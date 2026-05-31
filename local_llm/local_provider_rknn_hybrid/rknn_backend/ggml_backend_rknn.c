#include "ggml-backend-impl.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char * rknn_backend_probe_summary(void);

static const char * rknn_reg_get_name(ggml_backend_reg_t reg) {
    (void) reg;
    return "RKNN-PROBE";
}

static size_t rknn_reg_get_device_count(ggml_backend_reg_t reg) {
    (void) reg;
    return 1;
}

static const char * rknn_device_get_name(ggml_backend_dev_t dev) {
    (void) dev;
    return "RKNN-PROBE0";
}

static const char * rknn_device_get_description(ggml_backend_dev_t dev) {
    (void) dev;
    return "RKNN backend probe device (loadable registry only)";
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

    props->name = "RKNN-PROBE0";
    props->description = "RKNN backend probe device (loadable registry only)";
    props->memory_free = 0;
    props->memory_total = 0;
    props->type = GGML_BACKEND_DEVICE_TYPE_ACCEL;
    props->device_id = "probe0";
    props->caps.async = false;
    props->caps.host_buffer = false;
    props->caps.buffer_from_host_ptr = false;
    props->caps.events = false;
}

static ggml_backend_t rknn_device_init_backend(ggml_backend_dev_t dev, const char * params) {
    (void) dev;
    (void) params;
    return NULL;
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

static bool rknn_device_supports_op(ggml_backend_dev_t dev, const struct ggml_tensor * op) {
    (void) dev;
    (void) op;
    return false;
}

static bool rknn_device_supports_buft(ggml_backend_dev_t dev, ggml_backend_buffer_type_t buft) {
    (void) dev;
    (void) buft;
    return false;
}

static bool rknn_device_offload_op(ggml_backend_dev_t dev, const struct ggml_tensor * op) {
    (void) dev;
    (void) op;
    return false;
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

static ggml_backend_dev_t rknn_reg_get_device(ggml_backend_reg_t reg, size_t index);

static void * rknn_reg_get_proc_address(ggml_backend_reg_t reg, const char * name) {
    (void) reg;

    if (name != NULL && strcmp(name, "rknn_backend_probe_summary") == 0) {
        return (void *) rknn_backend_probe_summary;
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

static struct ggml_backend_reg g_rknn_reg;
static struct ggml_backend_device g_rknn_device = {
    .iface = rknn_device_i,
    .reg = &g_rknn_reg,
    .context = NULL,
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

static bool rknn_runtime_available(void) {
    const char * candidates[] = {
        getenv("RKNNRT_PATH"),
        "/usr/lib/librknnrt.so",
        "/usr/local/lib/librknnrt.so",
        "/home/wubinyi/.local/lib/librknnrt.so",
    };

    size_t i;
    for (i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
        const char * candidate = candidates[i];

        if (candidate == NULL || candidate[0] == '\0') {
            continue;
        }

        if (access(candidate, R_OK) == 0) {
            return true;
        }
    }

    return false;
}

static int rknn_backend_score_impl(void) {
    return rknn_runtime_available() ? 100 : 1;
}

static ggml_backend_reg_t rknn_backend_reg(void) {
    g_rknn_reg.api_version = GGML_BACKEND_API_VERSION;
    g_rknn_reg.iface = rknn_reg_i;
    g_rknn_reg.context = NULL;

    return &g_rknn_reg;
}

static const char * rknn_backend_probe_summary(void) {
    return rknn_runtime_available() ? "RKNN probe backend: runtime detected" : "RKNN probe backend: runtime not detected";
}

GGML_BACKEND_DL_IMPL(rknn_backend_reg)
GGML_BACKEND_DL_SCORE_IMPL(rknn_backend_score_impl)