#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_URL = os.environ.get("RKLLM_BACKEND_URL", "http://127.0.0.1:8080/rkllm_chat")
LISTEN_HOST = os.environ.get("RKLLM_OPENAI_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("RKLLM_OPENAI_PORT", "18000"))
DEFAULT_MODEL = os.environ.get("RKLLM_MODEL_NAME", "qwen3-vl-2b-rkllm")
REQUEST_TIMEOUT = float(os.environ.get("RKLLM_BACKEND_TIMEOUT", "600"))

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _flatten_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    prompt_parts: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            content = "\n".join(part for part in text_parts if part)
        if content is None:
            continue
        content_text = str(content).strip()
        if not content_text:
            continue
        if role == "system":
            prompt_parts.append(f"System:\n{content_text}")
        elif role == "user":
            prompt_parts.append(f"User:\n{content_text}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant:\n{content_text}")
        elif role == "tool":
            tool_name = message.get("name") or "tool"
            prompt_parts.append(f"Tool {tool_name} result:\n{content_text}")

    flattened_prompt = "\n\n".join(prompt_parts).strip()
    if not flattened_prompt:
        flattened_prompt = "User:\nRespond to the last request."
    return [{"role": "user", "content": flattened_prompt}]


def _json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error_payload(message: str, status: int = 500) -> tuple[dict[str, Any], int]:
    return {
        "error": {
            "message": message,
            "type": "rkllm_error",
            "code": status,
        }
    }, status


def _extract_tool_calls(content: str) -> tuple[str | None, list[dict[str, Any]]]:
    tool_calls = []
    cleaned = content
    for raw_match in _TOOL_CALL_PATTERN.findall(content):
        try:
            parsed = json.loads(raw_match)
        except json.JSONDecodeError:
            continue
        tool_name = parsed.get("name")
        arguments = parsed.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        tool_calls.append(
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": tool_name or "unknown_tool",
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )
        cleaned = _TOOL_CALL_PATTERN.sub("", cleaned, count=1)
    cleaned = cleaned.strip()
    return (cleaned or None), tool_calls


def _normalize_response(upstream: dict[str, Any], requested_model: str | None) -> dict[str, Any]:
    choices = upstream.get("choices") or []
    if not choices:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": requested_model or DEFAULT_MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }
            ],
            "usage": upstream.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    first = choices[-1]
    message = first.get("message") or {}
    content = message.get("content") or ""
    normalized_content, tool_calls = _extract_tool_calls(content)
    finish_reason = "tool_calls" if tool_calls else (first.get("finish_reason") or "stop")

    normalized_message: dict[str, Any] = {
        "role": "assistant",
        "content": normalized_content,
    }
    if tool_calls:
        normalized_message["tool_calls"] = tool_calls

    usage = upstream.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "id": upstream.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": upstream.get("created") or int(time.time()),
        "model": requested_model or upstream.get("model") or DEFAULT_MODEL,
        "choices": [
            {
                "index": 0,
                "message": normalized_message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def _stream_chunks(response_payload: dict[str, Any]) -> list[str]:
    choice = (response_payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    tool_calls = message.get("tool_calls")
    chunk_id = response_payload.get("id") or f"chatcmpl-{uuid.uuid4().hex}"
    created = response_payload.get("created") or int(time.time())
    model = response_payload.get("model") or DEFAULT_MODEL
    chunks: list[str] = []

    first_delta: dict[str, Any] = {"role": "assistant"}
    if content:
        first_delta["content"] = content
    if tool_calls:
        first_delta["tool_calls"] = tool_calls

    chunks.append(
        json.dumps(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": first_delta, "finish_reason": None}],
            },
            ensure_ascii=False,
        )
    )
    chunks.append(
        json.dumps(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": choice.get("finish_reason") or "stop",
                    }
                ],
                "usage": response_payload.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
            ensure_ascii=False,
        )
    )
    return chunks


def _post_backend(payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        BACKEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer no-key"},
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


class RKLLMOpenAIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            _json_response(self, {"status": "ok", "backend": BACKEND_URL, "model": DEFAULT_MODEL})
            return
        if self.path == "/v1/models":
            _json_response(
                self,
                {
                    "object": "list",
                    "data": [{"id": DEFAULT_MODEL, "object": "model", "owned_by": "rkllm"}],
                },
            )
            return
        payload, status = _error_payload(f"Unsupported path: {self.path}", HTTPStatus.NOT_FOUND)
        _json_response(self, payload, status)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            payload, status = _error_payload(f"Unsupported path: {self.path}", HTTPStatus.NOT_FOUND)
            _json_response(self, payload, status)
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = self.rfile.read(length) if length else b"{}"
            request_data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload, status = _error_payload("Invalid JSON body", HTTPStatus.BAD_REQUEST)
            _json_response(self, payload, status)
            return

        messages = request_data.get("messages")
        if not isinstance(messages, list) or not messages:
            payload, status = _error_payload("messages must be a non-empty list", HTTPStatus.BAD_REQUEST)
            _json_response(self, payload, status)
            return

        backend_payload = {
            "model": request_data.get("model") or DEFAULT_MODEL,
            "messages": _flatten_messages(messages),
            "stream": False,
            "enable_thinking": bool(request_data.get("reasoning_effort")),
        }
        if request_data.get("tools"):
            backend_payload["tools"] = request_data["tools"]

        try:
            upstream = _post_backend(backend_payload)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            payload, status = _error_payload(f"RKLLM backend HTTP {error.code}: {detail}", error.code)
            _json_response(self, payload, status)
            return
        except URLError as error:
            payload, status = _error_payload(f"RKLLM backend unreachable: {error.reason}", HTTPStatus.BAD_GATEWAY)
            _json_response(self, payload, status)
            return
        except Exception as error:  # pragma: no cover - defensive integration path
            payload, status = _error_payload(f"RKLLM backend error: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)
            _json_response(self, payload, status)
            return

        normalized = _normalize_response(upstream, request_data.get("model"))
        if request_data.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            for chunk in _stream_chunks(normalized):
                self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        _json_response(self, normalized)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        syslog_line = "%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args)
        print(syslog_line, end="")


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), RKLLMOpenAIHandler)
    print(f"RKLLM OpenAI adapter listening on http://{LISTEN_HOST}:{LISTEN_PORT}/v1/chat/completions")
    print(f"Forwarding requests to {BACKEND_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()