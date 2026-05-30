# RKNPU Driver Install On Radxa RK3588

## Scope

This file documents how to get the Rockchip NPU kernel driver working on the
Radxa Rock 5T used by this repository.

Important detail for this board:

- The RKNPU driver is a kernel driver.
- On this Radxa setup, it is delivered by the Armbian vendor kernel package,
  not by a separate `apt install rknpu-driver` package.
- The validated package on this host is `linux-image-vendor-rk35xx`.

Validated host state:

- Board: Radxa Rock 5T
- SoC: RK3588
- OS: Armbian 26.2.1 / Debian 13
- Kernel: `6.1.115-vendor-rk35xx`
- Kernel package: `linux-image-vendor-rk35xx 26.2.1`
- Verified runtime report: `rknpu driver version: 0.9.8`

## Install path used on this board

### 1. Confirm you are on the vendor RK3588 kernel track

```bash
uname -r
dpkg -l 'linux-image*' | grep rk35xx
apt-cache search '^linux-image.*rk35xx'
```

Expected result on the validated host:

```text
6.1.115-vendor-rk35xx
ii  linux-image-vendor-rk35xx 26.2.1 arm64 ...
```

If you are already on `vendor-rk35xx`, the RKNPU driver is already part of the
installed kernel image.

### 2. Install or refresh the vendor kernel package

If the host is missing the vendor kernel, install it:

```bash
sudo apt-get update
sudo apt-get install -y linux-image-vendor-rk35xx
```

If it is already installed, upgrade it in place:

```bash
sudo apt-get update
sudo apt-get install --only-upgrade -y linux-image-vendor-rk35xx
```

### 3. Reboot into the updated kernel

```bash
sudo reboot
```

After reboot, confirm the running kernel:

```bash
uname -r
```

You want a `vendor-rk35xx` kernel, not `legacy-rk35xx`, for this validated
RKLLM path.

### 4. Verify that the driver is active

Preferred low-level probe:

```bash
sudo cat /sys/kernel/debug/rknpu/version
```

If that requires elevated access you do not want to grant immediately, a second
verified probe is to inspect the RKLLM demo log after a successful run:

```bash
sed -n '1,5p' /home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64/demo.log
```

Validated output from this workspace:

```text
I rkllm: rkllm-runtime version: 1.2.3, rknpu driver version: 0.9.8, platform: RK3588
```

That line proves the RKLLM runtime successfully talked to the live kernel NPU
driver on this board.

## What not to do on this host

- Do not look for a standalone Debian package named `rknpu-driver`; that is not
  how this validated Armbian setup ships the driver.
- Do not replace the vendor kernel with a generic kernel and expect RKLLM to
  keep working unchanged.
- Do not treat `librknnrt.so` or `librkllmrt.so` as the kernel driver. Those are
  user-space runtime libraries layered on top of the kernel driver.

## Relationship to RKLLM

The full stack on this board is:

1. `linux-image-vendor-rk35xx` provides the kernel-side RKNPU driver
2. `librknnrt.so` provides the RKNN user-space runtime
3. `librkllmrt.so` provides the RKLLM runtime
4. The RKLLM demo or your application uses those runtimes to talk to the NPU

If step 1 is missing or mismatched, RKLLM will not reach a working NPU-backed
inference path.

## Runtime upgrade attempt for 3-core matmul (2026-05-30)

Goal of this procedure: upgrade `librknnrt.so` and verify whether
`rknn_matmul_set_core_mask(ctx, 7)` can enable 3-core mode on RK3588.

### Step-by-step commands (exact)

1. Confirm currently available runtime copies:

```bash
cd /home/wubinyi/workspace/embed_nanobot
find . -name 'librknnrt.so' -o -name 'librknnrt*.so'
find /usr /opt /home/wubinyi -name 'librknnrt.so' 2>/dev/null | head -100
```

2. Confirm no dedicated apt runtime package exists on this host:

```bash
apt-cache search rknn
apt-cache search rkllm
apt-cache search rknpu
```

3. Pull latest upstream toolkit source (v2.3.2 at test time):

```bash
proxy_on
cd /tmp
rm -rf rknn-toolkit2
git clone --depth 1 https://github.com/airockchip/rknn-toolkit2.git
```

4. Locate and compare runtime hashes:

```bash
cd /tmp/rknn-toolkit2
find . -name 'librknnrt.so' -print0 | xargs -0 sha256sum

sha256sum \
  /tmp/rknn-toolkit2/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so \
  /home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so
```

5. Install the runtime to user-local path for explicit override testing:

```bash
mkdir -p /home/wubinyi/.local/lib
install -m 755 \
  /tmp/rknn-toolkit2/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so \
  /home/wubinyi/.local/lib/librknnrt.so
```

6. Verify with Phase 2.1 benchmark forcing this runtime:

```bash
cd /home/wubinyi/workspace/embed_nanobot
RKNNRT_PATH=/home/wubinyi/.local/lib/librknnrt.so \
  /home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/benchmark_roundtrip.py \
  --m 1 --k 3584 --n 3584 --repeats 20
```

### Outcome

- Core mask still rejected:
  - `Not support core mask: 7, fallback to single core auto mode`
  - `rknn_core_mask_ret: -1`
- Runtime still reports:
  - `NN Compiler/Model Version is 0.0.0`
- Therefore, on this host and currently available `librknnrt.so`, matmul 3-core
  pinning is **not** enabled by runtime upgrade alone.

### Practical conclusion

`librknnrt.so` was upgraded to the latest available upstream copy in user-local
path and benchmarked, but 3-core matmul remains unsupported. Phase 2 should
proceed assuming single-core matmul behavior unless Rockchip releases a runtime
that accepts core mask `7` for this API path.