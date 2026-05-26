"""Configuration loader — reads .github/lsp.json from the workspace root."""

import json
import os
from pathlib import Path
from dataclasses import dataclass, field


# Built-in extension→languageId map for common languages
_DEFAULT_EXTENSIONS: dict[str, str] = {
    ".cs": "csharp",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".lua": "lua",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
}


@dataclass
class LspServerConfig:
    """Configuration for a single LSP server."""
    prefix: str
    command: str
    args: list[str]
    workspace_root: str
    root_uri: str
    file_extensions: dict[str, str] = field(default_factory=dict)

    def language_id_for(self, file_path: str) -> str:
        """Resolve the LSP languageId for a file based on its extension."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in self.file_extensions:
            return self.file_extensions[ext]
        if ext in _DEFAULT_EXTENSIONS:
            return _DEFAULT_EXTENSIONS[ext]
        return "plaintext"


@dataclass
class WorkspaceConfig:
    """Top-level configuration: workspace root + all LSP server entries."""
    workspace_root: str
    servers: dict[str, LspServerConfig] = field(default_factory=dict)


def load_config(workspace_root: str | None = None) -> WorkspaceConfig:
    """Load LSP server configuration from .github/lsp.json in the workspace root.

    Returns a WorkspaceConfig with zero or more server entries.
    Missing or empty config is not an error — the MCP server starts with no LSP tools.
    """
    if workspace_root is None:
        workspace_root = os.getcwd()

    workspace_root = os.path.abspath(workspace_root)
    config_path = os.path.join(workspace_root, ".github", "lsp.json")

    if not os.path.isfile(config_path):
        return WorkspaceConfig(workspace_root=workspace_root)

    with open(config_path) as f:
        data = json.load(f)

    servers_data = data.get("lspServers", {})
    root_uri = Path(workspace_root).as_uri()

    servers: dict[str, LspServerConfig] = {}
    for prefix, server_data in servers_data.items():
        servers[prefix] = LspServerConfig(
            prefix=prefix,
            command=server_data["command"],
            args=server_data.get("args", []),
            workspace_root=workspace_root,
            root_uri=root_uri,
            file_extensions=server_data.get("fileExtensions", {}),
        )

    return WorkspaceConfig(workspace_root=workspace_root, servers=servers)
