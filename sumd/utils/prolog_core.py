import subprocess
import re
from pathlib import Path
from typing import Generator, Any, Dict, List, Optional, Union

# Try importing pyswip
try:
    import pyswip
    PYSWIP_AVAILABLE = True
except ImportError:
    PYSWIP_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# 🧠 PURE PYTHON PROLOG INTERPRETER (SLD Resolution)
# ─────────────────────────────────────────────────────────────

class Variable:
    """Represents a logical variable in our pure Python engine."""
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other) -> bool:
        return isinstance(other, Variable) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


class Term:
    """Represents a Prolog term (e.g. parent(john, mary))."""
    def __init__(self, op: str, *args: Any):
        self.op = op
        self.args = list(args)

    def __repr__(self) -> str:
        if not self.args:
            return self.op
        return f"{self.op}({', '.join(map(str, self.args))})"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Term) and
                self.op == other.op and
                self.args == other.args)


class Rule:
    """Represents a Prolog rule Head :- Body."""
    def __init__(self, head: Term, body: Optional[List[Term]] = None):
        self.head = head
        self.body = body or []

    def __repr__(self) -> str:
        if not self.body:
            return f"{self.head}."
        return f"{self.head} :- {', '.join(map(str, self.body))}."


def is_variable(x: Any) -> bool:
    if isinstance(x, Variable):
        return True
    if isinstance(x, str) and x:
        return (x[0].isupper() or x.startswith("_")) and re.match(r"^[A-Z_][a-zA-Z0-9_]*$", x) is not None
    return False


_ANON_COUNTER = 0


def _top_level_operator(text: str, operator: str) -> int:
    """Find an operator outside quoted atoms and compound arguments."""
    quote = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith(operator, index):
            return index
    return -1


def _parse_str_to_term(x: str) -> Any:
    x = x.strip()
    if x.startswith("'") and x.endswith("'") and len(x) >= 2:
        escapes = {"\\": "\\", "'": "'", "n": "\n", "r": "\r", "t": "\t"}
        return Term(re.sub(r"\\([\\'nrt])", lambda match: escapes[match[1]], x[1:-1]))
    if x.startswith("\\+"):
        return Term("\\+", to_term(x[2:].strip()))
    operator = _top_level_operator(x, "\\=")
    if operator >= 0:
        left, right = x[:operator], x[operator + 2:]
        return Term("\\=", to_term(left.strip()), to_term(right.strip()))
    m = re.match(r"^([a-z_][a-zA-Z0-9_]*)\((.*)\)$", x, re.DOTALL)
    if m:
        op, args_str = m.group(1), m.group(2)
        args = [to_term(a.strip()) for a in _split_body_terms(args_str) if a.strip()]
        return Term(op, *args)
    return Term(x)

def to_term(x: Any) -> Any:
    global _ANON_COUNTER
    if is_variable(x):
        var_name = str(x) if isinstance(x, str) else x.name
        if var_name.startswith("_"):
            _ANON_COUNTER += 1
            var_name = f"_anon_{_ANON_COUNTER}"
        return Variable(var_name)
    if isinstance(x, str):
        return _parse_str_to_term(x)
    return x


from dataclasses import dataclass

@dataclass
class _SplitState:
    terms: List[str]
    current_term: List[str]
    paren_depth: int
    in_quotes: bool
    escaped: bool = False

def _handle_quotes_and_parens(char: str, prev_char: str, state: _SplitState) -> bool:
    if state.in_quotes:
        state.current_term.append(char)
        if state.escaped:
            state.escaped = False
        elif char == "\\":
            state.escaped = True
        elif char == "'":
            state.in_quotes = False
        return True
    if char == "'":
        state.in_quotes = True
        state.current_term.append(char)
        return True
    if char == "(":
        state.paren_depth += 1
        state.current_term.append(char)
        return True
    if char == ")":
        if state.paren_depth > 0:
            state.paren_depth -= 1
        state.current_term.append(char)
        return True
    return False

def _handle_split_char(char: str, prev_char: str, state: _SplitState) -> None:
    if _handle_quotes_and_parens(char, prev_char, state):
        return
    if char == "," and state.paren_depth == 0:
        state.terms.append("".join(state.current_term).strip())
        state.current_term.clear()
    else:
        state.current_term.append(char)

def _split_body_terms(body_str: str) -> List[str]:
    """Splits comma-separated Prolog rule body into distinct term strings."""
    state = _SplitState(terms=[], current_term=[], paren_depth=0, in_quotes=False)
    for i, char in enumerate(body_str):
        prev = body_str[i-1] if i > 0 else ""
        _handle_split_char(char, prev, state)
    if state.current_term:
        state.terms.append("".join(state.current_term).strip())
    return [t for t in state.terms if t]


def _prolog_clauses(text: str) -> List[str]:
    """Split clauses and remove comments only outside quoted atom contents."""
    clauses = []
    current = []
    quote = None
    escaped = False
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "%":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            current.append("\n")
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            current.append(" ")
            continue
        elif char == "." and depth == 0 and (
            index + 1 == len(text) or text[index + 1].isspace()
            or text[index + 1] == "%" or text.startswith("/*", index + 1)
        ):
            clause = "".join(current).strip()
            if clause:
                clauses.append(clause)
            current = []
        else:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            current.append(char)
        index += 1
    clause = "".join(current).strip()
    if clause:
        clauses.append(clause)
    return clauses


