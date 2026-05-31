#include "ggml-backend-impl.h"
#include "ggml.h"
#include "ggml-impl.h"
#include "rknn_api.h"
#include "rknn_matmul_api.h"

#include <dlfcn.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef int (*rknn_matmul_create_fn)(rknn_matmul_ctx *, rknn_matmul_info *, rknn_matmul_io_attr *);
typedef rknn_tensor_mem * (*rknn_create_mem_fn)(rknn_context, uint32_t);
typedef int (*rknn_matmul_set_io_mem_fn)(rknn_matmul_ctx, rknn_tensor_mem *, rknn_matmul_tensor_attr *);
typedef int (*rknn_B_normal_layout_to_native_layout_fn)(void *, void *, int, int, rknn_matmul_info *);
typedef int (*rknn_matmul_set_core_mask_fn)(rknn_matmul_ctx, rknn_core_mask);
typedef int (*rknn_matmul_run_fn)(rknn_matmul_ctx);
typedef int (*rknn_destroy_mem_fn)(rknn_context, rknn_tensor_mem *);
typedef int (*rknn_matmul_destroy_fn)(rknn_matmul_ctx);
typedef int (*rknn_mem_sync_fn)(rknn_context, rknn_tensor_mem *, rknn_mem_sync_mode);

struct rknn_runtime_api {
    void * handle;
    const char * path;
    rknn_matmul_create_fn matmul_create;
    rknn_create_mem_fn create_mem;
    rknn_matmul_set_io_mem_fn set_io_mem;
    rknn_B_normal_layout_to_native_layout_fn b_normal_to_native;
    rknn_matmul_set_core_mask_fn set_core_mask;
    rknn_matmul_run_fn run;
    rknn_destroy_mem_fn destroy_mem;
    rknn_matmul_destroy_fn matmul_destroy;
    rknn_mem_sync_fn mem_sync;
};

struct rknn_backend_policy {
    float fp16_clip;
    float act_clip;
    float state_clip;
    float silu_input_clip;
    float attn_qkv_scale;
    float attn_out_scale;
    float ffn_scale;
    float ssm_scale;
};

struct rknn_backend_context {
    struct rknn_runtime_api runtime;
    struct rknn_backend_policy policy;
    bool runtime_loaded;
};

static struct ggml_backend_reg g_rknn_reg;
static struct ggml_backend_device g_rknn_device;
static const struct ggml_backend_i rknn_backend_i;

static size_t rknn_tensor_nelements(const struct ggml_tensor * tensor) {
    return (size_t) tensor->ne[0] * (size_t) tensor->ne[1] * (size_t) tensor->ne[2] * (size_t) tensor->ne[3];
}

static float rknn_clampf(float value, float limit) {
    if (value > limit) {
        return limit;
    }
    if (value < -limit) {
        return -limit;
    }
    return value;
}

static void rknn_copy_to_fp16(const struct ggml_tensor * tensor, ggml_fp16_t * dst, float clip_limit) {
    const size_t n = rknn_tensor_nelements(tensor);
    if (tensor->type == GGML_TYPE_F16) {
        const ggml_fp16_t * src = (const ggml_fp16_t *) tensor->data;
        for (size_t i = 0; i < n; ++i) {
            dst[i] = GGML_FP32_TO_FP16(rknn_clampf(GGML_FP16_TO_FP32(src[i]), clip_limit));
        }
        return;
    }

    const float * src = (const float *) tensor->data;
    for (size_t i = 0; i < n; ++i) {
        dst[i] = GGML_FP32_TO_FP16(rknn_clampf(src[i], clip_limit));
    }
}

