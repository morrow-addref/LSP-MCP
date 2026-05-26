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
class LspConfig:
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


def load_config(workspace_root: str | None = None, language: str | None = None) -> LspConfig:
    """Load LSP server configuration from .github/lsp.json in the workspace root.

    Args:
        workspace_root: Path to the workspace root (defaults to cwd).
        language: Name of the server entry to use (e.g. "csharp"). Defaults to first entry.
    """
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

    if language:
        if language not in servers:
            available = ", ".join(servers.keys())
            raise ValueError(f"Server '{language}' not found in {config_path}. Available: {available}")
        server_name = language
    else:
        server_name = next(iter(servers))

    server_config = servers[server_name]

    command = server_config["command"]
    args = server_config.get("args", [])
    file_extensions = server_config.get("fileExtensions", {})

    root_uri = Path(workspace_root).as_uri()

    return LspConfig(
        command=command,
        args=args,
        workspace_root=workspace_root,
        root_uri=root_uri,
        file_extensions=file_extensions,
    )
