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

## 独立优化分支

`tune/sm8350-balanced` 是建立在已验证 2.4 + BakaSU 基线上的更积极、仍可回退的骁龙 888+ 调优实验档：

- CPUFreq 默认从 `performance` 改为 `schedutil`，但仍保留 `performance` governor 供 Android/厂商服务或回退使用。固定 odin 驱动支持 per-policy governor 与 fast switch，且 schedutil 已编译；如果 Android 启动后重设 governor，内核默认值不会覆盖其选择。
- CPUIdle 同时编入 `menu` 和 `TEO`，默认通过 `cpuidle.governor=teo` 选择 TEO；`IDLE_GOVERNOR=menu` 可构建回退档。固定 odin 源码的 TEO Kconfig 说明某些 workload 会受益且通常可安全使用，但这不是 MIX 4 实机省电或延迟提升的证据。原有 `cgroup_disable=pressure` 被保留，内核使用已有 `CONFIG_CMDLINE_EXTEND=y` 追加参数，不启用会替换 bootloader 命令行的 `CMDLINE_FORCE`。若 bootloader 或用户空间另设 governor，以实机 `current_governor` 为准。
- Qualcomm `ARM_QCOM_LPM_CPUIDLE`、WALT、uclamp、cpuset、`HZ=250`、`NO_HZ_IDLE`、RCU callback offload、CPU 频率表/OPP，以及 QTI thermal/DCVS、CPU isolation/hotplug/voltage cooling 和 step-wise 热管理均保留；构建脚本会在 `olddefconfig` 后断言关键项仍启用。没有改温度阈值、最高频率、电压表、触摸 boost、zram/writeback 或厂商 thermal policy。

参考对照：同为 SM8350 的 [OnePlus 9 stock defconfig（固定提交 `9a0c7d6`）](https://github.com/AOSPA/android_kernel_oneplus_sm8350/blob/9a0c7d6add912e2f0935c55bf92d0e8468dac2e3/arch/arm64/configs/oneplus9-stock_defconfig) 也采用 WALT/uclamp、Qualcomm LPM、`performance` 默认与 `menu` idle，并未启用 TEO。MIX 4 保留共同的平台调度/idle/热管理框架；`schedutil + TEO` 是本分支用于实机 A/B 的本地调优假设，不是把 OnePlus 的设备专属频点、boost 或热表搬过来。可核对的本仓固定基线包括 [odin_defconfig](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/arch/arm64/configs/odin_defconfig)、[TEO Kconfig](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/drivers/cpuidle/Kconfig)、[Qualcomm LPM 驱动](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/drivers/cpuidle/lpm-levels-of.c) 与 [Qualcomm CPUFreq 驱动](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/drivers/cpufreq/qcom-cpufreq-hw.c)。

构建默认 TEO 档：`JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh`；若要生成保留原 menu 默认的对照包：`IDLE_GOVERNOR=menu JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh`。两种配置都应在 odin 真机检查实际 policy governor 和 idle governor，再对照待机、短交互、持续 CPU/GPU 负载、温度、热限频、功耗与性能。**尚未实机刷写或测量，不能宣称续航或持续性能已提升，也不能保证设备启动。**

## 构建与验证

运行 `JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh` 可从固定源码执行完整 arm64 `Image` 构建并打 AnyKernel3 包。脚本校验 `port/SHA256SUMS`，在新建的私有临时目录中获取固定内核、BakaSU 和 AnyKernel3；AOSP Clang 从固定 Gitiles commit 分目录拉取，先验 gzip/tar 归档，不完整时拆分目录并按 Git blob ID 校验单文件。编译参数用 `-ffile-prefix-map` / `-fmacro-prefix-map` 规范源和输出路径。产物只原子更新到带专用标记的 `out/`；不会清理或复用旧 `work/`。默认 `INSTALL_DEPS=1` 会安装构建依赖。

固定 pinned 构建已成功，UTS release 为 `5.4.302-inkypen-v2`；工具链锁定 AOSP `android-17.0.0_r1` commit `29182889399818f97baa65ea238c80e8117981eb` 中的 Clang `r596125`（22.0.2）。最终配置的 KSU、SUSFS、AVD 和 Priority UID Filter 均为 `y`，ext4、F2FS、UFS、dm-verity、dm-crypt、Binder 与 SELinux 关键项也启用。与固定内核提交的原始 `odin_defconfig` 对比，5,413 个显式配置项无缺失或未解释差异；差异仅是构建明确启用的项和固定 Clang 版本元数据。

四轮独立干净构建均成功，UTS release 均为 `5.4.302-inkypen-v2`，`Image` 长度均为 37,292,544 字节。但四轮 SHA-256 各不相同；同一配置与源码 pin 下未实现字节级可复现，原因尚未最终确认。构建 4、5、6 使用 `JOBS=8`，构建 7 使用 `JOBS=1`，调低并行度也未消除差异。完整比较和可能原因见 [`port-notes.md`](port-notes.md)。

主线 `60633be` 第七轮基线产物的 Image SHA-256 为 `e0d655edd51f0a319ffe68c3e518243174cc5c5a73ce89bc0cfc81b9d3607c9a`，AnyKernel3 ZIP SHA-256 为 `06145058deabd5317b736f77d16af59292f37e1605b46d0e12c6a36086dd2a80`；这是调优前对照值，不代表本分支构建产物。

调优分支本次固定 pin 的 arm64 构建成功，UTS release 为 `5.4.302-inkypen-v2`。`out/SHA256SUMS` 对 Image、kernel.config、source-pins.txt 和 AnyKernel3 ZIP 的逐项校验均通过；ZIP 完整性、28 项文件清单，以及包内 Image 与独立 Image 的逐字节一致性均通过。最终 Image SHA-256：`c85fa34626fea9f6b7f5ca8d67354786ef23f163ca3eee953b68e839fb4813d1`；AnyKernel3 ZIP SHA-256：`db6e2c6bf41716681f266ae9a61753805d4d2cf7cc98dd7c1b378d86332c827f`。最终配置确认 schedutil 默认、TEO 请求、menu/TEO 均编入、`CMDLINE_EXTEND` 生效且未强制覆盖 bootloader 参数，并保留 Qualcomm LPM、WALT/uclamp、NO_HZ/RCU 与 QTI thermal/DCVS 等断言项。

构建日志有非致命 Kconfig choice override、`thermal_core.c` 的 3 条 `snprintf` fortify warning，以及 MODPOST 对 `embms_tm_multicast_recv` 为 static `EXPORT_SYMBOL` 的警告；没有编译错误。

**设备侧尚未测试。** 构建和打包通过不等于设备可启动；仍需在 odin 设备验证刷写、启动、SELinux 策略加载、布尔值、AVC 行为及重启回归。

逐文件移植、5.4 API 适配和新增钩子的审计记录见 [`port-notes.md`](port-notes.md)。精确 pin 也会随构建写入 `out/source-pins.txt`。