static void rknn_copy_from_float(const float * src, struct ggml_tensor * tensor, float clip_limit) {
    const size_t n = rknn_tensor_nelements(tensor);
    if (tensor->type == GGML_TYPE_F16) {
        ggml_fp16_t * dst = (ggml_fp16_t *) tensor->data;
        for (size_t i = 0; i < n; ++i) {
            dst[i] = GGML_FP32_TO_FP16(rknn_clampf(src[i], clip_limit));
        }
        return;
    }

    float * dst = (float *) tensor->data;
    for (size_t i = 0; i < n; ++i) {
        dst[i] = rknn_clampf(src[i], clip_limit);
    }
}

static bool rknn_runtime_path_exists(const char * path) {
    return path != NULL && path[0] != '\0' && access(path, R_OK) == 0;
}

static const char * rknn_runtime_candidates(void) {
    const char * env = getenv("RKNNRT_PATH");
    if (rknn_runtime_path_exists(env)) {
        return env;
    }
    if (rknn_runtime_path_exists("/home/wubinyi/.local/lib/librknnrt.so")) {
        return "/home/wubinyi/.local/lib/librknnrt.so";
    }
    if (rknn_runtime_path_exists("/usr/local/lib/librknnrt.so")) {
        return "/usr/local/lib/librknnrt.so";
    }
    if (rknn_runtime_path_exists("/usr/lib/librknnrt.so")) {
        return "/usr/lib/librknnrt.so";
    }
    return NULL;
}

static void * rknn_dlsym(void * handle, const char * symbol) {
    dlerror();
    return dlsym(handle, symbol);
}

static bool rknn_load_runtime(struct rknn_runtime_api * runtime) {
    memset(runtime, 0, sizeof(*runtime));

    const char * path = rknn_runtime_candidates();
    if (path == NULL) {
        return false;
    }

    void * handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        return false;
    }

    runtime->handle = handle;
    runtime->path = path;
    runtime->matmul_create = (rknn_matmul_create_fn) rknn_dlsym(handle, "rknn_matmul_create");
    runtime->create_mem = (rknn_create_mem_fn) rknn_dlsym(handle, "rknn_create_mem");
    runtime->set_io_mem = (rknn_matmul_set_io_mem_fn) rknn_dlsym(handle, "rknn_matmul_set_io_mem");
    runtime->b_normal_to_native = (rknn_B_normal_layout_to_native_layout_fn) rknn_dlsym(handle, "rknn_B_normal_layout_to_native_layout");
    runtime->set_core_mask = (rknn_matmul_set_core_mask_fn) rknn_dlsym(handle, "rknn_matmul_set_core_mask");
    runtime->run = (rknn_matmul_run_fn) rknn_dlsym(handle, "rknn_matmul_run");
    runtime->destroy_mem = (rknn_destroy_mem_fn) rknn_dlsym(handle, "rknn_destroy_mem");
    runtime->matmul_destroy = (rknn_matmul_destroy_fn) rknn_dlsym(handle, "rknn_matmul_destroy");
    runtime->mem_sync = (rknn_mem_sync_fn) rknn_dlsym(handle, "rknn_mem_sync");

    if (runtime->matmul_create == NULL || runtime->create_mem == NULL || runtime->set_io_mem == NULL ||
        runtime->b_normal_to_native == NULL || runtime->set_core_mask == NULL || runtime->run == NULL ||
        runtime->destroy_mem == NULL || runtime->matmul_destroy == NULL || runtime->mem_sync == NULL) {
        dlclose(handle);
        memset(runtime, 0, sizeof(*runtime));
        return false;
    }

    return true;
}

static void rknn_runtime_unload(struct rknn_runtime_api * runtime) {
    if (runtime->handle != NULL) {
        dlclose(runtime->handle);
    }
    memset(runtime, 0, sizeof(*runtime));
}

static const char * rknn_reg_get_name(ggml_backend_reg_t reg) {
    (void) reg;
    return "RKNN";
}

static size_t rknn_reg_get_device_count(ggml_backend_reg_t reg) {
    (void) reg;
    return 1;
}

static const char * rknn_device_get_name(ggml_backend_dev_t dev) {
    (void) dev;
    return "RKNN0";
}

