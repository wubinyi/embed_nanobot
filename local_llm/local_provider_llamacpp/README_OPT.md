RK3588使用llama.cpp部署模型的性能提升点如下：
1. `--mlock` (Memory Lock): 强烈建议开启。这会强制将整个模型锁定在物理内存（RAM）中，禁止操作系统将其放入虚拟内存（Swap/Pagefile）交换到硬盘上。开启后，可以避免推理过程中的突然卡顿。可能会出现warning，`warning: failed to mlock 576376832-byte buffer (after previously locking 0 bytes): Cannot allocate memory`,解决方法：
    - 单词临时生效`ulimit -l unlimited`。命令运行失败，`sudo: ulimit: command not found: ulimit` 并不是一个独立的系统程序（像 `ls` 或 `cd` 那样放在 `/bin` 目录下），它是 Bash 的内置命令（Built-in command）。 `sudo` 只能调用外部的可执行文件，无法直接执行 Shell 的内置命令。
    - 永久生效
        - 编辑 limits 配置文件：
            ```Bash
            sudo nano /etc/security/limits.conf
            ```
        - 在文件末尾添加以下两行（星号代表对所有用户生效）：
            ```Bash
            * soft memlock unlimited
            * hard memlock unlimited
            或
            wubinyi soft memlock unlimited
            wubinyi hard memlock unlimited
            ```
        - 保存退出后，彻底注销并重新登录（或重启系统），设置即可生效。
        - 重新登录后，再次运行 `ulimit -l`，如果输出是 `unlimited`，说明配置成功，你就可以正常带 `--mlock` 参数启动 `llama-server` 了。
2. `--no-mmap` (视情况而定): 默认情况下 `llama.cpp` 使用 mmap 来加载模型。如果你的内存非常充足，使用 `--mlock` 就足够了。但在某些特定的老旧系统或受限环境中，禁用 mmap 完全读入内存有时会更稳定。
3. `-fa` (Flash Attention): 尝试开启。虽然它在 GPU 上带来的提升更显著，但在 CPU 上也可以优化长上下文（Context）的处理效率并略微减少内存占用。
4. 电源模式调整 (Linux): 将 CPU 调速器设置为性能模式，防止推理期间 CPU 降频。
    ```Bash
    # 将所有 CPU 核心设置为 performance 模式
    sudo cpupower frequency-set -g performance
    ``` 
5. RK3588 是“大小核”架构（big.LITTLE）。如果你不设置，操作系统会把任务分配给所有 8 个核心。灾难后果： 4 个羸弱的 A55 小核会严重拖慢 4 个 A76 大核的同步速度，导致整体推理速度比只用 4 个大核还要慢 30% 以上！查看大小核
    ```Bash
    # 查看所有核心的最高频率（最简单直观），最上面对应`core 0`频率
    cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq
    # 查看 CPU 集群策略 (Cluster Topology)
    cat /sys/devices/system/cpu/cpufreq/policy*/related_cpus
    # 使用 lscpu 综合查看
    lscpu
    ```
    llama-server 启动命令
    ```Bash
    taskset -c 4-7 ./llama-server \
        -m /path/to/your/model-Q4_K_M.gguf \
        --host 0.0.0.0 \
        --port 8080 \
        -c 2048 \
        -t 4 \
        -ngl 99
    ```
    - `taskset -c 4-7`: 【系统级】把进程死死按在 4 个 A76 高性能大核上，不准去小核。
    - `--host 0.0.0.0`: 允许局域网内其他设备（比如你的电脑/手机）通过 API 访问这块板子。
    - `-c 2048`: 限制上下文长度为 2K，保护有限的运行内存。
    - `-t 4`: 告诉 llama.cpp 只启动 4 个物理线程（完美对应 4 个大核）。
    - `-ngl 99`: (极其重要) 将所有支持的模型层（Layers）卸载到 Mali GPU 上运行（前提是你按上面的方法开启了 Vulkan 编译）。99 表示尽可能多地卸载。
6. 编译终极杀器：开启 Vulkan (GPU 加速)。官方默认编译是纯 CPU 的。但 RK3588 的 Mali-G610 GPU 性能尚可，并且 llama.cpp 原生支持通过 Vulkan 后端调用 ARM GPU。这通常能让你的推理速度翻倍。启用`Vulkan`支持进行编译，安装依赖包
	```Bash
    sudo apt update
    sudo apt install libvulkan-dev vulkan-tools glslang-tools glslc
	``` 
    重新编译
    ```Bash
    mkdir build
    cd build
    # 启用 Vulkan 支持进行编译
    cmake .. -DGGML_VULKAN=1
    cmake --build . --config Release -j 4
    ```
    - 安装 Vulkan 开发依赖
    ```Bash
    sudo apt update
    sudo apt install libvulkan-dev vulkan-tools glslang-tools glslc
    # 注：如果你在安装 glslc 时遇到包找不到的错误，在某些 ARM64 软件源中它可能包含在 shaderc 包内，你可以替换为 
    # sudo apt install libvulkan-dev vulkan-tools glslang-tools shaderc。
    ```
    - 清理并重新编译
    ```Bash
    # CMake 有极强的缓存机制。既然之前失败了，你必须清理旧的缓存，否则它哪怕有了依赖也会继续报错。彻底删除旧的构建目录。
    rm -rf build

    # 重新创建并配置 CMake
    mkdir build && cd build
    cmake .. -DGGML_VULKAN=1

    # 开始多线程编译
    cmake --build . --config Release -j 4
    ```
    - Vulkan 诊断：解决编译报错只是第一关，在 RK3588 上跑 Vulkan，最致命的坑在“运行时 (Runtime)”。当你编译成功，满心欢喜地带上 `-ngl 99` 启动 `llama-server` 时，如果速度慢得像幻灯片，那是由于系统没有正确调用 Mali-G610 硬件，而是回退到了 llvmpipe (CPU 软件模拟渲染)。运行刚刚安装的 Vulkan 诊断工具：
    ```Bash
    vulkaninfo | grep -i deviceName
    ```
    正确的结果：你应该能看到类似 deviceName = Mali-G610 或者 deviceName = Panfrost 的字样。这说明 Vulkan 驱动正确挂载了 GPU。