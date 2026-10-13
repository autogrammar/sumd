"""SUMD MCP Server — exposes sumd as an MCP service with CQRS ES and DSL support.

Tools exposed:
  - parse_sumd       : parse a SUMD.md file and return structured data
  - validate_sumd    : validate a SUMD.md file and return errors
  - export_sumd      : export SUMD.md to json/yaml/toml/markdown
  - list_sections    : list section names and types from a SUMD document
  - get_section      : retrieve content of a specific section
  - info_sumd        : return project name, description and stats
  - generate_sumd    : generate SUMD.md from a JSON payload
  
CQRS ES Tools:
  - execute_command  : execute CQRS command
  - execute_query    : execute CQRS query
  - get_events       : get event history
  - get_aggregate    : get aggregate state
  
DSL Tools:
  - execute_dsl      : execute DSL expression
  - dsl_shell_info   : get DSL shell information
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from sumd.parser import SUMDParser, parse_file
from sumd.cqrs.events import EventStore
from sumd.cqrs.commands import CommandBus, SumdCommandHandler
from sumd.cqrs.queries import QueryBus, SumdQueryHandler
from sumd.cqrs.aggregates import EventSourcedRepository
from sumd.cqrs.sumd_aggregate import SumdAggregate
from sumd.dsl.shell import DSLShellServer

# ---------------------------------------------------------------------------
# CQRS ES Infrastructure
# ---------------------------------------------------------------------------

# Initialize CQRS ES components
event_store = EventStore(Path.home() / ".sumd" / "events")
command_bus = CommandBus(event_store)
query_bus = QueryBus(event_store)

# Register handlers
command_handler = SumdCommandHandler(event_store)
query_handler = SumdQueryHandler(event_store)

# Register command handlers
for cmd_type in [
    "create_sumd_document",
    "update_sumd_document", 
    "add_sumd_section",
    "remove_sumd_section",
    "validate_sumd_document",
    "scan_project",
    "generate_map",
    "execute_dsl_command",
]:
    command_bus.register_handler(cmd_type, command_handler)

# Register query handlers
for query_type in [
    "get_sumd_document",
    "list_sumd_sections",
    "get_sumd_section",
    "get_project_info",
    "get_event_history",
    "get_all_events",
    "search_documents",
    "get_validation_results",
    "execute_dsl_query",
]:
    query_bus.register_handler(query_type, query_handler)

# Initialize DSL shell server
dsl_server = DSLShellServer()

# Initialize repository
sumd_repository = EventSourcedRepository(event_store, SumdAggregate)


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = Server("sumd-mcp")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_MUTATION_ENV = "SUMD_MCP_ALLOW_MUTATION"


def _require_mutation(action: str) -> None:
    enabled = os.getenv(_MUTATION_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        raise PermissionError(
            f"MCP mutation '{action}' is disabled; start the server with {_MUTATION_ENV}=1"
        )


def _doc_to_dict(doc) -> dict[str, Any]:
    return {
        "project_name": doc.project_name,
        "description": doc.description,
        "sections": [
            {
                "name": s.name,
                "type": s.type.value,
                "content": s.content,
                "level": s.level,
            }
            for s in doc.sections
        ],
    }


def _resolve_path(path: str) -> Path:
    """Resolve path; if relative, resolve from CWD."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    return p


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="parse_sumd",
            description="Parse a SUMD.md file and return the full structured document as JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file (absolute or relative to CWD).",
                    }
                },
                "required": ["file"],
            },
        ),
        types.Tool(
            name="validate_sumd",
            description="Validate a SUMD.md file. Returns a list of validation errors (empty list = valid).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file.",
                    }
                },
                "required": ["file"],
            },
        ),
        types.Tool(
            name="export_sumd",
            description="Export a SUMD.md file to json, yaml, toml, or markdown format.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "yaml", "toml", "markdown"],
                        "description": "Output format.",
                        "default": "json",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output file path. If omitted, content is returned as string.",
                    },
                },
                "required": ["file"],
            },
        ),
        types.Tool(
            name="list_sections",
            description="List all section names and types in a SUMD document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file.",
                    }
                },
                "required": ["file"],
            },
        ),
        types.Tool(
            name="get_section",
            description="Get the content of a specific section from a SUMD document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file.",
                    },
                    "section": {
                        "type": "string",
                        "description": "Section name or type (e.g. 'Intent', 'intent', 'Dependencies').",
                    },
                },
                "required": ["file", "section"],
            },
        ),
        types.Tool(
            name="info_sumd",
            description="Return project name, description and section statistics for a SUMD document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the SUMD markdown file.",
                    }
                },
                "required": ["file"],
            },
        ),
        types.Tool(
            name="generate_sumd",
            description="Generate a SUMD.md document from a JSON payload.",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "SUMD document data with project_name, description, and sections array.",
                    },
                    "output": {
                        "type": "string",
                        "description": "Optional output file path. If omitted, content is returned as string.",
                    },
                },
                "required": ["data"],
            },
        ),
        # CQRS ES Tools
        types.Tool(
            name="execute_command",
            description="Execute a CQRS command on SUMD aggregate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command_type": {
                        "type": "string",
                        "enum": [
                            "create_sumd_document",
                            "update_sumd_document",
                            "add_sumd_section", 
                            "remove_sumd_section",
                            "validate_sumd_document",
                            "scan_project",
                            "generate_map",
                            "execute_dsl_command"
                        ],
                        "description": "Type of command to execute.",
                    },
                    "aggregate_id": {
                        "type": "string",
                        "description": "ID of the aggregate (usually file path).",
                    },
                    "data": {
                        "type": "object",
                        "description": "Command data payload.",
                    },
                },
                "required": ["command_type", "aggregate_id"],
            },
        ),
        types.Tool(
            name="execute_query",
            description="Execute a CQRS query to read SUMD data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": [
                            "get_sumd_document",
                            "list_sumd_sections",
                            "get_sumd_section",
                            "get_project_info",
                            "get_event_history",
                            "get_all_events",
                            "search_documents",
                            "get_validation_results",
                            "execute_dsl_query"
                        ],
                        "description": "Type of query to execute.",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Query parameters.",
                    },
                },
                "required": ["query_type"],
            },
        ),
        types.Tool(
            name="get_events",
            description="Get event history for an aggregate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "aggregate_id": {
                        "type": "string",
                        "description": "ID of the aggregate.",
                    },
                    "from_version": {
                        "type": "integer",
                        "description": "Starting version (default: 0).",
                        "default": 0,
                    },
                },
                "required": ["aggregate_id"],
            },
        ),
        types.Tool(
            name="get_aggregate",
            description="Get current state of a SUMD aggregate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "aggregate_id": {
                        "type": "string",
                        "description": "ID of the aggregate (usually file path).",
                    },
                },
                "required": ["aggregate_id"],
            },
        ),
        # DSL Tools
        types.Tool(
            name="execute_dsl",
            description="Execute a SUMD DSL expression.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dsl_expression": {
                        "type": "string",
                        "description": "DSL expression to execute.",
                    },
                    "context_vars": {
                        "type": "object",
                        "description": "Optional context variables.",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory for execution.",
                    },
                },
                "required": ["dsl_expression"],
            },
        ),
        types.Tool(
            name="dsl_shell_info",
            description="Get information about DSL shell capabilities.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


if hasattr(server, "list_tools"):
    list_tools = server.list_tools()(list_tools)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _tool_parse_sumd(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    doc = parse_file(path)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(_doc_to_dict(doc), indent=2, ensure_ascii=False),
        )
    ]


