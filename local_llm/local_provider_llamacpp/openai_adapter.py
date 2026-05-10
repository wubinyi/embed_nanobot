#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_BASE = os.environ.get("LLAMACPP_BACKEND_BASE", "http://127.0.0.1:19080")
LISTEN_HOST = os.environ.get("LLAMACPP_OPENAI_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LLAMACPP_OPENAI_PORT", "19000"))
DEFAULT_MODEL = os.environ.get("LLAMACPP_MODEL_NAME", "qwen3.5-9b-llamacpp")
REQUEST_TIMEOUT = float(os.environ.get("LLAMACPP_BACKEND_TIMEOUT", "600"))


def _proxy(method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, dict[str, str]]:
    request = Request(
        f"{BACKEND_BASE}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer no-key",
        },
        method=method,
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read()
        headers = {
            "Content-Type": response.headers.get_content_type() or "application/json",
        }
        return response.status, payload, headers


class LlamaCppAdapterHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        target_path = "/health" if self.path == "/health" else self.path
        try:
            status, payload, headers = _proxy("GET", target_path)
        except HTTPError as error:
            status = error.code
            payload = error.read()
            headers = {"Content-Type": "application/json"}
        except URLError as error:
            status = 502
            payload = json.dumps({"error": {"message": f"llama.cpp backend unreachable: {error.reason}"}}).encode("utf-8")
            headers = {"Content-Type": "application/json"}

        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            payload = json.dumps({"error": {"message": f"Unsupported path: {self.path}"}}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            request_data = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = json.dumps({"error": {"message": "Invalid JSON body"}}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        request_data["model"] = request_data.get("model") or DEFAULT_MODEL
        body = json.dumps(request_data).encode("utf-8")

        try:
            status, payload, headers = _proxy("POST", self.path, body)
        except HTTPError as error:
            status = error.code
            payload = error.read()
            headers = {"Content-Type": "application/json"}
        except URLError as error:
            status = 502
            payload = json.dumps({"error": {"message": f"llama.cpp backend unreachable: {error.reason}"}}).encode("utf-8")
            headers = {"Content-Type": "application/json"}

        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), LlamaCppAdapterHandler)
    print(f"llama.cpp adapter listening on http://{LISTEN_HOST}:{LISTEN_PORT}/v1/chat/completions")
    print(f"Forwarding requests to {BACKEND_BASE}")
    server.serve_forever()


if __name__ == "__main__":
    main()