static const char * rknn_device_get_description(ggml_backend_dev_t dev) {
    (void) dev;
    return "RKNN backend with decode-style graph execution";
}

static void rknn_device_get_memory(ggml_backend_dev_t dev, size_t * free, size_t * total) {
    (void) dev;
    if (free != NULL) {
        *free = 0;
    }
    if (total != NULL) {
        *total = 0;
    }
}

static enum ggml_backend_dev_type rknn_device_get_type(ggml_backend_dev_t dev) {
    (void) dev;
    return GGML_BACKEND_DEVICE_TYPE_ACCEL;
}

static void rknn_device_get_props(ggml_backend_dev_t dev, struct ggml_backend_dev_props * props) {
    (void) dev;
    if (props == NULL) {
        return;
    }

    props->name = "RKNN0";
    props->description = "RKNN backend with decode-style graph execution";
    props->memory_free = 0;
    props->memory_total = 0;
    props->type = GGML_BACKEND_DEVICE_TYPE_ACCEL;
    props->device_id = "rknn0";
    props->caps.async = false;
    props->caps.host_buffer = false;
    props->caps.buffer_from_host_ptr = false;
    props->caps.events = false;
}

static const char * rknn_backend_probe_summary(void) {
    static char summary[256];
    struct rknn_runtime_api runtime;
    if (rknn_load_runtime(&runtime)) {
        snprintf(summary, sizeof(summary), "RKNN backend: runtime detected at %s", runtime.path);
        rknn_runtime_unload(&runtime);
    } else {
        snprintf(summary, sizeof(summary), "RKNN backend: runtime not detected");
    }
    return summary;
}