async def _tool_validate_sumd(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    doc = parse_file(path)
    parser = SUMDParser()
    errors = parser.validate(doc)
    result = json.dumps({"valid": len(errors) == 0, "errors": errors}, indent=2)
    return [types.TextContent(type="text", text=result)]


async def _tool_export_sumd(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    fmt = arguments.get("format", "json")
    output_path = arguments.get("output")
    doc = parse_file(path)
    data = _doc_to_dict(doc)
    if fmt == "markdown":
        content = doc.raw_content
    elif fmt == "yaml":
        import yaml

        content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    elif fmt == "toml":
        import toml

        content = toml.dumps(data)
    else:
        content = json.dumps(data, indent=2, ensure_ascii=False)
    if output_path:
        _require_mutation("export_sumd")
        out = _resolve_path(output_path)
        out.write_text(content, encoding="utf-8")
        return [types.TextContent(type="text", text=f"Exported to {out}")]
    return [types.TextContent(type="text", text=content)]


async def _tool_list_sections(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    doc = parse_file(path)
    sections = [
        {"name": s.name, "type": s.type.value, "level": s.level} for s in doc.sections
    ]
    return [
        types.TextContent(
            type="text", text=json.dumps(sections, indent=2, ensure_ascii=False)
        )
    ]


async def _tool_get_section(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    query = arguments["section"].lower()
    doc = parse_file(path)
    match = next(
        (s for s in doc.sections if s.name.lower() == query or s.type.value == query),
        None,
    )
    if match is None:
        return [
            types.TextContent(
                type="text", text=f'Section "{arguments["section"]}" not found.'
            )
        ]
    result = {
        "name": match.name,
        "type": match.type.value,
        "level": match.level,
        "content": match.content,
    }
    return [
        types.TextContent(
            type="text", text=json.dumps(result, indent=2, ensure_ascii=False)
        )
    ]


async def _tool_info_sumd(arguments: dict) -> list[types.TextContent]:
    path = _resolve_path(arguments["file"])
    doc = parse_file(path)
    info = {
        "project_name": doc.project_name,
        "description": doc.description,
        "section_count": len(doc.sections),
        "section_types": [s.type.value for s in doc.sections],
    }
    return [
        types.TextContent(
            type="text", text=json.dumps(info, indent=2, ensure_ascii=False)
        )
    ]


async def _tool_generate_sumd(arguments: dict) -> list[types.TextContent]:
    data = arguments["data"]
    output_path = arguments.get("output")
    lines: list[str] = [f"# {data.get('project_name', 'Project')}", ""]
    if data.get("description"):
        lines += [data["description"], ""]
    for section in data.get("sections", []):
        level = "#" * section.get("level", 2)
        lines += [f"{level} {section['name']}", ""]
        if section.get("content"):
            lines += [section["content"], ""]
    content = "\n".join(lines)
    if output_path:
        _require_mutation("generate_sumd")
        out = _resolve_path(output_path)
        out.write_text(content, encoding="utf-8")
        return [types.TextContent(type="text", text=f"Generated {out}")]
    return [types.TextContent(type="text", text=content)]


# ---------------------------------------------------------------------------
# CQRS ES Tool Handlers
# ---------------------------------------------------------------------------

async def _tool_execute_command(arguments: dict) -> list[types.TextContent]:
    """Execute CQRS command."""
    _require_mutation("execute_command")
    from sumd.cqrs.commands import (
        CreateSumdDocument,
        UpdateSumdDocument,
        AddSumdSection,
        RemoveSumdSection,
        ValidateSumdDocument,
        ScanProject,
        GenerateMap,
        ExecuteDslCommand,
    )
    
    command_type = arguments["command_type"]
    aggregate_id = arguments["aggregate_id"]
    data = arguments.get("data", {})
    
    # Create command based on type
    command_classes = {
        "create_sumd_document": CreateSumdDocument,
        "update_sumd_document": UpdateSumdDocument,
        "add_sumd_section": AddSumdSection,
        "remove_sumd_section": RemoveSumdSection,
        "validate_sumd_document": ValidateSumdDocument,
        "scan_project": ScanProject,
        "generate_map": GenerateMap,
        "execute_dsl_command": ExecuteDslCommand,
    }
    
    command_class = command_classes.get(command_type)
    if not command_class:
        return [types.TextContent(type="text", text=f"Unknown command type: {command_type}")]
    
    command = command_class(aggregate_id=aggregate_id, data=data)
    
    try:
        events = await command_bus.dispatch(command)
        result = {
            "command_type": command_type,
            "aggregate_id": aggregate_id,
            "events_generated": len(events),
            "success": True,
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Command execution failed: {e}")]


async def _tool_execute_query(arguments: dict) -> list[types.TextContent]:
    """Execute CQRS query."""
    from sumd.cqrs.queries import (
        GetSumdDocument,
        ListSumdSections,
        GetSumdSection,
        GetProjectInfo,
        GetEventHistory,
        GetAllEvents,
        SearchDocuments,
        GetValidationResults,
        ExecuteDslQuery,
    )
    
    query_type = arguments["query_type"]
    parameters = arguments.get("parameters", {})
    
    # Create query based on type
    query_classes = {
        "get_sumd_document": GetSumdDocument,
        "list_sumd_sections": ListSumdSections,
        "get_sumd_section": GetSumdSection,
        "get_project_info": GetProjectInfo,
        "get_event_history": GetEventHistory,
        "get_all_events": GetAllEvents,
        "search_documents": SearchDocuments,
        "get_validation_results": GetValidationResults,
        "execute_dsl_query": ExecuteDslQuery,
    }
    
    query_class = query_classes.get(query_type)
    if not query_class:
        return [types.TextContent(type="text", text=f"Unknown query type: {query_type}")]
    
    query = query_class(parameters=parameters)
    
    try:
        result = await query_bus.dispatch(query)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Query execution failed: {e}")]


async def _tool_get_events(arguments: dict) -> list[types.TextContent]:
    """Get event history."""
    aggregate_id = arguments["aggregate_id"]
    from_version = arguments.get("from_version", 0)
    
    try:
        events = event_store.get_events(aggregate_id, from_version)
        result = {
            "aggregate_id": aggregate_id,
            "from_version": from_version,
            "events": [event.to_dict() for event in events],
            "total_events": len(events),
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Failed to get events: {e}")]


async def _tool_get_aggregate(arguments: dict) -> list[types.TextContent]:
    """Get aggregate state."""
    aggregate_id = arguments["aggregate_id"]
    
    try:
        aggregate = await sumd_repository.get_by_id(aggregate_id)
        if not aggregate:
            return [types.TextContent(type="text", text=f"Aggregate not found: {aggregate_id}")]
        
        state = aggregate.get_state()
        return [types.TextContent(type="text", text=json.dumps(state, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Failed to get aggregate: {e}")]


# ---------------------------------------------------------------------------
# DSL Tool Handlers
# ---------------------------------------------------------------------------

async def _tool_execute_dsl(arguments: dict) -> list[types.TextContent]:
    """Execute DSL expression."""
    _require_mutation("execute_dsl")
    dsl_expression = arguments["dsl_expression"]
    context_vars = arguments.get("context_vars", {})
    working_directory = arguments.get("working_directory")
    
    if working_directory:
        dsl_server.working_directory = Path(working_directory)
        dsl_server.shell.context.working_directory = Path(working_directory)
    
    try:
        result = await dsl_server.execute_dsl(dsl_expression, context_vars)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"DSL execution failed: {e}")]


async def _tool_dsl_shell_info(arguments: dict) -> list[types.TextContent]:
    """Get DSL shell info."""
    try:
        info = await dsl_server.get_shell_info()
        return [types.TextContent(type="text", text=json.dumps(info, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Failed to get shell info: {e}")]


_TOOL_HANDLERS = {
    "parse_sumd": _tool_parse_sumd,
    "validate_sumd": _tool_validate_sumd,
    "export_sumd": _tool_export_sumd,
    "list_sections": _tool_list_sections,
    "get_section": _tool_get_section,
    "info_sumd": _tool_info_sumd,
    "generate_sumd": _tool_generate_sumd,
    # CQRS ES Tools
    "execute_command": _tool_execute_command,
    "execute_query": _tool_execute_query,
    "get_events": _tool_get_events,
    "get_aggregate": _tool_get_aggregate,
    # DSL Tools
    "execute_dsl": _tool_execute_dsl,
    "dsl_shell_info": _tool_dsl_shell_info,
}


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
        return await handler(arguments)
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Error: {exc}")]


if hasattr(server, "call_tool"):
    call_tool = server.call_tool()(call_tool)



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    import asyncio

    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
