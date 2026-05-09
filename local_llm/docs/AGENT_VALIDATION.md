# Agent Validation

## Goal

Record real `nanobot agent` validation runs for both local and remote providers.

## Planned checks

| Mode | Command | Expected signal |
|------|---------|-----------------|
| Local | `bash local_llm/scripts/run_agent_smoke.sh --mode local` | Output contains `LOCAL_OK` |
| Remote | `bash local_llm/scripts/run_agent_smoke.sh --mode remote` | Output contains `REMOTE_OK` |
| RKLLM local provider | `bash local_llm/scripts/run_agent_smoke.sh --mode rkllm` | Output contains `RKLLM_OK` |
| Hybrid local route | real `nanobot agent` with live `~/.embed_nanobot/config.json` | Output contains `HYBRID_LOCAL_OK` and router log shows `routing to LOCAL model` |
| Hybrid API route | real `nanobot agent` with probe config threshold `0.30` | Router log shows `routing to API model` |

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

### RKLLM local-provider validation

- Provider start command: `bash local_llm/local_provider_rkllm/start_local_provider.sh`
- Adapter probe: `curl -s http://127.0.0.1:18000/v1/chat/completions ...`
- Agent smoke command: `bash local_llm/scripts/run_agent_smoke.sh --mode rkllm`
- Result: PASS
- Evidence:
	- direct adapter probe returned `RKLLM_OK`
	- real `nanobot agent` smoke returned `RKLLM_OK`
- Runtime note: the validated smoke path uses a dedicated RKLLM workspace and disables built-in skills plus tool schemas to fit the model's hard `4096` token context limit

### Hybrid local-route validation

- Command: `/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -m 'Reply with exactly HYBRID_LOCAL_OK and nothing else.' --logs --no-markdown`
- Config: live `~/.embed_nanobot/config.json` updated to `agents.defaults.provider = "hybrid"` with `hybrid_router.localModel = "qwen2.5:0.5b-nb"` and `difficultyThreshold = 0.85`
- Result: PASS
- Evidence:
	- router log: `[HybridRouter] difficulty score=0.80 threshold=0.85`
	- router log: `[HybridRouter] routing to LOCAL model`
	- final agent output: `HYBRID_LOCAL_OK`

### Hybrid API-route validation

- Command: `/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/runtime/hybrid_remote_probe.json -m 'Write a correct Python implementation of Dijkstra\'s algorithm for an adjacency-list weighted graph, include a complexity explanation, and finish your response with the exact token HYBRID_REMOTE_OK.' --logs --no-markdown`
- Config: probe config derived from the live config with `difficultyThreshold = 0.30` to force the hard-task branch
- Result: ROUTE VERIFIED, provider blocked
- Evidence:
	- router log: `[HybridRouter] difficulty score=0.80 threshold=0.3`
	- router log: `[HybridRouter] routing to API model (with PII sanitisation)`
	- remote provider response: `unsupported_country_region_territory`
- Interpretation: the hybrid router reached the remote branch correctly; the remaining failure is upstream provider region policy, not local hybrid wiring

### Conclusion

The real remote-agent path, the real local-agent path, the RKLLM local-provider
path, and the live hybrid local route are verified on the Radxa 5T. The hybrid
API route is also verified up to the remote provider boundary; the current
blocker is the remote provider's region policy, not hybrid-router control flow.
The validated local workflows now include both the repo-local Ollama runtime
plus the small-model alias `qwen2.5:0.5b-nb`, and the RKLLM adapter bridge on
port `18000`.
