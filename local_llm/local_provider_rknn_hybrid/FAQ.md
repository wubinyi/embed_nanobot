## Q: Why does RKNN show "Not support core mask: 7, fallback to single core auto mode"?

This means the runtime accepted matmul execution, but rejected your explicit request to pin all three NPU cores (mask 7 = core0|core1|core2).

In practice, your workload still runs, but in runtime-selected auto mode, which on this machine/library falls back to single-core behavior.

### Why this happens

1. The loaded `librknnrt.so` is an older/incompatible build for this API path.
2. `rknn_matmul_set_core_mask()` is not supported for this runtime + matmul path combination.
3. The runtime reports `NN Compiler/Model Version is 0.0.0`, which is a strong signal that this vendored library is not the full production runtime for multi-core scheduling.

### What it means for benchmark numbers

- `run_ms` can still look reasonable for a single kernel call.
- End-to-end throughput is lower than expected for 3-core NPU.
- Any speedup projection assuming 3-core parallelism is not currently valid on this runtime.

### How to verify quickly

Run the Phase 2.1 benchmark and check two fields:

- `rknn_core_mask_ret`
  - `0` means explicit core mask accepted
  - non-zero means rejected (fallback path)
- Runtime log line contains "fallback to single core auto mode"

If either indicates fallback, treat results as single-core constrained.

### Supporting data / commands

```bash
cd /home/wubinyi/workspace/embed_nanobot
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/benchmark_roundtrip.py \
  --m 1 --k 3584 --n 3584 --repeats 20
```

Observed in this project run:

- `rknn_core_mask_ret: -1`
- `Not support core mask: 7, fallback to single core auto mode`
- `NN Compiler/Model Version is 0.0.0`
