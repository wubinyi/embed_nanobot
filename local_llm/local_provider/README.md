# RKLLM Local Provider

This directory contains the executable startup path that bridges the validated
RKLLM runtime on the Radxa into a nanobot-compatible local provider.

## What it does

- starts the upstream RKLLM Flask backend from `rknn-llm-src/examples/rkllm_server_demo`
- skips the upstream hardcoded `sudo bash fix_freq_*` step so the service can start unattended
- exposes an OpenAI-compatible adapter at `http://127.0.0.1:18000/v1/chat/completions`
- lets nanobot use the existing `custom` provider without any core code changes

## Start the provider

```bash
bash local_llm/local_provider/start_local_provider.sh
```

Optional environment overrides:

```bash
RKLLM_MODEL_PATH=/absolute/path/to/model.rkllm \
RKLLM_TARGET_PLATFORM=rk3588 \
RKLLM_OPENAI_PORT=18000 \
bash local_llm/local_provider/start_local_provider.sh
```

## Health check

```bash
curl http://127.0.0.1:18000/health
curl http://127.0.0.1:18000/v1/models
```

## Nanobot config

Use `local_llm/runtime/local_rkllm.json` for the validated local-provider test.
That config points nanobot at a dedicated RKLLM workspace so old `cli:direct`
history does not blow past the RKLLM context limit.

For the validated smoke path, run:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode rkllm
```

That helper also sets `NANOBOT_DISABLE_BUILTIN_SKILLS=1` and
`NANOBOT_DISABLE_TOOLS=1` so the real `nanobot agent` request fits inside this
model's `4096` token context window.

## Current limitation

The adapter is validated for standard chat and a real low-context `nanobot agent`
smoke run. The upstream RKLLM server's tool-calling output is tag-based rather
than fully OpenAI-native, so tool calling is best treated as experimental until
a broader assistant workflow is validated end-to-end.