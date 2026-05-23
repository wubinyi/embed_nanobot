# RK3588 (Rock-5T) Llama.cpp Vulkan 部署排查记录

**最终状态**: **已证实 Vulkan 路径不可用。**\
**核心结论**: 在当前 `6.1.115-vendor-rk35xx` 内核环境下，Mali-G610 闭源驱动因缺失标准 ICD 接口及阉割了动态符号表，导致与 `llama.cpp` 的 Vulkan 后端陷入死结（Catch-22）。\
**系统环境**: Armbian (Debian Trixie, aarch64) / 内核版本 `6.1.115-vendor-rk35xx`\
**GPU**: Mali-G610

---

## 阶段一：编译依赖缺失 (已解决)

* **现象**: 在配置 `llama.cpp` 的 CMake 时，报错 `Could NOT find Vulkan (missing: Vulkan_LIBRARY Vulkan_INCLUDE_DIR glslc)`，且后续多线程编译时报错 `spirv/unified1/spirv.hpp: No such file or directory`。
* **原因**: 纯净的 Debian 系统默认未安装 Vulkan 开发头文件、着色器编译器 (glslc) 和 SPIR-V C++ 头文件。
* **🔍 诊断/排查命令**:
  观察 CMake 初始配置阶段的终端报错日志即可。
* **🛠️ 解决方案 / 操作命令**:
  ```bash
  sudo apt update
  # 安装必要的 Vulkan 头文件、着色器编译器以及 SPIR-V C++ 依赖
  sudo apt install libvulkan-dev vulkan-tools glslang-tools glslc spirv-headers
  ```
* **结果**: CMake 成功输出 `-- Vulkan found`，顺利通过配置和编译阶段。


## 阶段二：底层驱动链路断裂 (已解决)

* **现象**: 运行 `vulkaninfo` 显示 `deviceName = llvmpipe (LLVM ...)`。
* **原因**: Debian 默认安装的 `mesa-vulkan-drivers` (开源 Panthor 驱动) 无法在 6.1 版本的 Rockchip 官方闭源 BSP 内核上运行，导致系统退回到 CPU 软渲染。
* **🔍 诊断/排查命令**:
  ```bash
  # 1. 检查当前 Vulkan 识别到的硬件设备 (确认是否掉入 llvmpipe 软渲染陷阱)
  vulkaninfo | grep -i deviceName

  # 2. 检查系统内核版本 (判断应该走开源 Panthor 还是闭源 BSP 路线)
  uname -r

  # 3. 检查物理 GPU 设备节点是否存在及权限
  ls -l /dev/mali0
  ```
* **🛠️ 解决方案 / 操作命令**:
  ```bash
  # 1. 卸载可能存在的开源驱动，防止优先级冲突
  sudo apt purge mesa-vulkan-drivers
  sudo apt autoremove

  # 2. 下载第三方社区打包的闭源驱动 deb 包 (适配 6.1 内核，针对 Headless 优化的 gbm 版本)
  wget [https://github.com/tsukumijima/libmali-rockchip/releases/download/v1.9-1-55611b0/libmali-valhall-g610-g13p0-x11-wayland-gbm_1.9-1_arm64.deb](https://github.com/tsukumijima/libmali-rockchip/releases/download/v1.9-1-55611b0/libmali-valhall-g610-g13p0-x11-wayland-gbm_1.9-1_arm64.deb)

  # 3. 安装 deb 包并修复依赖
  sudo dpkg -i libmali-valhall-g610-g13p0-x11-wayland-gbm_1.9-1_arm64.deb
  sudo apt-get install -f
  ```
* **结果**: 驱动本体和依赖包安装成功，但 `vulkaninfo` 报错 `vkCreateInstance: Found no drivers!`。进入下一阶段排查。


## 阶段三：API 签名冲突与加载器劫持 (已解决)

