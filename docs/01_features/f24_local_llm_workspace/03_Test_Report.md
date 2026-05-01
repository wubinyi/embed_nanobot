# f24: Radxa Local LLM Workspace — Test Report

**Task**: Radxa 5T local LLM workspace + real agent validation  
**Date**: 2026-05-01  
**Environment**: Radxa Rock 5T, Armbian 26 / Debian 13, conda env `embed_nanobot`

---

## Validation Class

`real-hardware required`

Reason:

- local runtime installation targets the actual Radxa 5T
- agent validation must use the real `nanobot agent` path
- the task outcome depends on actual machine networking and local runtime reachability

---

## Executed checks

### 1. Baseline environment checks

Executed:

```bash
command -v ollama || true
uname -m
cat /etc/os-release | sed -n '1,8p'
```

Observed:

- architecture: `aarch64`
- OS: Armbian 26.2.1 / Debian 13 Trixie
- `ollama`: not installed on `PATH`

### 2. Config rendering

Executed:

```bash
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python local_llm/scripts/render_agent_configs.py
```

Result: PASS

Generated:

- `local_llm/runtime/local_ollama.json`
- `local_llm/runtime/remote_current.json`

### 3. Remote real-agent validation

Executed:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode remote
```

Result: PASS

Observed output:

```text
🐈 nanobot
REMOTE_OK
PASS: found REMOTE_OK in .../agent_remote_20260501_093333.log
```

### 4. Local real-agent validation

Executed:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode local
```

Result: FAIL

Observed output:

```text
🐈 nanobot
Error calling LLM: Connection error.
FAIL: nanobot agent exited non-zero for local
```

Interpretation:

- the real `nanobot agent` path works
- the generated local config is being used
- the local LLM endpoint is unreachable because no Ollama server is available on `http://localhost:11434/v1`

### 5. Ollama installation attempts

Executed:

```bash
bash local_llm/scripts/install_ollama.sh
```

Result: FAIL (external blocker)

Observed outcomes:

- official installer path requested sudo for `/usr/local`
- user-local fallback path attempted ARM64 archive install
- archive download failed because outbound GitHub access was not reachable from this host

---

## Real Hardware Validation

### Commands run

```bash
command -v ollama || true
uname -m
cat /etc/os-release | sed -n '1,8p'

bash local_llm/scripts/install_ollama.sh

/home/wubinyi/workspace/embed_nanobot/.conda/bin/python local_llm/scripts/render_agent_configs.py

bash local_llm/scripts/run_agent_smoke.sh --mode remote
bash local_llm/scripts/run_agent_smoke.sh --mode local
```

### Outcome summary

- Remote provider validation: successful through real `nanobot agent`
- Local provider validation: failed through real `nanobot agent` because no reachable local Ollama server could be installed or started
- Root cause of local failure: external network restriction to GitHub blocked Ollama installation on the Radxa host

---

## Known gaps

| Gap | Impact | Status |
|-----|--------|--------|
| No reachable GitHub download path for Ollama ARM64 archive | Blocks local runtime install | External blocker |
| No local Ollama daemon on `localhost:11434` | Local agent smoke fails with connection error | Consequence of blocker |
| Workspace-selected `.conda` env differs from documented `embed_nanobot` env | Could confuse future setup work | Mitigated in smoke runner |