class PythonPrologDB:
    """In-memory Prolog database for pure Python execution."""
    def __init__(self):
        self.rules: List[Rule] = []

    def add_fact(self, op: str, *args: Any):
        self.rules.append(Rule(Term(op, *[to_term(a) for a in args])))

    def add_rule(self, head: Term, body: List[Term]):
        self.rules.append(Rule(head, body))

    def parse_and_load(self, prolog_text: str):
        """Parses a simple Prolog file into rules/facts."""
        for c in _prolog_clauses(prolog_text):
            separator = _top_level_operator(c, ":-")
            if separator >= 0:
                head_str, body_str = c[:separator], c[separator + 2:]
                head = to_term(head_str.strip())
                # Parse comma separated body terms
                body = [to_term(b.strip()) for b in _split_body_terms(body_str.strip()) if b.strip()]
                self.add_rule(head, body)
            else:
                self.rules.append(Rule(to_term(c)))


def _unify_terms(x: Term, y: Term, subst: Dict[Variable, Any]) -> Optional[Dict[Variable, Any]]:
    if x.op != y.op or len(x.args) != len(y.args):
        return None
    new_subst = subst.copy()
    for ax, ay in zip(x.args, y.args):
        res = unify(ax, ay, new_subst)
        if res is None:
            return None
        new_subst = res
    return new_subst

def unify(x: Any, y: Any, subst: Dict[Variable, Any]) -> Optional[Dict[Variable, Any]]:
    """Logical unification of x and y under substitution subst."""
    x = resolve_val(x, subst)
    y = resolve_val(y, subst)
    if x == y:
        return subst
    if isinstance(x, Variable):
        return extend_subst(x, y, subst)
    if isinstance(y, Variable):
        return extend_subst(y, x, subst)
    if isinstance(x, Term) and isinstance(y, Term):
        return _unify_terms(x, y, subst)
    return None


def resolve_val(x: Any, subst: Dict[Variable, Any]) -> Any:
    while isinstance(x, Variable) and x in subst:
        x = subst[x]
    return x


def deep_resolve(x: Any, subst: Dict[Variable, Any]) -> Any:
    x = resolve_val(x, subst)
    if isinstance(x, Term):
        return Term(x.op, *[deep_resolve(arg, subst) for arg in x.args])
    return x


def extend_subst(v: Variable, val: Any, subst: Dict[Variable, Any]) -> Optional[Dict[Variable, Any]]:
    if occurs_check(v, val, subst):
        return None
    new_subst = subst.copy()
    new_subst[v] = val
    return new_subst


def occurs_check(v: Variable, val: Any, subst: Dict[Variable, Any]) -> bool:
    val = resolve_val(val, subst)
    if v == val:
        return True
    if isinstance(val, Term):
        return any(occurs_check(v, arg, subst) for arg in val.args)
    return False


def rename_variables(rule: Rule, suffix: int) -> Rule:
    """Rename variables in rule to avoid collisions in resolution."""
    var_map: Dict[Variable, Variable] = {}

    def rename(x: Any) -> Any:
        if isinstance(x, Variable):
            if x not in var_map:
                var_map[x] = Variable(f"{x.name}_{suffix}")
            return var_map[x]
        if isinstance(x, Term):
            return Term(x.op, *[rename(arg) for arg in x.args])
        return x

    new_head = rename(rule.head)
    new_body = [rename(b) for b in rule.body]
    return Rule(new_head, new_body)