* **现象**: 安装了 `libmali` deb 包后，Vulkan Loader 报错 `Attempt to retrieve either 'vkGetInstanceProcAddr' or 'vk_icdGetInstanceProcAddr' ... failed`。
* **原因**: 
  1. deb 包内携带的 `libmali` 库（12MB）为了精简体积，被阉割了 Vulkan API（仅剩 GLES/OpenCL）。
  2. 即便换成了 43MB 的全功能版 `libmali.so`，由于瑞芯微采用“单体架构”设计，未导出标准的 Khronos ICD 插件接口，导致高版本的 Debian Vulkan Loader 拒绝加载。
* **🔍 诊断/排查命令**:
  ```bash
  # 1. 开启 Vulkan Loader 的上帝视角调试模式
  VK_LOADER_DEBUG=all vulkaninfo 2>&1 | grep -i mali

  # 2. 检查动态库的具体绝对路径
  dpkg -L libmali-valhall-g610-g13p0-x11-wayland-gbm | grep '\.so'

  # 3. 终极法医鉴定：检查 .so 库中是否包含 Vulkan 符号 (API)
  nm -D /usr/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so | grep -i vkGetInstanceProcAddr
  ```
* **🛠️ 解决方案 / 操作命令 (Dirty Hack)**:
  废弃系统标准的 Vulkan 加载器 (`libvulkan.so.1`)，直接将其软链接强行重定向到满血版的 Mali 驱动，实现底层 API 暴力劫持。
  ```bash
  # 1. 下载 43MB 的全功能版 libmali.so (包含完整的 Vulkan API)
  wget [https://raw.githubusercontent.com/JeffyCN/mirrors/libmali/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so](https://raw.githubusercontent.com/JeffyCN/mirrors/libmali/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so) -O libmali-full.so

  # 2. 狸猫换太子：覆盖 deb 包安装的残缺版库文件
  sudo mv libmali-full.so /usr/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so
  sudo chmod 755 /usr/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so

  # 3. 销毁无效的 Vulkan ICD 配置文件 (断绝 Loader 的正常加载路径)
  sudo rm -f /usr/share/vulkan/icd.d/mali_icd.json

  # 4. 备份系统默认的 Vulkan Loader
  sudo mv /usr/lib/aarch64-linux-gnu/libvulkan.so.1 /usr/lib/aarch64-linux-gnu/libvulkan.so.1.bak

  # 5. 执行暴力劫持：将标准 Vulkan 动态库入口指向全功能版 Mali 驱动
  sudo ln -s /usr/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so /usr/lib/aarch64-linux-gnu/libvulkan.so.1

  # 6. 刷新动态链接器缓存
  sudo ldconfig
  ```
* **结果**: 成功绕过 ICD Loader。`ldd` 检测证实 `llama.cpp` 能够成功找到并挂载硬件驱动层。


## 阶段四：Llama.cpp 动态后端与硬件初始化失败 (已证实不可行)

* **现象**: 现象: 执行启动脚本后，`llama_server.log` 显示 `warning: no usable GPU found`，模型被 100% 加载到 CPU 内存 (`CPU_REPACK`)，`system_info` 中无 `VULKAN = 1` 标志。
* **原因**: 新版 `llama.cpp` 将 Vulkan 编译为独立动态库 `libggml-vulkan.so`。在成功通过环境变量挂载该库后，底层的 `vkCreateInstance` 被 Mali 硬件层拒绝。
* **🔍 诊断/排查命令**:
  ```bash
  # 1. 检查构建目录，确认 Vulkan 是否被编译成了独立的动态插件 (.so)
  ls -l runtime/build/bin/*vulkan*.so

  # 2. 检查主程序是否静态链接了 Vulkan (无输出代表未静态链接)
  nm -C runtime/build/bin/llama-server | grep ggml_backend_vk_init

  # 3. 终极追踪：注入环境变量裸跑，抓取硬件驱动初始化失败日志
  GGML_BACKEND_PATH="/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_llamacpp/runtime/build/bin" \
  GGML_VULKAN_DEBUG=1 \
  /home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_llamacpp/runtime/build/bin/llama-server \
      --model "/home/wubinyi/workspace/embed_nanobot/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf" \
      --threads 4 -ngl 99 --verbose
  ```
