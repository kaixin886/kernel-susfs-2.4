# Xiaomi MIX 4（odin）5.4.302 集成内核：LZ4K + Kcompressd + MGLRU

**状态：UNTESTED。** 这是面向 Xiaomi MIX 4 / Snapdragon 888 的集成构建候选。没有 MIX 4 实机启动验证，也没有 A/B/A 功耗、性能、游戏帧时间或温度测量；CI 成功和 ZIP 校验都不等于设备验证。

## 来源与合并内容

新建分支 `integration/odin-memory-stack`，从 `feature/odin-mglru` 的 `085a042c3829bd9711b30d17bfbf6690a891c17a` 开始。MGLRU 分支已继承日常功耗提交 `5b26ce9e4595fe9de5a7e90223581ac3bab3694c` 和 SUSFS 2.4 SID 修复 `dc93390b87acbee7010ca4e9460d40ea5f1c0141`；本分支再合入 LZ4K `c83d41137769baa484f6037f761088e551fb1652` 与 Kcompressd `40c484351d6a7e7e86e9e7b440c09a5309371cc9`。三个原功能分支、SID-fix 分支和已验证包均保持不变。

固定源码为 Inkypen `kernel_xiaomi_odin` 提交 `50e0141b29b62be21632c768e4818348098ac6cd`（Linux 5.4.302）。SUSFS v2.4.0 文件移植及 SHA-256 清单在 `port/`；BakaSU 固定 `sync-up` 提交 `55f3dcb11a0ce5b8aad3cb9763b200fe52efe218`，并单独叠加兼容的 Manager WebView #35262 修复 `7b65bde0710b5e7c6f755545cb15a4abd417f3a8`。ROM 标签按设备所有者提供的 LineageOS 24.0 GApps / Android 17 记录。

## 三项功能及默认状态

- **LZ4K zram：可选，但不是默认压缩器。** 固定 openEuler kernel PR #1277 codec，并为 Linux 5.4 适配 `CRYPTO_ACOMP2` 与 zcomp backend。构建启用 `CONFIG_CRYPTO_LZ4K=y`，但会比较集成前后的 `CONFIG_ZRAM*` 配置并要求完全一致；不改默认算法、不加运行时切换或启动参数。
- **Kcompressd：运行时默认启用。** 编译启用 `CONFIG_KCOMPRESSD=y`，`vm.kcompressd` 初始值为 **32**，表示每个内存节点最多排队 32 个待处理页；范围为 0–128，写入 `0` 可停止新任务提交，写入非零值可重新启用/调整。每节点队列有独立上限 128。默认队列深度是为此 5.4 适配选择的保守非零值，不是实机性能结论；静态测试覆盖队列、页锁/写回屏障、异步 BIO、swapoff 与启停顺序。尚未做压力或 zswap runtime 测试。
- **MGLRU：启动时默认启用，可在运行时关闭。** `CONFIG_LRU_GEN=y`、`CONFIG_LRU_GEN_ENABLED=y`，`CONFIG_LRU_GEN_STATS=n`。运行时 kill switch 为 `/sys/kernel/mm/lru_gen/enabled`；写入 `0` 可关闭，写入 `y` 可重新启用。默认开启仅适用于此集成分支，与独立 MGLRU 分支原先默认关闭的配置不同；独立分支不变更。适配参考与 pin 记录见 `port/mglru/`。
- **继承的日常调速：** schedutil 保留原升频延迟，初始化降频延迟为 0。Android/Scene/Power HAL 仍可能改写运行时 tunables；没有安装轮询或自动切换服务。
- **SUSFS SID 修复：** SUSFS 过滤后的 context 继续经 Linux 5.4 `context_struct_to_sid()` 做 hash-aware 转换；未修改 enforcing、SELinux policy 或 BakaSU hide 行为。

SUSFS 2.3 仍单独保存在 `kaixin886/odin-kernel-susfs`，不在此次修改范围内。

## 热控与测试边界

构建脚本会断言 `CONFIG_THERMAL`、CPU thermal、QTI thermal/DCVS、CPU isolate/hotplug/voltage cooling 和 BCL 保护仍启用；MGLRU 回归测试拒绝补丁触及 device thermal driver。没有移植其他机型的 OPP、电压、GPU、IRQ 或温控数值。静态配置断言不能证明实机 thermal throttling 或温度行为。

构建脚本组合运行 schedutil、LZ4K、Kcompressd、MGLRU 与 SUSFS/SID 回归；还检查 zram 默认配置、MGLRU 启动默认启用及运行时 kill switch、Kcompressd 默认 32 页/节点及零值关闭、热控选项、固定源码和补丁哈希。CI 完整编译 arm64 `Image` 并生成 AnyKernel3 ZIP；校验包内 `Image` 与单独构建的 `Image` 逐字节一致，并检查 ZIP 文件清单/哈希。完整实机测试仍须验证冷启动、重启、Termux、网络、相机/音频、休眠唤醒、zram 算法选择、swapoff/内存压力、Kcompressd 与 MGLRU 的开关及压力行为、温控限频和游戏帧时间，并做可回滚的 A/B/A。未完成前不宣称省电或性能收益，包名保留 `UNTESTED`。
