from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


DEFAULT_SOURCE = Path.home() / ".embed_nanobot" / "config.json"
DEFAULT_SHARED_OUTPUT = Path(__file__).resolve().parents[1] / "runtime"
DEFAULT_OLLAMA_OUTPUT = Path(__file__).resolve().parents[1] / "local_provider_ollama" / "runtime"
DEFAULT_LOCAL_MODEL = "qwen2.5:0.5b-nb"
DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _disable_hybrid_router(config: dict) -> None:
    config.pop("hybridRouter", None)


def _render_local_config(source: dict, local_model: str, api_base: str) -> dict:
    config = deepcopy(source)
    defaults = config.setdefault("agents", {}).setdefault("defaults", {})
    defaults["model"] = local_model
    defaults["provider"] = "ollama"
    providers = config.setdefault("providers", {})
    ollama = providers.setdefault("ollama", {})
    ollama["apiKey"] = ollama.get("apiKey") or "dummy"
    ollama["apiBase"] = ollama.get("apiBase") or api_base
    _disable_hybrid_router(config)
    return config


def _render_remote_config(source: dict) -> dict:
    config = deepcopy(source)
    _disable_hybrid_router(config)
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Render local and remote nanobot agent configs.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Path to the source user config")
    parser.add_argument("--shared-output-dir", type=Path, default=DEFAULT_SHARED_OUTPUT, help="Directory for shared generated runtime configs")
    parser.add_argument("--ollama-output-dir", type=Path, default=DEFAULT_OLLAMA_OUTPUT, help="Directory for generated Ollama runtime configs")
    parser.add_argument("--local-model", default=DEFAULT_LOCAL_MODEL, help="Model string for the local ollama config")
    parser.add_argument("--local-api-base", default=DEFAULT_LOCAL_BASE, help="OpenAI-compatible base URL for the local runtime")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    shared_output_dir = args.shared_output_dir.expanduser().resolve()
    ollama_output_dir = args.ollama_output_dir.expanduser().resolve()
    data = _load_json(source)

    local_path = ollama_output_dir / "local_ollama.json"
    remote_path = shared_output_dir / "remote_current.json"
    _write_json(local_path, _render_local_config(data, args.local_model, args.local_api_base))
    _write_json(remote_path, _render_remote_config(data))

    print(f"Wrote {local_path}")
    print(f"Wrote {remote_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
