# MGLRU 5.4.302 适配记录（集成分支）

## 参考来源

- [Linux MGLRU 管理文档](https://docs.kernel.org/admin-guide/mm/multigen_lru.html)：`CONFIG_LRU_GEN` 编译支持，`CONFIG_LRU_GEN_ENABLED` 选择启动默认状态；运行时开关为 `/sys/kernel/mm/lru_gen/enabled`，可写入 `0` 关闭。
- [Google Android Common `android12-5.4-lts` 内存管理源码](https://android.googlesource.com/kernel/common/+/refs/heads/android12-5.4-lts/mm/)及其 [`mm/Kconfig`](https://android.googlesource.com/kernel/common/+/refs/heads/android12-5.4-lts/mm/Kconfig)：该 5.4 LTS 分支没有 MGLRU 实现或 `CONFIG_LRU_GEN` 条目，不能只改配置启用。
- [Ghostess Android/Qualcomm 5.4.302 参考提交补丁](https://github.com/Ghostess/ghost_kernel_a52s_5g/commit/39289dde38331d6b7feaceb1675fd3de3252f0f3.patch)。参考仓库面向 Snapdragon 778G / SM7325，并说明 MGLRU 是回移植；该实现并不证明已适配 Xiaomi MIX 4 / odin。原补丁 SHA-256：`9b709263f54d895947a297228df104eaf75d26a50d6915d8bc8831889d2d25da`；原改动 53 个文件。

## odin 适配与集成默认值

固定目标源码为 Inkypen `kernel_xiaomi_odin` commit `50e0141b29b62be21632c768e4818348098ac6cd`。参考提交的 Samsung 专属配置、x86 文件、`fs/exec.c` vendor 上下文和依赖设备 helper 的大型 `mm/vmscan.c` hunk 没有原样照搬。最终适配补丁位于 `port/mglru/odin-mglru.patch`：45 个文件、4,450 行新增、222 行删除；在目标 `shrink_node_memcg()` 中只增加 `lru_gen_enabled()` 分流，原有 reclaim 实现保留为运行时关闭后的回退路径。补丁未触及 thermal 驱动、x86 或 odin defconfig。

本次集成分支将 `CONFIG_LRU_GEN=y` 与 `CONFIG_LRU_GEN_ENABLED=y` 设为启动默认启用，保留 `/sys/kernel/mm/lru_gen/enabled` runtime kill switch，并将 `CONFIG_LRU_GEN_STATS` 保持关闭。此为新集成分支的显式配置选择；独立 `feature/odin-mglru` 分支的默认关闭设置及既有包不变更。MGLRU 默认启用尚未在 MIX 4 实机做启动、稳定性、功耗或性能测试。

集成分支也将 Kcompressd 的运行时队列深度初值设为 `vm.kcompressd=32`，即每个内存节点最多 32 个排队页；sysctl 仍接受 0–128，写入 `0` 会停止新的异步提交，固定队列容量为每节点 128。该值是保守的非零默认选择，尚未在 MIX 4 实机验证。

适配补丁 SHA-256：`8d82d869090dd2f35c984e676398de9e054f5341449a32a68be4ca94dda74f99`。目标源码、参考提交和原始补丁哈希均固定在 [`source-pins.json`](source-pins.json)。

## 已完成的源码级检查

- 对固定 odin 源码文件预检树执行 `git apply --check --whitespace=error --recount`，完整补丁通过；对已经叠加 SUSFS overlay 的完整 5.4.302 源码树再次执行同样检查，也通过。这确认 MGLRU 的 `fs/exec.c` 钩子不会被既有 overlay 覆盖。
- 集成构建会检查 `CONFIG_LRU_GEN=y`、`CONFIG_LRU_GEN_ENABLED=y`、`CONFIG_LRU_GEN_STATS=n`，以及 thermal、CPU thermal、QTI thermal/DCVS、cooling/BCL 配置仍全部为 `y`。
- `scripts/test-odin-mglru.py` 校验补丁哈希、目标 pin、设备适用路径、exec 钩子、MGLRU reclaim 分流、保留的旧 reclaim 调用、运行时关闭接口和 thermal 配置。`scripts/test-kcompressd-5.4.py` 会断言运行时默认值是每节点 32 页，同时检查 0 值关闭能力和队列边界。集成源码交叉静态测试不是内核编译或设备运行验证。

## 仍待验证

没有在 MIX 4 实机验证默认开启 MGLRU 和默认队列深度 32 的启动稳定性、内存压力、息屏耗电、游戏帧时间、温控 A/B 或运行时 kill switch。完整 arm64 编译和 ZIP/Image 一致性检查将在更新后的集成分支 GitHub Actions 中完成；这仍不替代实机测试。包保留 `UNTESTED` 标记，不宣称省电、性能或热控收益。
