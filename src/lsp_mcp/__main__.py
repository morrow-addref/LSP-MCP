"""Entry point for the LSP-MCP server."""

import argparse
import asyncio
import logging
import sys

from .config import load_config
from .lsp_client import LspClient
from .mcp_server import create_server


async def run(workspace: str | None):
    """Start all LSP clients and the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("lsp_mcp")

    # Load config — gracefully handles missing lsp.json
    config = load_config(workspace)
    logger.info("Workspace: %s", config.workspace_root)
    logger.info("LSP servers configured: %s", list(config.servers.keys()) or "(none)")

    # Create one LspClient per server entry
    clients: dict[str, LspClient] = {}
    for prefix, server_config in config.servers.items():
        clients[prefix] = LspClient(server_config)

    # Create MCP server with all clients
    mcp_server = create_server(clients)

    # Run MCP server on stdio — start immediately so the CLI can handshake.
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        # Start all LSP servers in background while MCP handshake proceeds
        for prefix, client in clients.items():
            task = asyncio.ensure_future(client.start())
            task.add_done_callback(
                lambda t, p=prefix: logger.info("[%s] LSP ready", p) if not t.exception()
                else logger.error("[%s] LSP init failed: %s", p, t.exception())
            )
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

    # Cleanup all clients
    for client in clients.values():
        await client.stop()


def main():
    parser = argparse.ArgumentParser(description="LSP-MCP: Language server bridge for AI agents")
    parser.add_argument(
        "--workspace", "-w",
        type=str,
        default=None,
        help="Workspace root directory (defaults to cwd). Must contain .github/lsp.json.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(args.workspace))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