static bool rknn_run_decode_matmul(struct rknn_backend_context * backend_ctx, struct ggml_tensor * dst) {
    const struct ggml_tensor * src0 = dst->src[0];
    const struct ggml_tensor * src1 = dst->src[1];

    if (src0 == NULL || src1 == NULL || dst->data == NULL || src0->data == NULL || src1->data == NULL) {
        return false;
    }
    if ((src0->type != GGML_TYPE_F16 && src0->type != GGML_TYPE_F32) ||
        (src1->type != GGML_TYPE_F16 && src1->type != GGML_TYPE_F32) ||
        (dst->type != GGML_TYPE_F16 && dst->type != GGML_TYPE_F32)) {
        return false;
    }

    const struct ggml_tensor * a = src0;
    const struct ggml_tensor * b = src1;
    if (a->ne[1] != 1 && b->ne[1] == 1) {
        a = src1;
        b = src0;
    }

    if (a->ne[1] != 1 || b->ne[0] != a->ne[0]) {
        return false;
    }

    const int64_t m = a->ne[1];
    const int64_t k = a->ne[0];
    const int64_t n = b->ne[1];

    rknn_matmul_info info;
    memset(&info, 0, sizeof(info));
    info.M = (int32_t) m;
    info.K = (int32_t) k;
    info.N = (int32_t) n;
    info.type = RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32;
    info.B_layout = RKNN_MM_LAYOUT_NATIVE;
    info.AC_layout = RKNN_MM_LAYOUT_NORM;
    info.B_quant_type = RKNN_QUANT_TYPE_PER_LAYER_SYM;
    info.AC_quant_type = RKNN_QUANT_TYPE_PER_LAYER_SYM;

    rknn_matmul_io_attr io_attr;
    memset(&io_attr, 0, sizeof(io_attr));

    rknn_matmul_ctx ctx = 0;
    if (backend_ctx->runtime.matmul_create(&ctx, &info, &io_attr) != RKNN_SUCC) {
        return false;
    }

    const size_t a_bytes = (size_t) m * (size_t) k * sizeof(ggml_fp16_t);
    const size_t b_bytes = (size_t) k * (size_t) n * sizeof(ggml_fp16_t);
    const size_t c_bytes = (size_t) m * (size_t) n * sizeof(float);

    rknn_tensor_mem * mem_a = backend_ctx->runtime.create_mem(ctx, (uint32_t) a_bytes);
    rknn_tensor_mem * mem_b = backend_ctx->runtime.create_mem(ctx, (uint32_t) b_bytes);
    rknn_tensor_mem * mem_c = backend_ctx->runtime.create_mem(ctx, (uint32_t) c_bytes);
    if (mem_a == NULL || mem_b == NULL || mem_c == NULL) {
        if (mem_a != NULL) {
            backend_ctx->runtime.destroy_mem(ctx, mem_a);
        }
        if (mem_b != NULL) {
            backend_ctx->runtime.destroy_mem(ctx, mem_b);
        }
        if (mem_c != NULL) {
            backend_ctx->runtime.destroy_mem(ctx, mem_c);
        }
        backend_ctx->runtime.matmul_destroy(ctx);
        return false;
    }

    ggml_fp16_t * a_fp16 = (ggml_fp16_t *) malloc(a_bytes);
    ggml_fp16_t * b_fp16 = (ggml_fp16_t *) malloc(b_bytes);
    ggml_fp16_t * b_native = (ggml_fp16_t *) malloc(b_bytes);
    float * c_fp32 = (float *) malloc(c_bytes);
    if (a_fp16 == NULL || b_fp16 == NULL || b_native == NULL || c_fp32 == NULL) {
        free(a_fp16);
        free(b_fp16);
        free(b_native);
        free(c_fp32);
        backend_ctx->runtime.destroy_mem(ctx, mem_a);
        backend_ctx->runtime.destroy_mem(ctx, mem_b);
        backend_ctx->runtime.destroy_mem(ctx, mem_c);
        backend_ctx->runtime.matmul_destroy(ctx);
        return false;
    }

    rknn_copy_to_fp16(a, a_fp16, backend_ctx->policy.fp16_clip);
    rknn_copy_to_fp16(b, b_fp16, backend_ctx->policy.fp16_clip);
    if (backend_ctx->runtime.b_normal_to_native((void *) b_fp16, (void *) b_native, (int) k, (int) n, &info) != RKNN_SUCC) {
        free(a_fp16);
        free(b_fp16);
        free(b_native);
        free(c_fp32);
        backend_ctx->runtime.destroy_mem(ctx, mem_a);
        backend_ctx->runtime.destroy_mem(ctx, mem_b);
        backend_ctx->runtime.destroy_mem(ctx, mem_c);
        backend_ctx->runtime.matmul_destroy(ctx);
        return false;
    }

    memcpy(mem_a->virt_addr, a_fp16, a_bytes);
    memcpy(mem_b->virt_addr, b_native, b_bytes);
    backend_ctx->runtime.set_io_mem(ctx, mem_a, &io_attr.A);
    backend_ctx->runtime.set_io_mem(ctx, mem_b, &io_attr.B);
    backend_ctx->runtime.set_io_mem(ctx, mem_c, &io_attr.C);
    backend_ctx->runtime.mem_sync((rknn_context) ctx, mem_a, RKNN_MEMORY_SYNC_TO_DEVICE);
    backend_ctx->runtime.mem_sync((rknn_context) ctx, mem_b, RKNN_MEMORY_SYNC_TO_DEVICE);
    (void) backend_ctx->runtime.set_core_mask(ctx, RKNN_NPU_CORE_0_1_2);

    if (backend_ctx->runtime.run(ctx) != RKNN_SUCC) {
        free(a_fp16);
        free(b_fp16);
        free(b_native);
        free(c_fp32);
        backend_ctx->runtime.destroy_mem(ctx, mem_a);
        backend_ctx->runtime.destroy_mem(ctx, mem_b);
        backend_ctx->runtime.destroy_mem(ctx, mem_c);
        backend_ctx->runtime.matmul_destroy(ctx);
        return false;
    }

    backend_ctx->runtime.mem_sync((rknn_context) ctx, mem_c, RKNN_MEMORY_SYNC_FROM_DEVICE);
    memcpy(c_fp32, mem_c->virt_addr, c_bytes);
    rknn_copy_from_float(c_fp32, dst, backend_ctx->policy.act_clip);

    free(a_fp16);
    free(b_fp16);
    free(b_native);
    free(c_fp32);
    backend_ctx->runtime.destroy_mem(ctx, mem_a);
    backend_ctx->runtime.destroy_mem(ctx, mem_b);
    backend_ctx->runtime.destroy_mem(ctx, mem_c);
    backend_ctx->runtime.matmul_destroy(ctx);
    return true;
}

