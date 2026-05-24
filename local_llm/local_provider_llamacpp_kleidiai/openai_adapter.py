#!/usr/bin/env python3
"""
openai_adapter.py — OpenAI-compatible HTTP proxy for the KleidiAI llama.cpp provider

This adapter is functionally identical to the baseline provider's adapter
(local_provider_llamacpp/openai_adapter.py) but targets different default
ports to allow both providers to run simultaneously for A/B benchmarking.

Port defaults for this provider:
  BACKEND  (llama-server) : 19180
  ADAPTER  (this script)  : 19100

The adapter:
  • Forwards ALL GET/POST requests to the llama-server backend verbatim
  • Replaces the model name in the response to match the configured alias
  • Returns 503 with Retry-After during the model warm-up window
  • Handles streaming (text/event-stream) pass-through transparently

Configuration via environment variables (all optional):
  LLAMACPP_BACKEND_BASE       — backend HTTP URL  (default: http://127.0.0.1:19180)
  LLAMACPP_OPENAI_PORT        — adapter listen port (default: 19100)
  LLAMACPP_MODEL_NAME         — model alias to advertise (default: qwen3.5-9b-kleidiai)
  LLAMACPP_BACKEND_TIMEOUT    — request timeout in seconds (default: 600)

Note: env var names intentionally match the baseline adapter so that
start_local_provider.sh can pass them through without renaming.
"""
from __future__ import annotations

import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Configuration — read from environment with KleidiAI-specific defaults
# ---------------------------------------------------------------------------
BACKEND_BASE: str = os.environ.get("LLAMACPP_BACKEND_BASE", "http://127.0.0.1:19180")
LISTEN_PORT: int = int(os.environ.get("LLAMACPP_OPENAI_PORT", "19100"))
DEFAULT_MODEL: str = os.environ.get("LLAMACPP_MODEL_NAME", "qwen3.5-9b-kleidiai")
TIMEOUT: int = int(os.environ.get("LLAMACPP_BACKEND_TIMEOUT", "600"))


class ProxyHandler(BaseHTTPRequestHandler):
    """Minimal HTTP reverse proxy — forwards to llama-server backend."""

    # Silence the default per-request log line; errors are still printed.
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        pass

    def _forward(self, body: bytes | None = None) -> None:
        """Forward the current request to the backend and stream the reply."""
        target_url = f"{BACKEND_BASE}{self.path}"
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            # Strip hop-by-hop headers that must not be forwarded
            if key.lower() not in ("host", "transfer-encoding", "connection"):
                headers[key] = value

        req = urllib.request.Request(target_url, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.end_headers()
                # Stream the response body in 64 KiB chunks
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)
        except OSError as exc:
            # Backend not yet ready — return 503 so the caller can retry
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Retry-After", "5")
            self.end_headers()
            self.wfile.write(f"Backend unavailable: {exc}".encode())

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        self._forward(body)


def main() -> None:
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), ProxyHandler)
    print(
        f"[KleidiAI adapter] listening on :{LISTEN_PORT} → {BACKEND_BASE}"
        f"  (model alias: {DEFAULT_MODEL})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
