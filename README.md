# LSP-MCP

Minimal MCP server that bridges any Language Server Protocol (LSP) server to AI agents (e.g. GitHub Copilot CLI). Exposes diagnostics (errors, warnings, info) as lightweight tool calls.

## Tools

| Tool | Description |
|------|-------------|
| `get_errors` | Compilation errors for a file (or all open files) |
| `get_warnings` | Warnings for a file |
| `get_info` | Info/hint diagnostics (style rules, analyzers) |
| `lsp_status` | LSP server state for debugging |

## Setup

```bash
pip install -e .
```

## Configuration

Create `.github/lsp.json` in your workspace root:

```json
{
  "lspServers": {
    "csharp": {
      "command": "path/to/Microsoft.CodeAnalysis.LanguageServer.exe",
      "args": ["--stdio", "--autoLoadProjects"],
      "fileExtensions": {
        ".cs": "csharp"
      }
    }
  }
}
```

Multiple servers can be defined — select one with `--language`:

```json
{
  "lspServers": {
    "csharp": { "command": "...", "args": [...], "fileExtensions": {".cs": "csharp"} },
    "python": { "command": "pyright-langserver", "args": ["--stdio"], "fileExtensions": {".py": "python"} }
  }
}
```

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
lsp-mcp [--workspace PATH] [--language NAME]
```

- `--workspace`, `-w`: Workspace root containing `.github/lsp.json` (defaults to cwd)
- `--language`, `-l`: Server entry name from lsp.json (defaults to first entry)

## How It Works

1. Reads `.github/lsp.json` to find the LSP server command
2. Spawns the language server with `--stdio` and performs the LSP initialize handshake
3. On tool call: opens the file, pulls diagnostics via `textDocument/diagnostic`, filters by severity
4. Falls back to push diagnostics (`publishDiagnostics`) if pull returns empty
5. Returns concise JSON with line, column, severity, message, and diagnostic code