class PythonPrologEngine:
    """SLD Resolution Logic Interpreter."""
    def __init__(self, db: PythonPrologDB):
        self.db = db
        self._var_counter = 0

    def query(self, goal_str: str) -> List[Dict[str, Any]]:
        goal = to_term(goal_str)
        results = []

        # We find all variables in the goal
        goal_vars = self._find_vars(goal)

        for subst in self._resolve([goal], {}):
            # Extract values for variables in query
            res = {}
            for gv in goal_vars:
                val = deep_resolve(gv, subst)
                # Helper formatting
                if isinstance(val, Term):
                    res[gv.name] = str(val)
                elif isinstance(val, Variable):
                    res[gv.name] = val.name
                else:
                    res[gv.name] = val
            results.append(res)

        return results

    def _find_vars(self, term: Any) -> List[Variable]:
        vars_set = set()
        def collect(t):
            if isinstance(t, Variable):
                vars_set.add(t)
            elif isinstance(t, Term):
                for arg in t.args:
                    collect(arg)
        collect(term)
        return list(vars_set)

    def _resolve_negation(self, first: Term, rest: List[Any], subst: Dict[Variable, Any]) -> Generator[Dict[Variable, Any], None, None]:
        inner_goal = first.args[0]
        if not list(self._resolve([inner_goal], subst)):
            yield from self._resolve(rest, subst)

    def _resolve_inequality(self, first: Term, rest: List[Any], subst: Dict[Variable, Any]) -> Generator[Dict[Variable, Any], None, None]:
        left = resolve_val(first.args[0], subst)
        right = resolve_val(first.args[1], subst)
        left_str = str(left) if not isinstance(left, Variable) else left
        right_str = str(right) if not isinstance(right, Variable) else right
        if left_str != right_str:
            yield from self._resolve(rest, subst)

    def _resolve_rule_step(self, first: Any, rest: List[Any], rule: Rule, subst: Dict[Variable, Any]) -> Generator[Dict[Variable, Any], None, None]:
        renamed_rule = rename_variables(rule, self._var_counter)
        new_subst = unify(first, renamed_rule.head, subst)
        if new_subst is not None:
            yield from self._resolve(renamed_rule.body + rest, new_subst)

    def _resolve(self, goals: List[Any], subst: Dict[Variable, Any]) -> Generator[Dict[Variable, Any], None, None]:
        if not goals:
            yield subst
            return

        first, rest = goals[0], goals[1:]
        is_term = isinstance(first, Term)

        if is_term and first.op in ("\\+", "not"):
            yield from self._resolve_negation(first, rest, subst)
            return

        if is_term and first.op in ("\\=", "\\\\=", "\\\\==", "\\="):
            yield from self._resolve_inequality(first, rest, subst)
            return

        self._var_counter += 1
        for rule in self.db.rules:
            yield from self._resolve_rule_step(first, rest, rule, subst)


# ─────────────────────────────────────────────────────────────
# 🛡️ THE HYBRID PROLOG ENGINE
# ─────────────────────────────────────────────────────────────

class HybridPrologEngine:
    """Hybrid Logic Engine delegating queries based on backend availability."""
    def __init__(self, prolog_file_path: Union[str, Path]):
        self.path = Path(prolog_file_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Prolog source file not found at: {self.path}")

        # Pre-load database for Python fallback
        self.py_db = PythonPrologDB()
        self.py_db.parse_and_load(self.path.read_text(encoding="utf-8"))
        self.py_engine = PythonPrologEngine(self.py_db)

    def query(self, query_str: str) -> List[Dict[str, Any]]:
        """Runs query against the best available Prolog backend."""
        # Trim ending dot if present
        query_str = query_str.strip().rstrip(".")

        # Try 1: PySwip Direct Bindings
        if PYSWIP_AVAILABLE:
            try:
                return self._query_pyswip(query_str)
            except Exception:
                # Fallback to next backend
                pass

        # Try 2: SWI-Prolog Subprocess (invokes swipl directly)
        if self._swipl_executable_exists():
            try:
                return self._query_subprocess(query_str)
            except Exception:
                pass

        # Try 3: Pure Python Fallback
        return self._query_python(query_str)

    def _query_pyswip(self, query_str: str) -> List[Dict[str, Any]]:
        """Executes query using the PySwip wrapper."""
        pyswip.Prolog.consult(str(self.path))
        results = list(pyswip.Prolog.query(query_str))

        # Clean results (convert PySwip atoms to strings)
        cleaned = []
        for r in results:
            clean_r = {}
            for k, v in r.items():
                if isinstance(v, bytes):
                    clean_r[k] = v.decode("utf-8")
                else:
                    clean_r[k] = str(v)
            cleaned.append(clean_r)
        return cleaned

    def _run_boolean_subprocess(self, query_str: str) -> List[Dict[str, Any]]:
        cmd = [
            "swipl", "-q", "-f", str(self.path),
            "-g", f"({query_str} -> write('true') ; write('false')), halt."
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return [{}] if res.stdout.strip() == "true" else []

    def _parse_swipl_output(self, stdout: str) -> List[Dict[str, Any]]:
        solutions = []
        current_sol = {}
        for line in stdout.splitlines():
            line = line.strip()
            if line == "---":
                if current_sol:
                    solutions.append(current_sol)
                    current_sol = {}
            elif ":" in line:
                k, v = line.split(":", 1)
                current_sol[k] = v
        if current_sol:
            solutions.append(current_sol)
        return solutions

    def _query_subprocess(self, query_str: str) -> List[Dict[str, Any]]:
        """Executes query by spawning a swipl process."""
        vars_found = list(set(re.findall(r"\b([A-Z][a-zA-Z0-9_]*)\b", query_str)))
        if not vars_found:
            return self._run_boolean_subprocess(query_str)

        print_goals = [f"format('~w:~w~n', ['{v}', {v}])" for v in vars_found]
        goal_exec = f"forall({query_str}, ( {' , '.join(print_goals)} , format('---~n') )), halt."
        
        cmd = ["swipl", "-q", "-f", str(self.path), "-g", goal_exec]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return self._parse_swipl_output(res.stdout)

    def _query_python(self, query_str: str) -> List[Dict[str, Any]]:
        """Pure Python fallback logic query."""
        return self.py_engine.query(query_str)

    def _swipl_executable_exists(self) -> bool:
        try:
            subprocess.run(["swipl", "--version"], capture_output=True)
            return True
        except FileNotFoundError:
            return False
