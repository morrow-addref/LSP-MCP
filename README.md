# LSP-MCP

Minimal MCP server that bridges a Roslyn C# language server to AI agents (e.g. GitHub Copilot CLI).

## Tools Exposed

| Tool | Description |
|------|-------------|
| `get_diagnostics` | Compiler errors/warnings for a file or all open files |
| `call_hierarchy_in` | Find all callers of a symbol |
| `call_hierarchy_out` | Find all functions called by a symbol |
| `type_supers` | Base types and interfaces |
| `type_subs` | Derived types and implementations |

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
      "args": ["--stdio", "--autoLoadProjects"]
    }
  }
}
```

## Usage with Copilot CLI

Add to `.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "roslyn": {
      "type": "stdio",
      "command": "lsp-mcp",
      "args": ["--workspace", "/path/to/your/project"]
    }
  }
}
```

## How It Works

1. On startup, reads `.github/lsp.json` to find the LSP server command
2. Spawns Roslyn with `--stdio` and performs the LSP initialize handshake
3. Caches diagnostics pushed by Roslyn via `textDocument/publishDiagnostics`
4. Exposes 5 MCP tools that agents can call for code intelligence