static void rknn_probe_cpu_matmul(const float * a, const float * b, float * out, size_t k, size_t n) {
    for (size_t col = 0; col < n; ++col) {
        float acc = 0.0f;
        for (size_t i = 0; i < k; ++i) {
            acc += a[i] * b[i * n + col];
        }
        out[col] = acc;
    }
}

static void rknn_probe_fill_case_one(float * a, float * b, size_t k, size_t n) {
    for (size_t i = 0; i < k; ++i) {
        a[i] = (float) (i + 1);
    }
    for (size_t i = 0; i < k * n; ++i) {
        b[i] = 1.0f;
    }
}

static void rknn_probe_fill_case_two(float * a, float * b, size_t k, size_t n) {
    for (size_t i = 0; i < k; ++i) {
        a[i] = (float) (((int) (i % 7) - 3) * 0.25f);
    }
    for (size_t row = 0; row < k; ++row) {
        for (size_t col = 0; col < n; ++col) {
            const int pattern = (int) ((row * 3 + col * 5) % 11) - 5;
            b[row * n + col] = (float) pattern * 0.125f;
        }
    }
}

static bool rknn_probe_run_case(
        struct rknn_backend_context * ctx,
        const float * in_a,
        const float * in_b,
        size_t k,
        size_t n,
        float * checksum,
        float * abs_sum,
        float * min_val,
        float * max_val,
        float * max_abs_diff,
        size_t * nonzero_count) {
    float a[32];
    float b[1024];
    float out[32];
    float ref[32];

    if (k != 32 || n != 32) {
        return false;
    }

    memcpy(a, in_a, sizeof(a));
    memcpy(b, in_b, sizeof(b));
    memset(out, 0, sizeof(out));
    memset(ref, 0, sizeof(ref));

    struct ggml_tensor a_tensor = {0};
    struct ggml_tensor b_tensor = {0};
    struct ggml_tensor out_tensor = {0};
    a_tensor.type = GGML_TYPE_F32;
    a_tensor.ne[0] = (int64_t) k;
    a_tensor.ne[1] = 1;
    a_tensor.data = a;
    b_tensor.type = GGML_TYPE_F32;
    b_tensor.ne[0] = (int64_t) k;
    b_tensor.ne[1] = (int64_t) n;
    b_tensor.data = b;
    out_tensor.type = GGML_TYPE_F32;
    out_tensor.ne[0] = (int64_t) n;
    out_tensor.ne[1] = 1;
    out_tensor.data = out;
    out_tensor.src[0] = &a_tensor;
    out_tensor.src[1] = &b_tensor;
    out_tensor.op = GGML_OP_MUL_MAT;

    if (!rknn_run_decode_matmul(ctx, &out_tensor)) {
        return false;
    }

    rknn_probe_cpu_matmul(a, b, ref, k, n);

    float local_checksum = 0.0f;
    float local_abs_sum = 0.0f;
    float local_min = out[0];
    float local_max = out[0];
    float local_max_abs_diff = 0.0f;
    size_t local_nonzero_count = 0;

    for (size_t i = 0; i < n; ++i) {
        const float value = out[i];
        const float diff = fabsf(value - ref[i]);
        if (fabsf(value) > 1e-6f) {
            local_nonzero_count += 1;
        }
        local_checksum += value;
        local_abs_sum += fabsf(value);
        if (value < local_min) {
            local_min = value;
        }
        if (value > local_max) {
            local_max = value;
        }
        if (diff > local_max_abs_diff) {
            local_max_abs_diff = diff;
        }
    }

    *checksum = local_checksum;
    *abs_sum = local_abs_sum;
    *min_val = local_min;
    *max_val = local_max;
    *max_abs_diff = local_max_abs_diff;
    *nonzero_count = local_nonzero_count;
    return true;
}

