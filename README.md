# LSP-MCP

Minimal MCP server that bridges any Language Server Protocol (LSP) server to AI agents (e.g. GitHub Copilot CLI). Exposes diagnostics (errors, warnings, info) as lightweight tool calls.

## Tools

Tools are generated per server entry, prefixed by the config key:

| Tool pattern | Description |
|------|-------------|
| `{prefix}_get_errors` | Compilation errors for a file (or all open files) |
| `{prefix}_get_warnings` | Warnings for a file |
| `{prefix}_get_info` | Info/hint diagnostics (style rules, analyzers) |
| `lsp_status` | All LSP servers' state for debugging |

Example with `"cs"` prefix: `cs_get_errors`, `cs_get_warnings`, `cs_get_info`

## Setup

```bash
pip install -e .
```

## Configuration

Create `.github/lsp.json` in your workspace root. Each key is the **tool prefix** — keep it short:

```json
{
  "lspServers": {
    "cs": {
      "command": "path/to/Microsoft.CodeAnalysis.LanguageServer.exe",
      "args": ["--stdio", "--autoLoadProjects"],
      "fileExtensions": {".cs": "csharp"}
    }
  }
}
```

Multiple servers generate prefixed tools automatically:

```json
{
  "lspServers": {
    "cs": { "command": "...", "args": [...], "fileExtensions": {".cs": "csharp"} },
    "py": { "command": "pyright-langserver", "args": ["--stdio"], "fileExtensions": {".py": "python"} }
  }
}
```

This exposes: `cs_get_errors`, `cs_get_warnings`, `py_get_errors`, `py_get_warnings`, etc.

The `fileExtensions` map tells the server which `languageId` to send in `textDocument/didOpen`. Common extensions (`.py`, `.ts`, `.go`, `.rs`, etc.) are detected automatically if omitted.

## Usage with Copilot CLI

Add to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "lsp": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "lsp_mcp", "--workspace", "/path/to/your/project"]
    }
  }
}
```

## CLI Options

```
lsp-mcp [--workspace PATH]
```

- `--workspace`, `-w`: Workspace root containing `.github/lsp.json` (defaults to cwd)

## How It Works

1. Reads `.github/lsp.json` to find the LSP server command
2. Spawns the language server with `--stdio` and performs the LSP initialize handshake
3. On tool call: opens the file, pulls diagnostics via `textDocument/diagnostic`, filters by severity
4. Falls back to push diagnostics (`publishDiagnostics`) if pull returns empty
5. Returns concise JSON with line, column, severity, message, and diagnostic code
