# RK3588 Toolchain Log

## Goal

Record every local-LLM setup step executed on the Radxa Rock 5T.

## Session Log

| Timestamp | Step | Command | Result | Notes |
|-----------|------|---------|--------|-------|
| 2026-05-01 09:18 | Baseline check | `command -v ollama` | PASS | `ollama` not installed |
| 2026-05-01 09:18 | Platform check | `uname -m` | PASS | `aarch64` |
| 2026-05-01 09:18 | OS check | `cat /etc/os-release | sed -n '1,8p'` | PASS | Armbian 26 / Debian 13 |
| 2026-05-01 09:20 | Official install attempt | `bash local_llm/scripts/install_ollama.sh` | FAIL | Blocked by sudo prompt for `/usr/local` |
| 2026-05-01 09:27 | User-local install attempt | `bash local_llm/scripts/install_ollama.sh` | FAIL | GitHub ARM64 archive download unreachable from host |
| 2026-05-01 11:24 | Post-reboot runtime verification | `bash local_llm/scripts/install_ollama.sh` | PASS | Repo-local Ollama runtime already present at `local_llm/runtime/bin/ollama` |
| 2026-05-01 11:25 | Small-model download | `ollama pull qwen2.5:0.5b` | PASS | 397 MB model chosen for RK3588 CPU validation |
| 2026-05-01 11:25 | Context-safe alias creation | `ollama create qwen2.5:0.5b-nb -f local_llm/runtime/Modelfile.qwen2.5-0.5b-nb` | PASS | Alias sets `num_ctx 8192` for the agent path |
| 2026-05-01 11:26 | Config rendering | `/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py --local-model qwen2.5:0.5b-nb` | PASS | Generated local and remote runtime configs |
| 2026-05-01 11:32 | Direct local endpoint check | `curl -sS http://127.0.0.1:11434/v1/chat/completions ...` | PASS | Ollama returned `LOCAL_OK` directly |
| 2026-05-01 11:40 | Direct local agent timing | `time python -m nanobot agent -c local_llm/runtime/local_ollama.json ...` | PASS | Real local agent path returned `LOCAL_OK` in about `371s` |
| 2026-05-01 11:47 | Smoke runner revalidation | `bash local_llm/scripts/run_agent_smoke.sh --mode local` | PASS | Updated local timeout (`600s`) matches measured RK3588 latency |

## Summary

The Radxa host now has a working repo-local Ollama runtime and a validated local
agent workflow. The stable CPU-only path on this hardware uses the small-model
alias `qwen2.5:0.5b-nb` plus a longer local smoke timeout.