static const char * rknn_backend_probe_run(void) {
    static char result[768];
    struct rknn_backend_context ctx = {0};
    if (!rknn_load_runtime(&ctx.runtime)) {
        snprintf(result, sizeof(result), "probe_run: runtime unavailable");
        return result;
    }

    ctx.runtime_loaded = true;
    ctx.policy.fp16_clip = 60000.0f;
    ctx.policy.act_clip = 1024.0f;
    ctx.policy.state_clip = 4096.0f;
    ctx.policy.silu_input_clip = 16.0f;
    ctx.policy.attn_qkv_scale = 0.1f;
    ctx.policy.attn_out_scale = 0.25f;
    ctx.policy.ffn_scale = 0.25f;
    ctx.policy.ssm_scale = 0.05f;

    float case1_a[32];
    float case1_b[1024];
    float case2_a[32];
    float case2_b[1024];
    rknn_probe_fill_case_one(case1_a, case1_b, 32, 32);
    rknn_probe_fill_case_two(case2_a, case2_b, 32, 32);

    float case1_checksum = 0.0f;
    float case1_abs_sum = 0.0f;
    float case1_min = 0.0f;
    float case1_max = 0.0f;
    float case1_max_abs_diff = 0.0f;
    size_t case1_nonzero_count = 0;

    float case2_checksum = 0.0f;
    float case2_abs_sum = 0.0f;
    float case2_min = 0.0f;
    float case2_max = 0.0f;
    float case2_max_abs_diff = 0.0f;
    size_t case2_nonzero_count = 0;

    const bool case1_ok = rknn_probe_run_case(
        &ctx,
        case1_a,
        case1_b,
        32,
        32,
        &case1_checksum,
        &case1_abs_sum,
        &case1_min,
        &case1_max,
        &case1_max_abs_diff,
        &case1_nonzero_count);
    const bool case2_ok = rknn_probe_run_case(
        &ctx,
        case2_a,
        case2_b,
        32,
        32,
        &case2_checksum,
        &case2_abs_sum,
        &case2_min,
        &case2_max,
        &case2_max_abs_diff,
        &case2_nonzero_count);

    const float max_abs_diff = case1_max_abs_diff > case2_max_abs_diff ? case1_max_abs_diff : case2_max_abs_diff;
    const bool metrics_finite = isfinite(case1_checksum) && isfinite(case1_abs_sum) && isfinite(case1_min) && isfinite(case1_max) &&
        isfinite(case2_checksum) && isfinite(case2_abs_sum) && isfinite(case2_min) && isfinite(case2_max) &&
        isfinite(case1_max_abs_diff) && isfinite(case2_max_abs_diff);
    const bool has_signal = case1_nonzero_count > 0 || case2_nonzero_count > 0;
    const bool discriminator_ok = case1_ok && case2_ok && metrics_finite && has_signal;

    snprintf(
        result,
        sizeof(result),
        "probe_run: %s case1_checksum=%.6f case1_abs_sum=%.6f case1_min=%.6f case1_max=%.6f "
        "case1_max_abs_diff=%.6f case1_nonzero=%zu "
        "case2_checksum=%.6f case2_abs_sum=%.6f case2_min=%.6f case2_max=%.6f "
        "case2_max_abs_diff=%.6f case2_nonzero=%zu max_abs_diff=%.6f",
        discriminator_ok ? "rk_graph_ok" : "rk_graph_fallback",
        case1_checksum,
        case1_abs_sum,
        case1_min,
        case1_max,
        case1_max_abs_diff,
        case1_nonzero_count,
        case2_checksum,
        case2_abs_sum,
        case2_min,
        case2_max,
        case2_max_abs_diff,
        case2_nonzero_count,
        max_abs_diff);
    rknn_runtime_unload(&ctx.runtime);
    return result;
}

