# Agent Validation

## Goal

Record real `nanobot agent` validation runs for both local and remote providers.

## Planned checks

| Mode | Command | Expected signal |
|------|---------|-----------------|
| Local | `bash local_llm/scripts/run_agent_smoke.sh --mode local` | Output contains `LOCAL_OK` |
| Remote | `bash local_llm/scripts/run_agent_smoke.sh --mode remote` | Output contains `REMOTE_OK` |

## Results

### Remote provider

- Command: `bash local_llm/scripts/run_agent_smoke.sh --mode remote`
- Result: PASS
- Evidence: `REMOTE_OK` returned by real `nanobot agent`

### Local provider

- Command: `bash local_llm/scripts/run_agent_smoke.sh --mode local`
- Result: PASS
- Model: `qwen2.5:0.5b-nb` (`qwen2.5:0.5b` with `num_ctx 8192`)
- Evidence: real `nanobot agent` returned `LOCAL_OK`
- Runtime note: direct wall-clock measurement on the Radxa was about `371s`, so
	the smoke helper now defaults to `600s` for local mode

### Local endpoint isolation check

- Command: `curl -sS http://127.0.0.1:11434/v1/chat/completions ...`
- Result: PASS
- Evidence: Ollama returned `LOCAL_OK` directly for the same model
- Purpose: separate provider/runtime health from CLI wrapper behavior

### Conclusion

Both the real remote-agent path and the real local-agent path are verified on
the Radxa 5T. The validated local workflow uses the repo-local Ollama runtime
plus the small-model alias `qwen2.5:0.5b-nb`.
