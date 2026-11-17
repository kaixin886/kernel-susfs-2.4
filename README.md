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

## 动态省电的策略边界

本分支不把 CPU 固定在高频，也不硬编码某款游戏的频率/核心亲和性。策略由内核调度器、设备 ROM 的 Power HAL 和 SoC 热管理分层完成：

- **CPU 负载变化：** 固定 odin 源码提供 schedutil，并启用 WALT 和 task/group uclamp；本项目沿用平衡分支的 schedutil 默认值，让调频跟随运行负载。Android 的顶层任务/性能提示可通过设备 Power HAL 影响实际策略。
- **空闲/息屏：** 保留 Qualcomm LPM、TEO、NO_HZ/RCU 和 QTI thermal/DCVS。AOSP Power HAL 的 `setInteractive(false)` 是进入非交互（通常是息屏）时调整 CPUfreq 参数、允许系统低功耗 suspend 的入口；本仓只有内核，没有目标 ROM 的 Power HAL 源码，故不伪造屏幕状态检测器。
- **游戏/高负载：** Android Performance Hint / ADPF 允许游戏向系统报告工作时长和目标帧期限，再由设备按本机拓扑与热设计调资源；[AOSP 文档](https://source.android.com/docs/core/perf/performance-hint-api)明确不应把核心亲和性写死。[Power HAL 接口](https://android.googlesource.com/platform/hardware/interfaces/+/fd877b5479b1639b4ba57af5c1f78a7a463e6be1/power/1.0/IPower.hal)中的 `powerHint()` 也由平台决定如何处理。
- **触控瞬时响应：** odin WALT 有事件驱动的 [cpu-boost](https://github.com/Inkypen79/kernel_xiaomi_odin/blob/50e0141b29b62be21632c768e4818348098ac6cd/kernel/sched/walt/cpu-boost.c)：收到输入事件后短时增加 CPU 频率下限/可选 scheduler boost，然后自动撤销；源码中的输入 boost 时长默认 40 ms，但各 CPU 的 `input_boost_freq` 和 `sched_boost_on_input` 默认都为 0，因此是否启用由 ROM/Power HAL 决定。本分支保留这些接口，不把 boost 强加给每次触摸。

基于此，**不加常驻轮询 `dumpsys`/前台应用的脚本**：它会主动唤醒 CPU，可能影响息屏省电，还可能与 ROM 的 Power HAL、thermal/DCVS 抢写。自动识别游戏和屏幕状态需要目标 ROM 的电源 HAL/系统服务，而不是只改内核即可安全完成。

## 本分支新增的可回滚实验

新增 `scripts/odin-schedutil-fast-down.sh`。在 schedutil 仍负责动态升降频的前提下，用户可手动把每个 policy 的 `down_rate_limit_us` 临时设成 `0`，让负载下降后更快尝试降频；`up_rate_limit_us` 保持不变。这是息屏/短时负载后的省电候选值，不是保证收益的默认策略，也不等同于按游戏/息屏自动切换。

脚本提供 `status`、`apply`、`restore`：`apply` 只在所有 policy 都是 schedutil 时才执行，先保存每个 policy 原始 up/down 值；`restore` 在同一次启动中逐项恢复。状态文件只允许 root 访问并带 boot ID；如果设备已重启，脚本只清除旧快照、不把旧值写进新启动策略。脚本不会改 governor、频率上限、OPP/电压、CPU 拓扑、IRQ、热管理或开机行为。任何卡顿、续航/温度回退或异常时可运行 `restore`；重启也会回到内核/ROM 自身默认策略。

从 AnyKernel ZIP 导出脚本到设备后运行：

```sh
unzip -p out/odin-susfs-v2.4.0-bakasu-ak3.zip tools/odin-schedutil-fast-down.sh > /tmp/odin-schedutil-fast-down.sh
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

默认 `IDLE_GOVERNOR=teo`；可设 `IDLE_GOVERNOR=menu` 做 idle governor 对照。构建脚本校验 SUSFS 文件清单与哈希、所有来源 pin、BakaSU WebView 补丁只触及预期 Manager 文件、profile 脚本语法和关键配置；包内 Image 与独立 Image 会逐字节比较，ZIP 清单和完整性会检查，`source-pins.txt` 记录固定 SHA 和运行时 profile SHA-256。产物位于 `out/`。

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

2026-11-18 00:44（UTC+8）以 `JOBS=8 INSTALL_DEPS=0` 完成固定 arm64 全量构建，退出码为 0；内核版本串为 `5.4.302-inkypen-v2`。AOSP Clang `android-17.0.0_r1` / `2918288…` 的全部固定子树均通过校验；下载 `musl` 子树时一次 HTTP 503 后重试成功并通过哈希校验。

最终 `.config` 已确认 `CONFIG_CPU_FREQ=y`，默认 governor 为 schedutil（performance governor 仍编入以供平台切换），WALT、uclamp task/group、Qualcomm LPM、TEO、NO_HZ/RCU、QTI thermal/DCVS 及 CPU isolation/hotplug/voltage cooling 配置保留；TEO 由追加的 `cpuidle.governor=teo` 请求，强制替换 bootloader 命令行仍关闭。SUSFS、BakaSU 和关键配置断言均通过。

构建和独立复核均通过：SUSFS 文件集/哈希、源码 pin、mock-sysfs 四项回归、`sha256sum -c out/SHA256SUMS`、ZIP 完整性、ZIP 恰为 pinned AnyKernel3 模板文件集的 29 项，且包内 Image 和 fast-down 脚本分别与构建产物/源码逐字节一致。`out/Image` SHA-256 为 `16f1427e137d9e02fa4f3f0f7ea9ad3dcfc07b9cd7ec9d4041908e84379748f4`；`out/odin-susfs-v2.4.0-bakasu-ak3.zip` SHA-256 为 `22eaca72083e59757cc738392ea78c85246ee516218ea59229fe4c5020e9a6ca`。其余产物哈希列在 `out/SHA256SUMS`；运行时脚本 SHA-256 为 `86c2047f569b6aecd8a06401c0f0093be4bfb35f404429735d2c50c4a040d38e`。

**已知构建告警：** 固定上游 `drivers/thermal/thermal_core.c` 有三条 `-Wfortify-source` 告警（第 1895、1976、1995 行，`PAGE_SIZE` 参数 4096 大于 128 字节目标缓冲区）；MODPOST 另提示 `embms_tm_multicast_recv` 是 static `EXPORT_SYMBOL`。Kconfig 还报告 schedutil 默认和 KSU_SUSFS 选择项被显式覆盖；最终 `.config` 断言通过。这些内核源文件没有被本分支修改；为遵守保留热管理的要求，未对 thermal 代码做未经验证的改写。无编译错误。

BakaSU #35262 的路径、单文件范围、干净应用和实际 binary diff SHA 已验证；未生成 Manager APK，也未运行 Manager Gradle 编译，因为环境未提供 Android SDK（`ANDROID_HOME`/`ANDROID_SDK_ROOT` 均未配置）。没有 MIX 4 实机启动、待机、游戏或电池 A/B 数据；**构建通过不代表已验证启动安全、性能提升或省电收益。**