static const char * rknn_backend_get_name(ggml_backend_t backend) {
    (void) backend;
    return "RKNN";
}

static void rknn_backend_free(ggml_backend_t backend) {
    if (backend == NULL) {
        return;
    }

    struct rknn_backend_context * context = (struct rknn_backend_context *) backend->context;
    if (context != NULL) {
        rknn_runtime_unload(&context->runtime);
        free(context);
    }
    free(backend);
}

static enum ggml_status rknn_backend_graph_compute(ggml_backend_t backend, struct ggml_cgraph * cgraph) {
    struct rknn_backend_context * context = (struct rknn_backend_context *) backend->context;
    if (context == NULL || !context->runtime_loaded) {
        return GGML_STATUS_FAILED;
    }

    for (int i = 0; i < cgraph->n_nodes; ++i) {
        struct ggml_tensor * node = cgraph->nodes[i];
        if (node == NULL || node->op == GGML_OP_NONE) {
            continue;
        }

        if (node->op != GGML_OP_MUL_MAT) {
            return GGML_STATUS_FAILED;
        }
        if (!rknn_run_decode_matmul(context, node)) {
            return GGML_STATUS_FAILED;
        }
    }

    return GGML_STATUS_SUCCESS;
}

static const struct ggml_backend_i rknn_backend_i = {
    .get_name = rknn_backend_get_name,
    .free = rknn_backend_free,
    .set_tensor_async = NULL,
    .get_tensor_async = NULL,
    .set_tensor_2d_async = NULL,
    .get_tensor_2d_async = NULL,
    .cpy_tensor_async = NULL,
    .synchronize = NULL,
    .graph_plan_create = NULL,
    .graph_plan_free = NULL,
    .graph_plan_update = NULL,
    .graph_plan_compute = NULL,
    .graph_compute = rknn_backend_graph_compute,
    .event_record = NULL,
    .event_wait = NULL,
    .graph_optimize = NULL,
};

static bool rknn_device_supports_op(ggml_backend_dev_t dev, const struct ggml_tensor * op) {
    (void) dev;
    return op != NULL && op->op == GGML_OP_MUL_MAT;
}

static bool rknn_device_supports_buft(ggml_backend_dev_t dev, ggml_backend_buffer_type_t buft) {
    (void) dev;
    (void) buft;
    return true;
}

static bool rknn_device_offload_op(ggml_backend_dev_t dev, const struct ggml_tensor * op) {
    return rknn_device_supports_op(dev, op);
}

static ggml_backend_t rknn_device_init_backend(ggml_backend_dev_t dev, const char * params) {
    (void) dev;
    (void) params;

    struct rknn_backend_context * context = (struct rknn_backend_context *) calloc(1, sizeof(*context));
    if (context == NULL) {
        return NULL;
    }

    context->policy.fp16_clip = 60000.0f;
    context->policy.act_clip = 1024.0f;
    context->policy.state_clip = 4096.0f;
    context->policy.silu_input_clip = 16.0f;
    context->policy.attn_qkv_scale = 0.1f;
    context->policy.attn_out_scale = 0.25f;
    context->policy.ffn_scale = 0.25f;
    context->policy.ssm_scale = 0.05f;
    context->runtime_loaded = rknn_load_runtime(&context->runtime);

    ggml_backend_t backend = (ggml_backend_t) calloc(1, sizeof(*backend));
    if (backend == NULL) {
        rknn_runtime_unload(&context->runtime);
        free(context);
        return NULL;
    }

    backend->guid = NULL;
    backend->iface = rknn_backend_i;
    backend->device = dev;
    backend->context = context;
    return backend;
}

