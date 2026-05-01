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
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py --local-model qwen2.5:0.5b-nb
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

Result: PASS

Observed output:

```text
🐈 nanobot
LOCAL_OK
PASS: found LOCAL_OK in .../agent_local_20260501_114725.log
```

Interpretation:

- the real `nanobot agent` path works
- the generated local config is being used
- the local Ollama runtime on the Radxa is reachable and completes the request
- RK3588 CPU inference is slow enough that local smoke needed a longer timeout

### 5. Ollama installation attempts

Executed:

```bash
bash local_llm/scripts/install_ollama.sh
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/bin:$PATH
ollama pull qwen2.5:0.5b
ollama create qwen2.5:0.5b-nb -f local_llm/runtime/Modelfile.qwen2.5-0.5b-nb
```

Result: PASS

Observed outcomes:

- the helper recognizes an existing repo-local runtime after reboot
- the working installer targets current `ollama.com` ARM64 archives (`.tar.zst` or `.tgz`)
- the validated local model is `qwen2.5:0.5b-nb`

### 6. Direct endpoint isolation and timing checks

Executed:

```bash
curl -sS http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' -d '{...}'
time /home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/runtime/local_ollama.json -m 'Reply with exactly LOCAL_OK and nothing else.' --no-logs
```

Result: PASS

Observed:

- direct Ollama endpoint returned `LOCAL_OK`
- direct `nanobot agent` wall-clock time was about `371s`
- the original `180s` smoke timeout was shorter than the real local inference path

### 7. Live hybrid local-route validation

Executed:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -m 'Reply with exactly HYBRID_LOCAL_OK and nothing else.' --logs --no-markdown
```

Result: PASS

Observed:

- live config loaded with `agents.defaults.provider = "hybrid"`
- router logged `difficulty score=0.80 threshold=0.85`
- router logged `routing to LOCAL model`
- final output was `HYBRID_LOCAL_OK`

### 8. Hybrid API-route verification

Executed:

```bash
cp ~/.embed_nanobot/config.json local_llm/runtime/hybrid_remote_probe.json
perl -0pi -e 's/"difficultyThreshold": 0\.85/"difficultyThreshold": 0.30/' local_llm/runtime/hybrid_remote_probe.json
proxy_on && export NO_PROXY=127.0.0.1,localhost && export no_proxy=127.0.0.1,localhost
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/runtime/hybrid_remote_probe.json -m 'Write a correct Python implementation of Dijkstra\''s algorithm for an adjacency-list weighted graph, include a complexity explanation, and finish your response with the exact token HYBRID_REMOTE_OK.' --logs --no-markdown
```

Result: ROUTE VERIFIED, provider blocked

Observed:

- router logged `difficulty score=0.80 threshold=0.3`
- router logged `routing to API model (with PII sanitisation)`
- remote provider returned `unsupported_country_region_territory`

Interpretation:

- hybrid routing reached the remote provider path correctly
- the remaining failure is remote-provider policy, not local routing or local Ollama setup

### 9. RKLLM native toolchain and runtime probe

Executed:

```bash
sudo apt-get install -y build-essential cmake
cd /tmp/rknn-llm/examples/rkllm_api_demo/deploy
rm -rf build/native && mkdir -p build/native && cd build/native
cmake ../.. -DCMAKE_BUILD_TYPE=Release
make -j4
cmake --install .
cd /tmp/rknn-llm/examples/rkllm_api_demo/deploy/install/demo_Linux_aarch64
export LD_LIBRARY_PATH=./lib
./llm_demo /tmp/does-not-exist.rkllm 16 32
```

Result: PARTIAL PASS

Observed:

- native toolchain installation succeeded on the Radxa
- RKLLM demo built successfully with native GCC 14 and CMake
- runtime initialized and reported `rkllm-runtime version: 1.2.3, rknpu driver version: 0.9.8, platform: RK3588`
- final failure was `failed to open '/tmp/does-not-exist.rkllm'`

Interpretation:

- board-side RKLLM runtime linkage is working
- end-to-end NPU inference is blocked only by the absence of a real converted `.rkllm` model file

---

## Real Hardware Validation

### Commands run

```bash
command -v ollama || true
uname -m
cat /etc/os-release | sed -n '1,8p'

bash local_llm/scripts/install_ollama.sh
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/bin:$PATH
ollama pull qwen2.5:0.5b
ollama create qwen2.5:0.5b-nb -f local_llm/runtime/Modelfile.qwen2.5-0.5b-nb

/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py --local-model qwen2.5:0.5b-nb

bash local_llm/scripts/run_agent_smoke.sh --mode remote
bash local_llm/scripts/run_agent_smoke.sh --mode local
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -m 'Reply with exactly HYBRID_LOCAL_OK and nothing else.' --logs --no-markdown
cp ~/.embed_nanobot/config.json local_llm/runtime/hybrid_remote_probe.json
perl -0pi -e 's/"difficultyThreshold": 0\.85/"difficultyThreshold": 0.30/' local_llm/runtime/hybrid_remote_probe.json
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/runtime/hybrid_remote_probe.json -m 'Write a correct Python implementation of Dijkstra\''s algorithm for an adjacency-list weighted graph, include a complexity explanation, and finish your response with the exact token HYBRID_REMOTE_OK.' --logs --no-markdown
sudo apt-get install -y build-essential cmake
cd /tmp/rknn-llm/examples/rkllm_api_demo/deploy && rm -rf build/native && mkdir -p build/native && cd build/native
cmake ../.. -DCMAKE_BUILD_TYPE=Release
make -j4
cmake --install .
cd /tmp/rknn-llm/examples/rkllm_api_demo/deploy/install/demo_Linux_aarch64 && export LD_LIBRARY_PATH=./lib && ./llm_demo /tmp/does-not-exist.rkllm 16 32
```

### Outcome summary

- Remote provider validation: successful through real `nanobot agent`
- Local provider validation: successful through real `nanobot agent` with `qwen2.5:0.5b-nb`
- Live hybrid local route: successful through real `nanobot agent`
- Hybrid API route: verified through router logs; remote provider blocked by `unsupported_country_region_territory`
- RKLLM board-side runtime: native build and runtime linkage verified on RK3588; no converted `.rkllm` model available yet for full inference
- Root cause of the earlier false local failure: the smoke helper timeout (`180s`) was shorter than the real RK3588 CPU inference time

---

## Known gaps

| Gap | Impact | Status |
|-----|--------|--------|
| Local CPU inference is slow on RK3588 even for the validated small model | Local smoke runs can take about 6 minutes | Known limitation |
| Validated local model alias creation is still a manual step | Extra setup work before first render | Follow-up opportunity |
| Workspace-selected `.conda` env differs from documented `embed_nanobot` env | Could confuse future setup work | Mitigated in smoke runner |
| Remote hybrid branch currently fails on OpenRouter region policy | Prevents a fully successful remote hybrid response from this location | External blocker |
| RKLLM still needs a converted `.rkllm` model file | Prevents full NPU inference validation after the runtime probe | External/input blocker |
