"""A command stored in a quoted atom must never become Prolog syntax."""
import pytest

from sumd.prolog_engine import PythonPrologDB, Term, Variable, _split_body_terms, to_term


@pytest.mark.parametrize("value", [
    "doql adopt . --output app.doql.css",
    "printf '%s' done",
    "path/*literal comment*/tail",
    "echo value :- still command data",
    r"echo \+ and \= literally",
    "C:\\folder\\",
    "first line\nsecond line\twith tab",
])
def test_quoted_atom_round_trips_as_one_fact_argument(value):
    encoded = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t")
    db = PythonPrologDB()
    db.parse_and_load(f"command('{encoded}', done).")
    assert len(db.rules) == 1
    rule = db.rules[0]
    assert rule.body == []
    assert rule.head.op == "command"
    assert rule.head.args == [Term(value), Term("done")]


def test_actual_comments_and_rule_delimiters_still_parse():
    db = PythonPrologDB()
    db.parse_and_load("% line comment.\nfact(one)./* block. */\nfact(two).\nselected(X) :- fact(X).")
    assert [rule.head.op for rule in db.rules] == ["fact", "fact", "selected"]
    assert db.rules[-1].body == [Term("fact", Variable("X"))]


def test_inequality_operator_outside_quotes_keeps_its_meaning():
    assert to_term(r"X \= Y") == Term(r"\=", Variable("X"), Variable("Y"))
    assert to_term(r"'X \= Y'") == Term(r"X \= Y")


def test_argument_split_handles_escaped_trailing_backslash():
    assert _split_body_terms(r"'path\\', next") == [r"'path\\'", "next"]