static ggml_backend_buffer_type_t rknn_device_get_buffer_type(ggml_backend_dev_t dev) {
    (void) dev;
    return NULL;
}

static ggml_backend_buffer_type_t rknn_device_get_host_buffer_type(ggml_backend_dev_t dev) {
    (void) dev;
    return NULL;
}

static ggml_backend_buffer_t rknn_device_buffer_from_host_ptr(
        ggml_backend_dev_t dev,
        void * ptr,
        size_t size,
        size_t max_tensor_size) {
    (void) dev;
    (void) ptr;
    (void) size;
    (void) max_tensor_size;
    return NULL;
}

static ggml_backend_event_t rknn_device_event_new(ggml_backend_dev_t dev) {
    (void) dev;
    return NULL;
}

static void rknn_device_event_free(ggml_backend_dev_t dev, ggml_backend_event_t event) {
    (void) dev;
    (void) event;
}

static void rknn_device_event_synchronize(ggml_backend_dev_t dev, ggml_backend_event_t event) {
    (void) dev;
    (void) event;
}

static const char * rknn_backend_probe_run_impl(void) {
    return rknn_backend_probe_run();
}

static ggml_backend_dev_t rknn_reg_get_device(ggml_backend_reg_t reg, size_t index);

static void * rknn_reg_get_proc_address(ggml_backend_reg_t reg, const char * name) {
    (void) reg;
    if (name == NULL) {
        return NULL;
    }
    if (strcmp(name, "rknn_backend_probe_summary") == 0) {
        return (void *) rknn_backend_probe_summary;
    }
    if (strcmp(name, "rknn_backend_probe_run") == 0) {
        return (void *) rknn_backend_probe_run_impl;
    }
    return NULL;
}

static const struct ggml_backend_device_i rknn_device_i = {
    .get_name = rknn_device_get_name,
    .get_description = rknn_device_get_description,
    .get_memory = rknn_device_get_memory,
    .get_type = rknn_device_get_type,
    .get_props = rknn_device_get_props,
    .init_backend = rknn_device_init_backend,
    .get_buffer_type = rknn_device_get_buffer_type,
    .get_host_buffer_type = rknn_device_get_host_buffer_type,
    .buffer_from_host_ptr = rknn_device_buffer_from_host_ptr,
    .supports_op = rknn_device_supports_op,
    .supports_buft = rknn_device_supports_buft,
    .offload_op = rknn_device_offload_op,
    .event_new = rknn_device_event_new,
    .event_free = rknn_device_event_free,
    .event_synchronize = rknn_device_event_synchronize,
};

static const struct ggml_backend_reg_i rknn_reg_i = {
    .get_name = rknn_reg_get_name,
    .get_device_count = rknn_reg_get_device_count,
    .get_device = rknn_reg_get_device,
    .get_proc_address = rknn_reg_get_proc_address,
};

static ggml_backend_dev_t rknn_reg_get_device(ggml_backend_reg_t reg, size_t index) {
    (void) reg;
    if (index != 0) {
        return NULL;
    }
    return &g_rknn_device;
}

static ggml_backend_reg_t rknn_backend_reg(void) {
    g_rknn_reg.api_version = GGML_BACKEND_API_VERSION;
    g_rknn_reg.iface = rknn_reg_i;
    g_rknn_reg.context = NULL;

    g_rknn_device.iface = rknn_device_i;
    g_rknn_device.reg = &g_rknn_reg;
    g_rknn_device.context = NULL;

    return &g_rknn_reg;
}

static int rknn_backend_score_impl(void) {
    struct rknn_runtime_api runtime;
    if (rknn_load_runtime(&runtime)) {
        rknn_runtime_unload(&runtime);
        return 100;
    }
    return 1;
}

GGML_BACKEND_DL_IMPL(rknn_backend_reg)
GGML_BACKEND_DL_SCORE_IMPL(rknn_backend_score_impl)