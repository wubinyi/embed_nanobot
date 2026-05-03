# RKLLM Install And Run On RK3588

## Scope

This guide records the validated steps for installing the RKLLM toolchain on the
Radxa Rock 5T and running the first real NPU-backed inference with an official
preconverted Qwen model.

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

## 7. Notes

- Use the native CMake path on the Radxa. Do not rely on `build-linux.sh`
  unless the missing cross-toolchain assumptions are fixed.
- This validated path is for RKLLM runtime testing, not yet nanobot provider
  integration.
- The current confirmed official Qwen path in this workspace is multimodal
  `Qwen3-VL-2B`, not a text-only `.rkllm` model.