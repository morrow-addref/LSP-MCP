"""LSP client — manages a language server subprocess and JSON-RPC communication."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from .config import LspServerConfig

logger = logging.getLogger(__name__)


class LspClient:
    """Async LSP client that spawns a language server and communicates via stdio JSON-RPC."""

    def __init__(self, config: LspServerConfig):
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._diagnostics: dict[str, list[dict]] = {}
        self._open_docs: set[str] = set()
        self._doc_version: dict[str, int] = {}
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._initialized = False
        self._diagnostics_event = asyncio.Event()
        self._server_capabilities: dict = {}
        self._stderr_task: asyncio.Task | None = None

    @property
    def diagnostics(self) -> dict[str, list[dict]]:
        return self._diagnostics

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def start(self):
        """Spawn the LSP server and perform the initialize handshake."""
        command = [self._config.command] + self._config.args

        logger.info("Spawning LSP server: %s", " ".join(command))
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._writer_task = asyncio.create_task(self._write_loop())
        self._reader_task = asyncio.create_task(self._read_loop())
        # Log stderr in background
        self._stderr_task = asyncio.create_task(self._read_stderr())

        # Initialize handshake
        init_params = {
            "processId": os.getpid(),
            "rootUri": self._config.root_uri,
            "rootPath": self._config.workspace_root,
            "workspaceFolders": [
                {"uri": self._config.root_uri, "name": os.path.basename(self._config.workspace_root)},
            ],
            "capabilities": {
                "textDocument": {
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                        "codeDescriptionSupport": True,
                    },
                    "callHierarchy": {"dynamicRegistration": False},
                    "typeHierarchy": {"dynamicRegistration": False},
                    "synchronization": {
                        "dynamicRegistration": False,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                        "didSave": True,
                    },
                },
                "window": {
                    "workDoneProgress": True,
                },
                "workspace": {
                    "workspaceFolders": True,
                    "didChangeConfiguration": {"dynamicRegistration": False},
                },
            },
        }

        result = await self.send_request("initialize", init_params)
        self._server_capabilities = result.get("capabilities", {})
        logger.info("LSP server initialized: %s", result.get("serverInfo", {}).get("name", "unknown"))
        logger.info("Server capabilities keys: %s", list(self._server_capabilities.keys()))
        await self.send_notification("initialized", {})
        self._initialized = True

    async def _read_stderr(self):
        """Log stderr output from the LSP server process."""
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.debug("LSP stderr: %s", line.decode("utf-8", errors="replace").strip())
        except asyncio.CancelledError:
            return

    async def stop(self):
        """Gracefully shut down the LSP server."""
        if not self._process:
            return
        try:
            await asyncio.wait_for(self.send_request("shutdown", None), timeout=5)
            await self.send_notification("exit", None)
        except (asyncio.TimeoutError, Exception):
            pass
        finally:
            if self._process.returncode is None:
                self._process.kill()
            if self._writer_task:
                self._writer_task.cancel()
            if self._reader_task:
                self._reader_task.cancel()
            if self._stderr_task:
                self._stderr_task.cancel()

    async def send_request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        msg_id = self._next_id
        self._next_id += 1

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params

        await self._write_queue.put(msg)
        return await asyncio.wait_for(future, timeout=30)

    async def send_notification(self, method: str, params: Any):
        """Send a JSON-RPC notification (no response expected)."""
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._write_queue.put(msg)

    async def open_document(self, file_path: str) -> str:
        """Open (or reopen) a document for diagnostics. Returns the URI."""
        uri = Path(file_path).as_uri()

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            raise RuntimeError(f"Cannot read file: {e}")

        # Always close and reopen to ensure the server analyzes current disk content
        if uri in self._open_docs:
            await self.send_notification("textDocument/didClose", {
                "textDocument": {"uri": uri},
            })

        language_id = self._config.language_id_for(file_path)
        self._doc_version[uri] = self._doc_version.get(uri, 0) + 1
        await self.send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": self._doc_version[uri],
                "text": text,
            }
        })
        self._open_docs.add(uri)
        # Clear stale cached diagnostics
        self._diagnostics.pop(uri, None)
        return uri

    async def wait_for_diagnostics(self, uri: str, timeout: float = 5.0) -> list[dict]:
        """Wait for diagnostics to arrive for a URI using an event-based approach."""
        # If already cached, return immediately
        if uri in self._diagnostics:
            return self._diagnostics[uri]

        # Wait for the diagnostics event to fire (set by _handle_notification)
        self._diagnostics_event.clear()
        try:
            await asyncio.wait_for(self._diagnostics_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        return self._diagnostics.get(uri, [])

    # --- Internal JSON-RPC transport ---

    async def _write_loop(self):
        """Drain the write queue and send messages to the LSP server's stdin."""
        try:
            while True:
                msg = await self._write_queue.get()
                if msg is None:
                    break
                body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
                header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                self._process.stdin.write(header + body)
                await self._process.stdin.drain()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.error("LSP write loop error", exc_info=True)
            self._fail_pending("Writer stopped")

    async def _read_loop(self):
        """Read JSON-RPC messages from the LSP server's stdout."""
        try:
            while True:
                msg = await self._read_message()
                if msg is None:
                    break
                self._dispatch_message(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.error("LSP read loop error", exc_info=True)

    async def _read_message(self) -> dict | None:
        """Read one Content-Length framed JSON-RPC message."""
        stdout = self._process.stdout
        if stdout is None:
            return None

        headers: dict[str, str] = {}
        while True:
            line = await stdout.readline()
            if not line:
                return None
            line_str = line.decode("ascii").strip()
            if not line_str:
                break
            if ":" in line_str:
                key, _, value = line_str.partition(":")
                headers[key.strip().lower()] = value.strip()

        content_length = int(headers.get("content-length", 0))
        if content_length == 0:
            return None

        body = await stdout.readexactly(content_length)
        return json.loads(body)

    def _dispatch_message(self, msg: dict):
        """Route an incoming JSON-RPC message."""
        if "id" in msg and "method" not in msg:
            # Response to our request
            msg_id = msg["id"]
            future = self._pending.pop(msg_id, None)
            if future is None:
                return
            if "error" in msg:
                err = msg["error"]
                future.set_exception(
                    RuntimeError(f"LSP error {err.get('code', '?')}: {err.get('message', 'unknown')}")
                )
            else:
                future.set_result(msg.get("result"))

        elif "method" in msg and "id" not in msg:
            # Notification from server
            self._handle_notification(msg["method"], msg.get("params"))

        elif "method" in msg and "id" in msg:
            # Server-initiated request — must respond
            response = self._build_response(msg["id"], msg["method"], msg.get("params"))
            self._write_queue.put_nowait(response)

    def _handle_notification(self, method: str, params: dict | None):
        """Handle LSP notifications — primarily diagnostics caching."""
        if method == "textDocument/publishDiagnostics" and params:
            uri = params.get("uri", "")
            self._diagnostics[uri] = params.get("diagnostics", [])
            self._diagnostics_event.set()
        elif method == "window/logMessage" and params:
            level = params.get("type", 4)
            message = params.get("message", "")
            if level <= 2:
                logger.warning("LSP: %s", message)
            else:
                logger.debug("LSP: %s", message)
        elif method == "$/progress" and params:
            token = params.get("token", "")
            value = params.get("value", {})
            kind = value.get("kind", "")
            message = value.get("message", "")
            if kind or message:
                logger.info("Progress [%s]: %s %s", token, kind, message)

    def _build_response(self, msg_id: int, method: str, params: dict | None) -> dict:
        """Build a response to a server-initiated request."""
        result = None
        if method == "workspace/configuration":
            items = (params or {}).get("items", [])
            result = [None for _ in items]
        # window/workDoneProgress/create, client/registerCapability → null result
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _fail_pending(self, reason: str):
        """Fail all pending request futures."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))
        self._pending.clear()
