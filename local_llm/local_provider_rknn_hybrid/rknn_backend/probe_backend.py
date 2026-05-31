#!/usr/bin/env python3
"""Inspect the loadable RKNN probe backend without needing llama.cpp bindings."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path


class BackendDevCaps(ctypes.Structure):
    _fields_ = [
        ("async_", ctypes.c_bool),
        ("host_buffer", ctypes.c_bool),
        ("buffer_from_host_ptr", ctypes.c_bool),
        ("events", ctypes.c_bool),
    ]


class BackendDevProps(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("description", ctypes.c_char_p),
        ("memory_free", ctypes.c_size_t),
        ("memory_total", ctypes.c_size_t),
        ("type", ctypes.c_int),
        ("device_id", ctypes.c_char_p),
        ("caps", BackendDevCaps),
    ]


BackendRegPtr = ctypes.c_void_p
BackendDevPtr = ctypes.c_void_p


GetName = ctypes.CFUNCTYPE(ctypes.c_char_p, BackendRegPtr)
GetDeviceCount = ctypes.CFUNCTYPE(ctypes.c_size_t, BackendRegPtr)
GetDevice = ctypes.CFUNCTYPE(BackendDevPtr, BackendRegPtr, ctypes.c_size_t)
GetProcAddress = ctypes.CFUNCTYPE(ctypes.c_void_p, BackendRegPtr, ctypes.c_char_p)


class BackendRegI(ctypes.Structure):
    _fields_ = [
        ("get_name", GetName),
        ("get_device_count", GetDeviceCount),
        ("get_device", GetDevice),
        ("get_proc_address", GetProcAddress),
    ]


class BackendReg(ctypes.Structure):
    _fields_ = [
        ("api_version", ctypes.c_int),
        ("iface", BackendRegI),
        ("context", ctypes.c_void_p),
    ]


DevGetName = ctypes.CFUNCTYPE(ctypes.c_char_p, BackendDevPtr)
DevGetDescription = ctypes.CFUNCTYPE(ctypes.c_char_p, BackendDevPtr)
DevGetMemory = ctypes.CFUNCTYPE(None, BackendDevPtr, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
DevGetType = ctypes.CFUNCTYPE(ctypes.c_int, BackendDevPtr)
DevGetProps = ctypes.CFUNCTYPE(None, BackendDevPtr, ctypes.POINTER(BackendDevProps))


class BackendDevI(ctypes.Structure):
    _fields_ = [
        ("get_name", DevGetName),
        ("get_description", DevGetDescription),
        ("get_memory", DevGetMemory),
        ("get_type", DevGetType),
        ("get_props", DevGetProps),
    ]


class BackendDev(ctypes.Structure):
    _fields_ = [
        ("iface", BackendDevI),
        ("reg", BackendRegPtr),
        ("context", ctypes.c_void_p),
    ]


def load_backend(library_path: Path) -> dict[str, object]:
    library = ctypes.CDLL(str(library_path))
    init_fn = library.ggml_backend_init
    init_fn.restype = BackendRegPtr
    score_fn = library.ggml_backend_score
    score_fn.restype = ctypes.c_int

    reg_ptr = init_fn()
    if not reg_ptr:
        raise RuntimeError("ggml_backend_init returned NULL")

    reg = ctypes.cast(reg_ptr, ctypes.POINTER(BackendReg)).contents
    name = reg.iface.get_name(reg_ptr).decode()
    device_count = reg.iface.get_device_count(reg_ptr)
    proc_summary_ptr = reg.iface.get_proc_address(reg_ptr, b"rknn_backend_probe_summary")
    summary = None
    if proc_summary_ptr:
        summary_fn = ctypes.CFUNCTYPE(ctypes.c_char_p)(proc_summary_ptr)
        summary = summary_fn().decode()

    devices: list[dict[str, object]] = []
    for index in range(device_count):
        dev_ptr = reg.iface.get_device(reg_ptr, index)
        if not dev_ptr:
            continue
        dev = ctypes.cast(dev_ptr, ctypes.POINTER(BackendDev)).contents
        props = BackendDevProps()
        dev.iface.get_props(dev_ptr, ctypes.byref(props))
        devices.append(
            {
                "name": dev.iface.get_name(dev_ptr).decode(),
                "description": dev.iface.get_description(dev_ptr).decode(),
                "type": dev.iface.get_type(dev_ptr),
                "memory_free": props.memory_free,
                "memory_total": props.memory_total,
                "device_id": props.device_id.decode() if props.device_id else None,
                "caps": {
                    "async": bool(props.caps.async_),
                    "host_buffer": bool(props.caps.host_buffer),
                    "buffer_from_host_ptr": bool(props.caps.buffer_from_host_ptr),
                    "events": bool(props.caps.events),
                },
            }
        )

    return {
        "library": str(library_path),
        "score": int(score_fn()),
        "api_version": int(reg.api_version),
        "name": name,
        "device_count": int(device_count),
        "summary": summary,
        "devices": devices,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path, help="Path to libggml-rknn-probe.so")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human-readable summary")
    args = parser.parse_args()

    result = load_backend(args.library)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    print(f"library: {result['library']}")
    print(f"score: {result['score']}")
    print(f"api_version: {result['api_version']}")
    print(f"name: {result['name']}")
    print(f"device_count: {result['device_count']}")
    print(f"summary: {result['summary']}")
    for device in result["devices"]:
        print(
            "device: "
            f"{device['name']} | {device['description']} | type={device['type']} | "
            f"memory={device['memory_free']}/{device['memory_total']} | "
            f"device_id={device['device_id']} | caps={device['caps']}"
        )


if __name__ == "__main__":
    main()