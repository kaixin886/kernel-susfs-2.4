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

## 仍待验证

尚未完成固定 AOSP Clang 下的完整 `Image`/AnyKernel 构建，也未执行 GitHub 云构建或 MIX 4 实机启动、内存压力、息屏耗电、游戏帧时间和温控 A/B。补丁应用和 Kconfig 通过不代表编译、启动安全或实机收益；应保持默认关闭，待完整编译与设备侧验证后再考虑开启。
