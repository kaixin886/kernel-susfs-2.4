# MGLRU 5.4.302 适配记录

## 参考来源

- [Linux MGLRU 管理文档](https://docs.kernel.org/admin-guide/mm/multigen_lru.html)：MGLRU 由 `CONFIG_LRU_GEN` 编译；`CONFIG_LRU_GEN_ENABLED` 控制默认状态；运行时开关为 `/sys/kernel/mm/lru_gen/enabled`。因此本分支选择编译 MGLRU、默认关闭，供设备侧 A/B。
- [Google Android Common `android12-5.4-lts` 内存管理源码](https://android.googlesource.com/kernel/common/+/refs/heads/android12-5.4-lts/mm/)及其 [`mm/Kconfig`](https://android.googlesource.com/kernel/common/+/refs/heads/android12-5.4-lts/mm/Kconfig)：检查时该 5.4 LTS 分支没有 MGLRU 实现或 `CONFIG_LRU_GEN` 条目，不能只改配置启用。
- [Ghostess Android/Qualcomm 5.4.302 参考提交补丁](https://github.com/Ghostess/ghost_kernel_a52s_5g/commit/39289dde38331d6b7feaceb1675fd3de3252f0f3.patch)。参考仓库面向 Snapdragon 778G / SM7325，并说明 MGLRU 是回移植；该实现并不证明已适配 Xiaomi MIX 4 / odin。原补丁 SHA-256：`9b709263f54d895947a297228df104eaf75d26a50d6915d8bc8831889d2d25da`；原改动 53 个文件。

## odin 适配

固定目标源码为 Inkypen `kernel_xiaomi_odin` commit `50e0141b29b62be21632c768e4818348098ac6cd`。参考提交的 Samsung 专属配置、x86 文件、`fs/exec.c` vendor 上下文和依赖设备 helper 的大型 `mm/vmscan.c` hunk 没有原样照搬。最终适配补丁位于 `port/mglru/odin-mglru.patch`：45 个文件、4,450 行新增、222 行删除；在目标 `shrink_node_memcg()` 中只增加 `lru_gen_enabled()` 分流，原有 reclaim 实现保留为后续回退路径。补丁未触及 thermal 驱动、x86 或 odin defconfig。

适配补丁 SHA-256：`8d82d869090dd2f35c984e676398de9e054f5341449a32a68be4ca94dda74f99`。目标源码、参考提交和原始补丁哈希均固定在 [`source-pins.json`](source-pins.json)。

## 已完成的检查

- 对固定 odin 源码文件预检树执行 `git apply --check --whitespace=error --recount`，完整补丁通过；对已经叠加 SUSFS overlay 的完整 5.4.302 源码树再次执行同样检查，也通过。这确认 MGLRU 的 `fs/exec.c` 钩子不会被既有 overlay 覆盖。
- 在独立的完整目标源码 worktree 中应用补丁并运行 `odin_defconfig`/`olddefconfig`：`CONFIG_LRU_GEN=y`，`CONFIG_LRU_GEN_ENABLED` 和 `CONFIG_LRU_GEN_STATS` 均未设置；thermal、CPU thermal、QTI thermal/DCVS 与各 cooling/BCL 配置仍全部为 `y`。
- `scripts/test-odin-mglru.py` 校验补丁哈希、目标 pin、设备适用路径、exec 钩子、MGLRU reclaim 分流、保留的旧 reclaim 调用、运行时文档和 thermal 配置。

## 完整构建验证

- 固定 AOSP Clang 22.0.2 的本地完整 `Image`/AnyKernel 构建成功；本地 SHA256SUMS 检查通过，AnyKernel ZIP 清单与包内 `Image` 校验通过。本地 `Image` 为 37,294,592 bytes，SHA-256：`8f6bfb0ff526f27bc7af66828b8a6c3c4e8d510d5ec500b899c9872800fc8f0d`；ZIP SHA-256：`207a871e2405931aee873a6af26d546505a3a6955d86479b602fec5c928e923b`。
- [GitHub Actions run 44414002675](https://github.com/kaixin886/kernel-susfs-2.4/actions/runs/44414002675) 的补丁、配置、完整构建、ZIP 校验及 artifact 上传步骤均成功；[artifact 14479698893](https://github.com/kaixin886/kernel-susfs-2.4/actions/runs/44414002675/artifacts/14479698893)。云端 `Image` 同为 37,294,592 bytes，SHA-256：`092d6f712b79e8bcabafa0062f6f8eaf9901b1d6e16b3b2d0749b86fa0b49907`；ZIP SHA-256：`1ae403398515f44f4ac8fe3f219a9a38d4f1b3696dfa65f53bc18ec22bba453e`。云端 ZIP 内 `Image` 与该云端独立 `Image` 一致。
- 两次构建的 `kernel.config` SHA-256 相同（`a689bfacfa8441b4af69b68252b7ec6135afcb7be911b82e709f2761e1e528f3`），`source-pins.txt` SHA-256 也相同（`af80c389f8cbc589aae36582aac8e53449a4de5a9e044ca317cd2750430935db`），但 `Image` 字节并不相同。两侧都是 Ubuntu 24.04 系列环境（Actions 镜像版本为 `20261116.376`），且配置启用 `CONFIG_LTO_CLANG=y`；这些环境因素尚不能解释或证明差异原因，现有 artifact 不含中间对象，故不宣称位级可复现。两个构建各自通过，不代表运行时或性能验证。

## 仍待验证

尚未执行 MIX 4 实机启动、内存压力、息屏耗电、游戏帧时间和温控 A/B；因此不声称设备启动安全、功耗/性能收益或 thermal 实测结果。MGLRU 编译接线已启用但运行时默认关闭；先在备份和可恢复条件下完成设备侧验收，再考虑运行时开启。
