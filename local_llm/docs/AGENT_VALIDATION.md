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
- Result: FAIL
- Evidence: `Error calling LLM: Connection error.` followed by `FAIL: nanobot agent exited non-zero for local`
- Root cause: no reachable Ollama server at `http://localhost:11434/v1`

### Conclusion

The real remote-agent path is verified. The real local-agent path is wired and
attempted, but remains blocked by the missing Ollama runtime on this Radxa host.
