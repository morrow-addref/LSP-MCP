"""Entry point for the LSP-MCP server."""

import argparse
import asyncio
import logging
import sys

from .config import load_config
from .lsp_client import LspClient
from .mcp_server import create_server


async def run(workspace: str | None, language: str | None):
    """Start the LSP client and MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("lsp_mcp")

    # Load config
    config = load_config(workspace, language=language)
    logger.info("Workspace: %s", config.workspace_root)

    # Create LSP client and MCP server
    lsp_client = LspClient(config)
    mcp_server = create_server(lsp_client)

    # Run MCP server on stdio — start immediately so the CLI can handshake.
    # LSP initialization happens lazily on first tool call.
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        # Start LSP in background while MCP handshake proceeds
        init_task = asyncio.ensure_future(lsp_client.start())
        init_task.add_done_callback(
            lambda t: logger.info("LSP ready") if not t.exception()
            else logger.error("LSP init failed: %s", t.exception())
        )
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

    # Cleanup
    await lsp_client.stop()


def main():
    parser = argparse.ArgumentParser(description="LSP-MCP: Language server bridge for AI agents")
    parser.add_argument(
        "--workspace", "-w",
        type=str,
        default=None,
        help="Workspace root directory (defaults to cwd). Must contain .github/lsp.json.",
    )
    parser.add_argument(
        "--language", "-l",
        type=str,
        default=None,
        help="Server entry name from lsp.json (e.g. 'csharp', 'python'). Defaults to first entry.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(args.workspace, args.language))
    except KeyboardInterrupt:
        pass
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