* **结果 (最终定论)**: 调试日志抛出 `ERROR_INCOMPATIBLE_DRIVER`。
**内核模块版本与用户态驱动的 `g13p0` ABI 不兼容，且硬件缺少大模型推理所需的原子操作指令。Vulkan 推理通道在当前内核架构下彻底宣告破产。**

## 阶段四(更新)：沙盒对抗与符号表阉割 (彻底定论)
* **现象**: 执行启动脚本时，程序报错 `warning: no usable GPU found`；而在引入私人沙盒目录强制加载后，程序直接崩溃报错 `symbol lookup error: undefined symbol: vkGetInstanceProcAddr`。
* **原因 (死结 / Catch-22)**: 我们在“阶段三”对系统库做的劫持，被系统工具 `sudo ldconfig` 识别并根据 ELF 的 `SONAME` 自动复原了。这迫使我们探索了正反两条路径，均告失败。
* **🔍 诊断/排查命令**:
  ```bash
  # 检查系统动态链接库是否被 ldconfig 篡改还原
  ll /usr/lib/aarch64-linux-gnu/ | grep vulkan

  # 建立私人沙盒 (fake_vulkan)，利用 LD_LIBRARY_PATH 强行隔离系统库干扰
  mkdir -p ~/workspace/embed_nanobot/local_llm/fake_vulkan
  ln -s /usr/lib/aarch64-linux-gnu/libmali-valhall-g610-g13p0-x11-wayland-gbm.so ~/workspace/embed_nanobot/local_llm/fake_vulkan/libvulkan.so.1

  # 终极测试：强制只加载假目录里的驱动
  LD_LIBRARY_PATH="/home/wubinyi/workspace/embed_nanobot/local_llm/fake_vulkan:$LD_LIBRARY_PATH" \
  GGML_BACKEND_PATH=".../runtime/build/bin" \
  ./llama-server --model ... -ngl 99
  ```
* **结果 (双线失败证明)**: 
  * **路线 A (走正门，受制于 Loader)**：当 `ldconfig` 自动还原了系统的 `libvulkan.so.1` 后，`llama-server` 启动加载了官方 Loader。但 Loader 判定 Mali 驱动不符合 ICD 规范拒绝加载，程序静默回退至纯 CPU，抛出 `no usable GPU found`。
  * **路线 B (走后门，受制于符号表)**：通过 `LD_LIBRARY_PATH` 局部沙盒技术完美绕过系统 Loader，强制加载 43MB 的满血 Mali 驱动。但由于瑞芯微在编译时 `strip` 了动态导出符号表，未暴露 `vkGetInstanceProcAddr` 函数入口。Linux 动态链接器 (`ld.so`) 在拉起 `libggml-vulkan.so` 插件时无法找到该符号，引发核心转储报错 `symbol lookup error`。

**最终判决**：无论如何规避加载器限制，闭源驱动缺失动态导出符号这一物理障碍无法逾越，Vulkan 路线宣告失败。

## 🛠️ 后续执行方案与建议
鉴于 Vulkan 通道不可用，建议立即执行以下步骤止损：
1. **清理战场 (恢复系统标准状态):**
    ```bash
    # 恢复系统原始 Vulkan Loader 并刷新
    sudo mv /usr/lib/aarch64-linux-gnu/libvulkan.so.1.bak /usr/lib/aarch64-linux-gnu/libvulkan.so.1
    sudo ldconfig

    # 删除为局部沙盒劫持创建的假目录
    rm -rf ~/workspace/embed_nanobot/local_llm/fake_vulkan

    # 建议卸载非标准 libmali deb 包
    sudo apt purge libmali-valhall-g610-g13p0-x11-wayland-gbm
    ```

2. **核心战略转移 (NPU 部署)**: 全面停止在 RK3588 上的 GPU/Vulkan 尝试。这块芯片的真正价值在于 6 TOPS 算力的 NPU。重点应转向基于 Rockchip 官方 `RKLLM` 框架的开发，或寻找针对 RK3588 的 NPU 社区分支，打通 RKNPU2 推理栈。
