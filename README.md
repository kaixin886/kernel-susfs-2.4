# SUSFS v2.4.0 + SM8350 动态省电实验（Xiaomi MIX 4 / odin）

本工作线面向 Xiaomi MIX 4（`odin`，Snapdragon 888，Linux 5.4.302）。`tune/sm8350-aggressive` 是从 `tune/sm8350-balanced` 独立切出的实验分支；不改 `main`、平衡分支或 SUSFS 2.3。优化目标按优先级排列：息屏/待机少耗电，负载出现时保留调度器和 Android 电源管理的动态响应，游戏负载下尽量平稳。**这些效果必须在 MIX 4 实机 A/B 测量后才能判断，本仓目前没有实机结果。**

## 固定源码与 BakaSU #35262

| 组件 | 来源 / 固定提交 |
|---|---|
| odin 内核 | [Inkypen `kernel_xiaomi_odin`](https://github.com/Inkypen79/kernel_xiaomi_odin/commit/50e0141b29b62be21632c768e4818348098ac6cd)，`50e0141b29b62be21632c768e4818348098ac6cd` |
| SUSFS v2.4 | [GitLab `simonpunk/susfs4ksu`](https://gitlab.com/simonpunk/susfs4ksu)：`gki-android12-5.10` 基础 `6dff25f2b2508f91df309e537771d612dccd201a`；参考 HEAD `784ac9e6fd49bb02499b5b60c57ccc9d0c680204`；v2.4.0 标记 `45a057536ddba12fd59fb583a8f5375f83be703e` |
| BakaSU `sync-up` | [固定提交 `55f3dcb`](https://github.com/Baka-SU/BakaSU/commit/55f3dcb11a0ce5b8aad3cb9763b200fe52efe218)，完整 SHA `55f3dcb11a0ce5b8aad3cb9763b200fe52efe218` |
| BakaSU Manager WebView #35262 | [独立修复 `7b65bde`](https://github.com/Baka-SU/BakaSU/commit/7b65bde0710b5e7c6f755545cb15a4abd417f3a8)，完整 SHA `7b65bde0710b5e7c6f755545cb15a4abd417f3a8` |
| AnyKernel3 | [固定提交](https://github.com/osm0sis/AnyKernel3/commit/41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1)，`41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1` |
| AOSP Clang | `android-17.0.0_r1`，commit `29182889399818f97baa65ea238c80e8117981eb`，Clang 22.0.2 / r596125 |

构建集成前和完成后分别复查远端，BakaSU `sync-up` 最新 HEAD 均为 `55f3dcb…`；该提交不包含 #35262。`7b65bde…` 可干净地单独叠加，只修改 `manager/app/src/main/java/org/bakasu/bakasu/ui/webui/WebViewInterface.kt`，补上主线程派送与 WebView 空值保护。按实际应用到 pinned `sync-up` 的 binary diff 计算，补丁 SHA-256 为 `cff8e5ee87b477ec30bc93fffadb739835987b62cff4a92595c914a3c746520c`。内核 `selinux_hide` 保持原样，`sync-up` 的 Manager API 修改也保留。该补丁是 Manager 源码修复，不是内核改动；AnyKernel ZIP 不含 Manager APK，不会更新 Manager。

## 当前 SELinux 修复分支

`fix/susfs24-selinux-context-sid` 从已核实的 `tune/sm8350-aggressive` tip `f571ef08ea82f0bf41ed42eadc3edb7296cf6ed2` 单独创建。本分支只修复 SUSFS 2.4 的 SELinux context-to-SID 路径，保留该基线已有的功耗/调度配置，不改任何其他分支，也不新增 Scene 抢写的调度参数。

5.4.302 的原生 `context_struct_to_sid()` 会在 `sidtab_context_to_sid()` 前调用 `context_add_hash()`；`sidtab` 用 `context->hash` 查找和去重。SUSFS 2.4 自己的 core 路径跳过原生 helper，直接调用 SID 表。本修复让 SUSFS 在解析/过滤完 context 后复用原生 hash-aware helper。BakaSU `sync-up` 的 #623 主/backup sidtab 修复和 `KSU_COMPAT_HAS_CONTEXT_ADD_HASH` 检测保持不变；不关闭隐藏、不改 enforcing、不放宽 SELinux policy。

目标 ROM 标签按设备所有者确认的 Inkypen LineageOS 24.0 GApps / Android 17 标记。包名会明确标注 `UNTESTED`：静态检查和编译不能替代设备冷启动 Termux A/B；不刷机，也不宣称已实机验证。

## 动态省电的策略边界

本分支不把 CPU 固定在高频，也不硬编码某款游戏的频率/核心亲和性。策略由内核调度器、设备 ROM 的 Power HAL 和 SoC 热管理分层完成：

- **CPU 负载变化：** 固定 odin 源码提供 schedutil，并启用 WALT 和 task/group uclamp；本项目沿用平衡分支的 schedutil 默认值，让调频跟随运行负载。Android 的顶层任务/性能提示可通过设备 Power HAL 影响实际策略。
- **空闲/息屏：** 保留 Qualcomm LPM、TEO、NO_HZ/RCU 和 QTI thermal/DCVS。AOSP Power HAL 的 `setInteractive(false)` 是进入非交互（通常是息屏）时调整 CPUfreq 参数、允许系统低功耗 suspend 的入口；本仓只有内核，没有目标 ROM 的 Power HAL 源码，故不伪造屏幕状态检测器。
- **游戏/高负载：** Android Performance Hint / ADPF 允许游戏向系统报告工作时长和目标帧期限，再由设备按本机拓扑与热设计调资源；[AOSP 文档](https://source.android.com/docs/core/perf/performance-hint-api)明确不应把核心亲和性写死。[Power HAL 接口](https://android.googlesource.com/platform/hardware/interfaces/+/fd877b5479b1639b4ba57af5c1f78a7a463e6be1/power/1.0/IPower.hal)中的 `powerHint()` 也由平台决定如何处理。
- **触控瞬时响应：** odin WALT 有事件驱动的 [cpu-boost](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/kernel/sched/walt/cpu-boost.c)：收到输入事件后短时增加 CPU 频率下限/可选 scheduler boost，然后自动撤销；源码中的输入 boost 时长默认 40 ms，但各 CPU 的 `input_boost_freq` 和 `sched_boost_on_input` 默认都为 0，因此是否启用由 ROM/Power HAL 决定。本分支保留这些接口，不把 boost 强加给每次触摸。

基于此，**不加常驻轮询 `dumpsys`/前台应用的脚本**：它会主动唤醒 CPU，可能影响息屏省电，还可能与 ROM 的 Power HAL、thermal/DCVS 抢写。自动识别游戏和屏幕状态需要目标 ROM 的电源 HAL/系统服务，而不是只改内核即可安全完成。

Scene 官方[更新频道](https://t.me/s/scene2023)目前可见的最新版是 N1 2026.10 Beta14；Scene 9.x 的公告另列 9.4.17 Alpha（2026-08-21）和 9.4.11 稳定版（2026-08-09）。官方[主页](https://omarea.com/)把 Scene4 4.7.3 标为开放源码产品，另列 SCENE N1，但没有 N1 的源码链接。N1 26.09 Alpha8 的[官方更新记录](https://t.me/scene2023/405)提到 Launcher Boost 区分冷/热启动并使用不同持续时间，说明启动 boost 本身也是 Scene 控制的一部分。

按用户确认，当前实际使用的是[星野 Scene 仓库](https://github.com/xingyeovo/HoshinoScene-oss)最新发布版，并将其视为与原版行为一致的 Scene 参考；该仓当前 release 标注 N1 2026.10 Alpha14Lite / v1.2.1（2026-10-10）。官方频道的 N1 标号已到 Beta14，两者版本标签不同；官方 N1 源码没有公开链接，因此只依据用户确认使用星野版和其公开重建代码判断当前行为，不把它误标为官方源代码。仓库 [`docs/RECOVERY.md`](https://github.com/xingyeovo/HoshinoScene-oss/blob/de840c7927cf58747428a52309fb73f6c29b8c87/docs/RECOVERY.md)说明该工程由 APK 解包/JADX 还原而来。

星野 LP profile 会从云端 `/cloud-scheduler2` 按平台/版本下载 `powercfg.sh` 与 `manifest.json`（[LP 加载代码](https://github.com/xingyeovo/HoshinoScene-oss/blob/de840c7927cf58747428a52309fb73f6c29b8c87/app/src/main/java/a/um0.java)）；仓库没有你设备当前实际收到的 profile。其通用框架能写 cluster governor、频率上下限和 governor 参数（[调度执行代码](https://github.com/xingyeovo/HoshinoScene-oss/blob/de840c7927cf58747428a52309fb73f6c29b8c87/app/src/main/java/a/gb0.java)），但无法静态证明 LP 没有写 `schedutil` rate-limit 节点。故本分支不加入 Scene 专属或默认调度改动；在拿到设备上的 `/data/powercfg.sh` 或实际写入日志前，也不要一边运行 Scene LP、一边应用本仓的 `fast-down` 实验。`down_rate_limit_us=0` 是否能更快回落、是否仍保留启动响应和游戏帧时间，都需 MIX 4 上的 A/B 验证。

对照了五个骁龙 888 魔改内核：[engstk/op9](https://github.com/engstk/op9/commit/2a97f7d42aaf1848cc528d0a67e09d39f0218f6d)、[Aesir SM8350](https://github.com/bcrtvkcs/aesir_kernel_oneplus_sm8350/commit/d41024e08108d2a9e05fa32431222696f5ac378d)、[Feather](https://github.com/ozyern/Feather-Kernel-SM8350/commit/79f7aa8fe53e953dd0fa4759994f872d9bf106d1)、[Xiaomi mars](https://github.com/EcrosoftXiao/kernel_xiaomi_mars/commit/7e68a9f6d1fe092611d2b427c1773195a1605fd1) 和 [EndCredits MIUI SM8350](https://github.com/EndCredits/android_kernel_xiaomi_sm8350-miui/commit/6cb9f5a9edc161abda546ee23c8f8ba741655746)。它们有 MSM/Oplus/MI display blank 通知，但可见消费者主要是触控、充电/PMIC、LED 或 thermal screen-state 同步；没有发现 blank 直接触发 CPUFreq、cpuidle、调度或内存省电策略。odin 固定 5.4.302 树里的 Qualcomm cpufreq PM 通知只处理真正的 system suspend/resume，不等于用户锁屏。因设备实际 Scene LP 脚本未公开，也无法证明这些机制中有哪项是 Scene 覆盖不到的；本分支因此不加新的屏灭调频/限频策略，也不移植其他机型 OPP、电压、thermal、IRQ 或 GPU 数值。

## 指定基线继承的可回滚调速实验

`scripts/odin-schedutil-fast-down.sh` 继承自本分支的指定基线 `tune/sm8350-aggressive`；本 SID 修复分支没有修改或自动执行它。该脚本在 schedutil 仍负责动态升降频的前提下，允许用户手动把每个 policy 的 `down_rate_limit_us` 临时设成 `0`，让负载下降后更快尝试降频；`up_rate_limit_us` 保持不变。这是息屏/短时负载后的省电候选值，不是保证收益的默认策略，也不等同于按游戏/息屏自动切换。

脚本提供 `status`、`apply`、`restore`：`apply` 只在所有 policy 都是 schedutil 时才执行，先保存每个 policy 原始 up/down 值；`restore` 在同一次启动中逐项恢复。状态文件只允许 root 访问并带 boot ID；如果设备已重启，脚本只清除旧快照、不把旧值写进新启动策略。脚本不会改 governor、频率上限、OPP/电压、CPU 拓扑、IRQ、热管理或开机行为。任何卡顿、续航/温度回退或异常时可运行 `restore`；重启也会回到内核/ROM 自身默认策略。

此脚本会改写 schedutil 调速参数；Scene LP 配置按平台/版本从云端下载，当前没有设备侧脚本可证明两者不重叠。**Scene LP 正常控制时不要运行 `apply`**，除非先确认其实际配置没有写这些 policy tunables。SELinux SID 修复本身不改调度节点。

从 AnyKernel ZIP 导出脚本到设备后运行：

```sh
unzip -p out/Xiaomi-MIX4-odin-Los24-GApps-A17-k5.4.302-SUSFS2.4-BakaSU-sync-up-55f3dcb-SELinuxSIDHashFix-UNTESTED.zip tools/odin-schedutil-fast-down.sh > /tmp/odin-schedutil-fast-down.sh
adb push /tmp/odin-schedutil-fast-down.sh /data/local/tmp/odin-schedutil-fast-down.sh
adb shell su -c 'sh /data/local/tmp/odin-schedutil-fast-down.sh status'
adb shell su -c 'sh /data/local/tmp/odin-schedutil-fast-down.sh apply'
adb shell su -c 'sh /data/local/tmp/odin-schedutil-fast-down.sh restore'
```

先看 `status`，确认每个 policy 的 governor 与 tunables；若某 policy 不是 schedutil，脚本会拒绝修改。重启后若状态文件仍在，先运行 `restore` 让脚本识别并丢弃旧 boot ID，再考虑新一轮测试。

## 已核查的来源与未采用项

odin 基线已带 WALT/uclamp、schedutil、Qualcomm LPM、zram、NO_HZ/RCU、QTI thermal/DCVS。对照了 [OnePlus 9 SM8350 社区内核](https://github.com/dev-sm8350/kernel_oneplus_sm8350/tree/edf0a8d63717aa1cfc387f6fd6d13e02aa3ce579) 和 [OnePlus OSS Lahaina QGKI](https://github.com/OnePlusOSS/android_kernel_oneplus_sm8350/blob/13ca08fdf0979fdd61d5e8991661874bb2d19150/arch/arm64/configs/vendor/lahaina_QGKI.config)；不同机型的任务策略、boost、CPU 容量、DT/OPP、IRQ 和温控并不通用。没有 odin A/B 数据支持改 WALT 窗口、全局 sched_boost、CPU/IRQ 亲和性、频率/电压表、热表或 zram/writeback，所以都不复制、不关闭 throttling、不碰启动关键机制。MIX 4 schedutil 实现见[固定源码](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/kernel/sched/cpufreq_schedutil.c)。

## 构建与回归测试

固定输入全量构建 arm64 `Image` 并打 AnyKernel3 ZIP：

```sh
JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh
```

默认 `IDLE_GOVERNOR=teo`；可设 `IDLE_GOVERNOR=menu` 做 idle governor 对照。构建脚本会在集成 SUSFS 与 BakaSU 的源码树上运行 SELinux context-to-SID 静态回归检查，再校验 SUSFS 文件清单与哈希、所有来源 pin、BakaSU WebView 补丁只触及预期 Manager 文件、profile 脚本语法和关键配置；包内 Image 与独立 Image 会逐字节比较，ZIP 清单和完整性会检查，`source-pins.txt` 记录固定 SHA 和运行时 profile SHA-256。产物位于 `out/`。

可对已集成 SUSFS/BakaSU 的 Linux 5.4 源码树单独重跑 SELinux 静态检查：

```sh
python3 scripts/test-susfs-selinux-context-hash.py /path/to/integrated/kernel
```

可重复运行 mock-sysfs 回归测试（需要 root 或 sudo）：

```sh
bash scripts/test-odin-schedutil-fast-down.sh
```

测试覆盖同次启动 apply/restore 精确恢复、跨重启快照不写 sysfs、任一 policy 非 schedutil 时不做部分修改，以及 `status` 只读。它不能替代实机测试。

## MIX 4 实机验收

当前没有这台设备的测量数据。建议在同一固件/ROM、刷新率、亮度、网络、温度、应用和电量范围做 A/B/A：默认值 → 应用 fast-down → 恢复；每轮只改一个变量并重复。验收至少记录：

| 场景 | 需要记录 |
|---|---|
| 息屏过夜 | 持续时长、起止电量/电流、温度、网络、唤醒源、`wakeup_sources`、Qualcomm cpuidle residency、schedutil tunables |
| 游戏 | 游戏/画质/FPS 上限、帧时间 P50/P95/P99 与掉帧、CPU/GPU 频率/负载、温度和 thermal cap/限频时间、游戏退出后的降频/降温 |
| 日常交互 | 触摸至首帧延迟、滚动掉帧、input boost 实际值、后台/息屏唤醒情况 |
| 安全性 | 启动/重启/休眠唤醒、modem/Wi‑Fi、音频/相机、内核日志、异常重启与 SELinux/AVC |

若没有稳定的待机收益或游戏帧时间变差，就恢复默认，不保留该候选。构建和 ZIP 通过不证明能启动，也不能证明电池/游戏表现。SUSFS 逐文件移植与 5.4 API 适配审计见 [`port-notes.md`](port-notes.md)。

## 构建结果

本修复分支尚未完成全量构建，也没有生成本分支对应的 `UNTESTED` ZIP。`JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh` 在固定 AOSP Clang `android-17.0.0_r1` 的 `bin` 子树抓取阶段因空间不足（`No space left on device`）退出；因此本次修复没有新的 `.config`、Image 或 ZIP 可供验收。当前 `out/` 中保留的包来自之前的调度实验分支，不是本 SID 修复包，请勿用于验证本修复。

可在现有空间内完成的校验已通过：SUSFS port 文件集与 SHA-256、补丁空白检查、构建/实验脚本 shell 语法，以及将本分支的 `services.c`/`hooks.c` 叠加到只读集成树后运行的 SUSFS/BakaSU context-to-SID 静态回归检查。直接对未叠加当前修复的旧集成树运行回归检查会按预期失败；完整夹具的结果为 `PASS`。由于当前仅约 2.2 GB 可用，且没有确认可安全清理的本任务构建残留，未重试构建。

BakaSU #35262 仍为独立 Manager 源码补丁；该 AnyKernel 包设计只含内核镜像，不含 Manager APK。没有 MIX 4 实机冷启动 Termux、待机、游戏或电池 A/B 数据；**静态回归通过不代表已验证运行成功，也不代表性能或省电收益。**


## 可选 LZ4K zram 压缩器（`feature/odin-lz4k-zram`）

本功能分支基于已验证的 SID-fix 提交 `dc93390b87acbee7010ca4e9460d40ea5f1c0141` 单独创建；不修改 SID-fix、`tune/odin-daily-power`、现有内核包或 SUSFS 2.3 仓库 `kaixin886/odin-kernel-susfs`。

codec 和 crypto API 以 [openEuler kernel PR #1277](https://gitee.com/openeuler/kernel/pulls/1277.patch) 为上游参考。原始两提交补丁保存在 `port/lz4k/openEuler-pr-1277.patch`，SHA-256：`51f0fe4e7e2b9bdc782a59f7f977c37bd710140fb0613fd27f84b2743c7d997b`。5.4 适配器为 `CRYPTO_LZ4K` 增加 `CRYPTO_ACOMP2` 依赖，并在 `drivers/block/zram/zcomp.c` 原有 `NULL` 哨兵前加入 LZ4K backend。

构建只启用 `CONFIG_CRYPTO_LZ4K=y`，使压缩算法可选；不改现有 zram 默认算法、不强制运行时切换，也不加启动参数。构建脚本会比较集成前后的 `CONFIG_ZRAM*` 配置，并在发生变化时失败。

运行主机侧测试：

```sh
python3 scripts/test_lz4k.py
```

测试覆盖 4 KiB 页的重复/随机数据编码解码、ASan/UBSan 下损坏输入检查，以及适配器的 Kconfig 和 backend 哨兵回归。完整 arm64 构建由 `.github/workflows/build.yaml` 手动触发，产物名含 `lz4k`；本地构建空间有限时以该流程为准。即使构建成功，也仍需在 MIX 4 上验证启动、zram 运行、SELinux/Termux 与待机/游戏表现。没有实机数据前，不宣称压缩率、性能或能效收益。

此分支只包含 LZ4K。后续 Kcompressd 和 MGLRU 工作按既定顺序另行移植、单独测试，以便归因。
