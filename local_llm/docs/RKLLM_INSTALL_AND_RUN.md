# RKLLM Install And Run On RK3588

## Scope

This guide records the validated steps for installing the RKLLM toolchain on the
Radxa Rock 5T, validating the first real NPU-backed inference, and bridging the
result into nanobot through the custom local provider under `local_llm/local_provider/`.

Validated host:

- Board: Radxa Rock 5T
- SoC: RK3588
- OS: Armbian 26 / Debian 13
- Python env for nanobot: `/home/wubinyi/miniforge3/envs/embed_nanobot`

Validated model:

- LLM: `qwen3-vl-2b-instruct_w8a8_rk3588.rkllm`
- Vision encoder: `qwen3-vl-2b_vision_rk3588.rknn`

Related driver note:

- See `local_llm/docs/RKNPU_DRIVER_INSTALL.md` for the kernel-side RKNPU driver path on this Radxa host.

## 1. Install native build prerequisites

Use the board-native toolchain instead of the upstream cross-build helper.

Before building RKLLM, make sure the board is already running the vendor RK3588
kernel that carries the RKNPU driver. The validated install/update steps are in
`local_llm/docs/RKNPU_DRIVER_INSTALL.md`.

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake git
```

## 2. Clone the official RKLLM source tree

Keep the source in the project-local workspace:

```bash
cd /home/wubinyi/workspace/embed_nanobot/local_llm
git clone https://github.com/airockchip/rknn-llm.git rknn-llm-src
```

If the directory already exists, update it instead:

```bash
cd /home/wubinyi/workspace/embed_nanobot/local_llm/rknn-llm-src
git pull --ff-only
```

## 3. Build the multimodal demo natively

The upstream `build-linux.sh` path assumes a cross-toolchain layout that is not
present on the Radxa. Build with the system compiler instead.

```bash
cd /home/wubinyi/workspace/embed_nanobot/local_llm/rknn-llm-src/examples/multimodal_model_demo/deploy
rm -rf build/native
mkdir -p build/native
cd build/native
cmake ../.. -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++
make -j4
cmake --install .
```

The installed demo bundle ends up here:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/rknn-llm-src/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64
```

## 4. Prepare the model directory

Create a stable location for the official RK3588 model pair:

```bash
mkdir -p /home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b
```

Expected files:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm
/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b_vision_rk3588.rknn
```

## 5. Run the first real NPU inference

Run the official multimodal demo against the bundled sample image:

```bash
cd /home/wubinyi/workspace/embed_nanobot/local_llm/rknn-llm-src/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64
export LD_LIBRARY_PATH="$PWD/lib"
printf '0\nexit\n' | ./demo ./demo.jpg \
  /home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b_vision_rk3588.rknn \
  /home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm \
  128 4096 3 '<|vision_start|>' '<|vision_end|>' '<|image_pad|>'
```

## 6. What success looks like

The validated run reported these signals:

- `rkllm-runtime version: 1.2.3`
- `platform: RK3588`
- `rkllm init success`
- `main: LLM Model loaded in 2745.04 ms`
- `main: ImgEnc Model loaded in 1073.26 ms`
- `main: ImgEnc Model inference took 2205.06 ms`

The generated answer correctly described the bundled astronaut image, which is
the first confirmed real RK3588 NPU inference in this workspace.

## 7. Bridge RKLLM into nanobot's OpenAI-compatible provider path

After the raw RKLLM toolchain is working, the repo uses a thin bridge rather
than modifying nanobot's provider registry.

### Backend and adapter roles

- RKLLM backend: `http://127.0.0.1:8080/rkllm_chat`
- OpenAI-compatible adapter: `http://127.0.0.1:18000/v1/chat/completions`

The adapter lives in:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider/openai_adapter.py
```

The launcher that assembles and starts both layers lives in:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider/start_local_provider.sh
```

### Start the RKLLM local provider

```bash
cd /home/wubinyi/workspace/embed_nanobot
bash local_llm/local_provider/start_local_provider.sh
```

### Probe the bridge directly

```bash
curl http://127.0.0.1:18000/health

curl -s http://127.0.0.1:18000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-vl-2b-rkllm",
    "stream": false,
    "messages": [{"role": "user", "content": "Reply with exactly RKLLM_OK and nothing else."}]
  }'
```

### Bridge it into nanobot

Use the generated runtime config:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/local_rkllm.json
```

That config points nanobot's `custom` provider to `http://127.0.0.1:18000/v1`.

Smoke test:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode rkllm
```

Interactive run:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent \
  -c local_llm/runtime/local_rkllm.json \
  --workspace /home/wubinyi/workspace/embed_nanobot/local_llm/runtime/workspaces/rkllm \
  --session cli:rkllm-direct
```

### Current limitation

The validated `.rkllm` artifact in this workspace has a hard runtime context
limit of `4096`, even though upstream source-model metadata may advertise a much
larger theoretical context. The current smoke path therefore uses a reduced
prompt surface.

## 8. Notes

- Use the native CMake path on the Radxa. Do not rely on `build-linux.sh`
  unless the missing cross-toolchain assumptions are fixed.
- The current confirmed official Qwen path in this workspace is multimodal
  `Qwen3-VL-2B`, not a text-only `.rkllm` model.
- Provider integration is now validated through `local_llm/local_provider/`,
  but the current smoke path still uses a reduced-context agent setup because
  the active RKLLM model hard-caps runtime context at `4096`.