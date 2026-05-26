"""MCP server — exposes LSP diagnostics tools, prefixed per language server."""

import json
import logging
import os

from mcp.server import Server
from mcp.types import TextContent, Tool

from .lsp_client import LspClient

logger = logging.getLogger(__name__)

# LSP severity codes
_SEV_ERROR = 1
_SEV_WARNING = 2
_SEV_INFO = 3
_SEV_HINT = 4

_SEVERITY_TOOLS = {
    "get_errors": (_SEV_ERROR,),
    "get_warnings": (_SEV_WARNING,),
    "get_info": (_SEV_INFO, _SEV_HINT),
}

_TOOL_DESCRIPTIONS = {
    "get_errors": "Get compiler errors for a file. Use after making code changes to catch compilation failures.",
    "get_warnings": "Get compiler warnings for a file. Use for code review or when asked about potential issues.",
    "get_info": "Get info/hint diagnostics (IDE analyzers, style rules). Only use when explicitly asked.",
}


def create_server(clients: dict[str, LspClient]) -> Server:
    """Create the MCP server with tool handlers bound to the given LSP clients.

    Args:
        clients: Mapping of prefix → LspClient (e.g. {"cs": client, "py": client}).
    """
    server = Server("lsp-mcp")

    _diag_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file. Empty string for all open files.",
            },
        },
        "required": [],
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools = []
        for prefix in sorted(clients.keys()):
            for tool_name, description in _TOOL_DESCRIPTIONS.items():
                tools.append(Tool(
                    name=f"{prefix}_{tool_name}",
                    description=f"[{prefix}] {description}",
                    inputSchema=_diag_schema,
                ))
        # Always expose lsp_status regardless of server count
        tools.append(Tool(
            name="lsp_status",
            description="Get LSP server status: initialization state, open documents, diagnostics cache.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "lsp_status":
            return await _handle_status(clients)

        # Parse prefix from tool name (e.g. "cs_get_errors" → prefix="cs", tool="get_errors")
        parts = name.split("_", 1)
        if len(parts) != 2 or parts[0] not in clients:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        prefix, tool_name = parts
        client = clients[prefix]

        if not client.is_initialized:
            return [TextContent(type="text", text=f"[{prefix}] LSP server not yet initialized. Please wait.")]

        if tool_name not in _SEVERITY_TOOLS:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        try:
            severities = set(_SEVERITY_TOOLS[tool_name])
            return await _handle_diagnostics(client, arguments, severities)
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e, exc_info=True)
            return [TextContent(type="text", text=f"Error: {e}")]

    return server


async def _pull_diagnostics(client: LspClient, uri: str) -> list[dict]:
    """Get diagnostics — pull first (fast), push-wait as fallback."""
    import asyncio

    try:
        pull_result = await client.send_request("textDocument/diagnostic", {
            "textDocument": {"uri": uri},
        })
        if pull_result and pull_result.get("items"):
            return pull_result["items"]
    except Exception as e:
        logger.debug("Pull diagnostics failed: %s", e)

    # If pull returned empty, wait briefly for push
    diagnostics = await client.wait_for_diagnostics(uri, timeout=2.0)
    if diagnostics:
        return diagnostics

    return []


async def _handle_diagnostics(client: LspClient, args: dict, severities: set[int]) -> list[TextContent]:
    """Handle diagnostics tool call, filtered by severity."""
    file_path = args.get("file_path", "")

    if file_path:
        file_path = os.path.abspath(file_path)
        uri = await client.open_document(file_path)
        all_diags = await _pull_diagnostics(client, uri)
        filtered = [d for d in all_diags if d.get("severity", 1) in severities]
        # Omit file path from output — caller already knows which file they asked about
        result = _format_diagnostics(None, filtered)
    else:
        # Return all cached diagnostics matching severity
        result = []
        for uri, diags in client.diagnostics.items():
            filtered = [d for d in diags if d.get("severity", 1) in severities]
            if filtered:
                fp = _uri_to_path(uri)
                result.extend(_format_diagnostics(fp, filtered))

    if not result:
        sev_names = {1: "errors", 2: "warnings", 3: "info", 4: "hints"}
        label = "/".join(sev_names.get(s, "?") for s in sorted(severities))
        return [TextContent(type="text", text=f"No {label}.")]

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_status(clients: dict[str, LspClient]) -> list[TextContent]:
    """Return LSP server status for debugging."""
    status = {}
    for prefix, client in clients.items():
        status[prefix] = {
            "initialized": client.is_initialized,
            "open_documents": list(client._open_docs),
            "diagnostics_uris": list(client.diagnostics.keys()),
            "diagnostics_counts": {uri: len(diags) for uri, diags in client.diagnostics.items()},
        }
    if not status:
        return [TextContent(type="text", text="No LSP servers configured. Create .github/lsp.json in the workspace root.")]
    return [TextContent(type="text", text=json.dumps(status, indent=2))]


def _format_diagnostics(file_path: str | None, diagnostics: list[dict]) -> list[dict]:
    """Format raw LSP diagnostics into concise output."""
    result = []
    for diag in diagnostics:
        start = diag.get("range", {}).get("start", {})
        severity_num = diag.get("severity", 1)
        severity_map = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        entry = {
            "line": start.get("line", 0) + 1,
            "col": start.get("character", 0) + 1,
            "severity": severity_map.get(severity_num, "unknown"),
            "message": diag.get("message", ""),
            "code": diag.get("code", ""),
        }
        if file_path:
            entry["file"] = file_path
        result.append(entry)
    return result


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a local path."""
    if uri.startswith("file:///"):
        path = uri[8:]
        return path.replace("/", os.sep)
    elif uri.startswith("file://"):
        return uri[7:]
    return uri
