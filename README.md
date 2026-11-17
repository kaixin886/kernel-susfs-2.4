# SUSFS v2.4.0 for Xiaomi MIX 4 (odin)

将 SUSFS v2.4.0 移植到 Inkypen Linux 5.4 内核，并集成用户指定的 BakaSU `sync-up` 修复版。此仓库是 `kaixin886/kernel-susfs-2.4` 的独立 2.4 工作线；不修改 2.3 主线。

## 固定来源

| 组件 | 来源与固定提交 |
|---|---|
| 内核基线 | [Inkypen `kernel_xiaomi_odin`](https://github.com/Inkypen79/kernel_xiaomi_odin/commit/50e0141b29b62be21632c768e4818348098ac6cd)，`50e0141b29b62be21632c768e4818348098ac6cd` |
| SUSFS v2.4 基础 | [GitLab `simonpunk/susfs4ksu`](https://gitlab.com/simonpunk/susfs4ksu)，`gki-android12-5.10` 分支基础提交 `6dff25f2b2508f91df309e537771d612dccd201a` |
| SUSFS 最新上游参考 | [当前分支提交](https://gitlab.com/simonpunk/susfs4ksu/-/commit/784ac9e6fd49bb02499b5b60c57ccc9d0c680204)，`784ac9e6fd49bb02499b5b60c57ccc9d0c680204`；这是分支 HEAD，不是版本号更新提交 |
| SUSFS v2.4.0 版本标记 | [提交 `45a0575`](https://gitlab.com/simonpunk/susfs4ksu/-/commit/45a057536ddba12fd59fb583a8f5375f83be703e) |
| BakaSU | [用户指定的 `sync-up`](https://github.com/Baka-SU/BakaSU/commit/55f3dcb11a0ce5b8aad3cb9763b200fe52efe218)，`55f3dcb11a0ce5b8aad3cb9763b200fe52efe218` |
| AnyKernel3 | [固定提交](https://github.com/osm0sis/AnyKernel3/commit/41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1)，`41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1` |

SUSFS 的 `kernel-5.4` 上游分支落后于 v2.4，因此以 5.10 分支作为功能参考，并按本内核的 5.4 API 手工适配。最新上游增量加入 SELinux `setxattr` / `post_setxattr` 包装和 SID 转换接口：仅在 `CONFIG_KSU_SUSFS` 下注册；当前 UID ≥ 10000 且 SELinux hide 正在运行时走 SUSFS-aware 路径，其余情况保留原始 SELinux handler。实现沿用 5.4 的 `state->ss`、`policy_rwlock`、`policydb` 与 `sidtab` 布局。

BakaSU 固定在用户指定的 `sync-up` 提交，不切换到 `main`。该版本已有 `KSU_SUSFS_PRIORITY_UID_FILTER`，构建 helper 只添加缺少的 `KSU_SUSFS_AVD`，并验证两项均唯一且配置有效。其 `KSU_COMPAT_HAS_SUSFS_FEATURE_SELINUX_HIDE` 兼容宏用于避免 BakaSU 与内核侧 hook 重复实现。

## 构建与验证

运行 `JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh` 可从固定源码执行完整 arm64 `Image` 构建并打 AnyKernel3 包。脚本校验 `port/SHA256SUMS`，在新建的私有临时目录中获取固定内核、BakaSU 和 AnyKernel3；AOSP Clang 从固定 Gitiles commit 分目录拉取，先验 gzip/tar 归档，不完整时拆分目录并按 Git blob ID 校验单文件。编译参数用 `-ffile-prefix-map` / `-fmacro-prefix-map` 规范源和输出路径。产物只原子更新到带专用标记的 `out/`；不会清理或复用旧 `work/`。默认 `INSTALL_DEPS=1` 会安装构建依赖。

固定 pinned 构建已成功，UTS release 为 `5.4.302-inkypen-v2`；工具链锁定 AOSP `android-17.0.0_r1` commit `29182889399818f97baa65ea238c80e8117981eb` 中的 Clang `r596125`（22.0.2）。最终配置的 KSU、SUSFS、AVD 和 Priority UID Filter 均为 `y`，ext4、F2FS、UFS、dm-verity、dm-crypt、Binder 与 SELinux 关键项也启用。与固定内核提交的原始 `odin_defconfig` 对比，5,413 个显式配置项无缺失或未解释差异；差异仅是构建明确启用的项和固定 Clang 版本元数据。

四轮独立干净构建均成功，UTS release 均为 `5.4.302-inkypen-v2`，`Image` 长度均为 37,292,544 字节。但四轮 SHA-256 各不相同；同一配置与源码 pin 下未实现字节级可复现，原因尚未最终确认。构建 4、5、6 使用 `JOBS=8`，构建 7 使用 `JOBS=1`，调低并行度也未消除差异。完整比较和可能原因见 [`port-notes.md`](port-notes.md)。

当前 `out/` 是第七轮产物：Image SHA-256 为 `e0d655edd51f0a319ffe68c3e518243174cc5c5a73ce89bc0cfc81b9d3607c9a`，AnyKernel3 ZIP SHA-256 为 `06145058deabd5317b736f77d16af59292f37e1605b46d0e12c6a36086dd2a80`。四轮的 `kernel.config` 与 `source-pins.txt` 哈希分别稳定为 `06b306be6c3d101dac7a9f469e89ee364144e8a57b616aef3d4dd9b1ce13bf6b` 和 `3d1be33024613b33e9c53fcb4eb109d0863dc0888c08a1eb737ab6e7f0fb8b5a`。本轮清单校验、ZIP 解压测试、28 项文件集以及包内 Image 与独立 Image 逐字节比较均通过。

构建日志有非致命 Kconfig choice override、`thermal_core.c` 的 3 条 `snprintf` fortify warning，以及 MODPOST 对 `embms_tm_multicast_recv` 为 static `EXPORT_SYMBOL` 的警告；没有编译错误。

**设备侧尚未测试。** 构建和打包通过不等于设备可启动；仍需在 odin 设备验证刷写、启动、SELinux 策略加载、布尔值、AVC 行为及重启回归。

逐文件移植、5.4 API 适配和新增钩子的审计记录见 [`port-notes.md`](port-notes.md)。精确 pin 也会随构建写入 `out/source-pins.txt`。
