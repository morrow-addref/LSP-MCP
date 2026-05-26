"""Configuration loader — reads .github/lsp.json from the workspace root."""

import json
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class LspConfig:
    command: str
    args: list[str]
    workspace_root: str
    root_uri: str


def load_config(workspace_root: str | None = None) -> LspConfig:
    """Load LSP server configuration from .github/lsp.json in the workspace root."""
    if workspace_root is None:
        workspace_root = os.getcwd()

    workspace_root = os.path.abspath(workspace_root)
    config_path = os.path.join(workspace_root, ".github", "lsp.json")

    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"LSP config not found at {config_path}. "
            f"Expected format: {{\"lspServers\": {{\"csharp\": {{\"command\": \"...\", \"args\": [...]}}}}}}"
        )

    with open(config_path) as f:
        data = json.load(f)

    servers = data.get("lspServers", {})
    if not servers:
        raise ValueError(f"No LSP servers defined in {config_path}")

    # Use the first available server (typically "csharp")
    server_name = next(iter(servers))
    server_config = servers[server_name]

    command = server_config["command"]
    args = server_config.get("args", [])

    # Convert workspace root to a file URI
    root_uri = Path(workspace_root).as_uri()

    return LspConfig(
        command=command,
        args=args,
        workspace_root=workspace_root,
        root_uri=root_uri,
    )
