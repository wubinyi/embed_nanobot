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
| 2026-05-01 14:21 | Live hybrid config enablement | `cp ~/.embed_nanobot/config.json ... && edit hybrid settings` | PASS | Set `agents.defaults.provider` to `hybrid`, enabled `hybrid_router`, removed duplicate disabled block |
| 2026-05-01 14:28 | Live hybrid local-route check | `python -m nanobot agent -m 'Reply with exactly HYBRID_LOCAL_OK and nothing else.' --logs --no-markdown` | PASS | Router logged local branch and final output was `HYBRID_LOCAL_OK` |
| 2026-05-01 14:33 | Hybrid API-route check | `python -m nanobot agent -c local_llm/runtime/hybrid_remote_probe.json -m 'Write a correct Python implementation of Dijkstra\'s algorithm ... HYBRID_REMOTE_OK.' --logs --no-markdown` | PASS | Router logged API branch; remote provider then rejected the request with `unsupported_country_region_territory` |
| 2026-05-01 14:38 | RKLLM upstream repo fetch | `git clone --depth 1 https://github.com/airockchip/rknn-llm.git /tmp/rknn-llm` | PASS | Official sources reachable on the Radxa through proxy |
| 2026-05-01 14:40 | RKLLM board-side build attempt | `cd /tmp/rknn-llm/examples/rkllm_api_demo/deploy && bash build-linux.sh` | FAIL | Build script assumes toolchain components not yet installed on the Radxa; first blocker was missing `cmake` |
| 2026-05-01 16:02 | RKLLM native build prerequisites | `sudo apt-get install -y build-essential cmake` | PASS | Installed native compiler toolchain and CMake on the Radxa |
| 2026-05-01 16:10 | RKLLM native demo build | `cmake ../.. -DCMAKE_BUILD_TYPE=Release && make -j4` | PASS | Built `examples/rkllm_api_demo/deploy/build/native/llm_demo` with native GCC 14 |
| 2026-05-01 16:11 | RKLLM runtime linkage probe | `cmake --install . && LD_LIBRARY_PATH=./lib ./llm_demo /tmp/does-not-exist.rkllm 16 32` | PASS | `librkllmrt.so` loaded and reported `platform: RK3588`; init failed only because no `.rkllm` model file was provided |
| 2026-05-03 10:05 | RKNPU kernel package check | `uname -r && dpkg -l 'linux-image*' | grep rk35xx && apt-cache search '^linux-image.*rk35xx'` | PASS | Running `6.1.115-vendor-rk35xx`; host package is `linux-image-vendor-rk35xx 26.2.1` |
| 2026-05-03 10:06 | RKNPU runtime evidence capture | `sed -n '1,5p' local_llm/rknn-llm-src/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64/demo.log` | PASS | RKLLM demo reported `rknpu driver version: 0.9.8` on RK3588 |
| 2026-05-03 09:40 | RKLLM local-provider launcher fix | `bash local_llm/local_provider/start_local_provider.sh` | PASS | Launcher now normalizes the copied RKLLM demo server to the model-safe `4096` context and starts both backend `:8080` and adapter `:18000` |
| 2026-05-03 09:42 | RKLLM adapter direct probe | `curl -s http://127.0.0.1:18000/v1/chat/completions ...` | PASS | OpenAI-compatible adapter returned `RKLLM_OK` after flattening OpenAI chat history into a single backend prompt |
| 2026-05-03 09:45 | RKLLM agent smoke | `bash local_llm/scripts/run_agent_smoke.sh --mode rkllm` | PASS | Real `nanobot agent` returned `RKLLM_OK` when built-in skills and tool schemas were disabled for the low-context smoke path |

## Summary

The Radxa host now has a working repo-local Ollama runtime and a validated local
agent workflow. The stable CPU-only path on this hardware uses the small-model
alias `qwen2.5:0.5b-nb` plus a longer local smoke timeout.

Hybrid mode is also live-validated on the Radxa: the local branch completed
end-to-end, and the remote branch was reached successfully before hitting the
current remote provider region restriction.

The RKLLM board-side toolchain is now installed and validated far enough for a
real `nanobot agent` smoke path on RK3588. The current model is still limited
to a hard `4096` context window, so the validated RKLLM smoke path uses a
reduced-context agent configuration.

For this Radxa setup, the kernel-side RKNPU driver is already supplied by the
Armbian vendor kernel package `linux-image-vendor-rk35xx`; driver installation
therefore means installing or upgrading that kernel package and rebooting into
the vendor kernel.

The two earlier `FAIL` entries are historical setup attempts, not current
blockers. They were superseded by the later successful repo-local install and
validation steps in the same log.
