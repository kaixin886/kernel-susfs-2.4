# Xiaomi MIX 4（odin）5.4.302 日常响应与功耗调优

本次调优位于独立分支 `tune/odin-daily-power`，从已验证的 `fix/susfs24-selinux-context-sid` 提交 `dc93390` 创建；不会改写 SID 修复分支或 SUSFS 2.3 仓库 `kaixin886/odin-kernel-susfs`。目标设备为 Xiaomi MIX 4 / Snapdragon 888 / Linux 5.4.302，重点是保留日常调频响应、缩短负载回落后的降频等待。当前没有 MIX 4 实测结果，不宣称省电或性能收益。

## 固定集成版本

| 组件 | 固定来源 |
|---|---|
| odin 内核 | [Inkypen `kernel_xiaomi_odin`](https://github.com/Inkypen79/kernel_xiaomi_odin/commit/50e0141b29b62be21632c768e4818348098ac6cd) |
| SUSFS | v2.4.0；移植文件与校验和见 `port/SHA256SUMS` |
| BakaSU | [`sync-up` 提交 `55f3dcb`](https://github.com/Baka-SU/BakaSU/commit/55f3dcb11a0ce5b8aad3cb9763b200fe52efe218) |
| BakaSU Manager WebView #35262 | [`7b65bde`](https://github.com/Baka-SU/BakaSU/commit/7b65bde0710b5e7c6f755545cb15a4abd417f3a8)，只作 Manager 源码修复，不包含在内核 ZIP 中 |
| AnyKernel3 | [`41f04bd`](https://github.com/osm0sis/AnyKernel3/commit/41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1) |
| AOSP Clang | `android-17.0.0_r1` / Clang 22.0.2 / commit `29182889399818f97baa65ea238c80e8117981eb` |

ROM 标签按设备所有者提供的 LineageOS 24.0 GApps / Android 17 信息标注；ROM 与本优化包的设备启动仍须实测。

## 借鉴与本分支改动

MIX 4 固定源码和 OnePlus 9 的 SM8350 Linux 5.4 [schedutil 实现](https://github.com/dev-sm8350/kernel_oneplus_sm8350/blob/edf0a8d63717aa1cfc387f6fd6d13e02aa3ce579/kernel/sched/cpufreq_schedutil.c)都保留 scheduler 驱动的动态调频；原始默认会让升、降频限速都取设备报告的 `cpufreq_policy_transition_delay_us(policy)`。[StatixOS 的 SM8350 设备电源策略评审](https://review.statixos.com/c/android_device_oneplus_sm8350-common/+/11042/2?usp=related-change)则采用“屏幕关闭时”把两项 rate limit 设为 2 ms 的 Power HAL/powerhint 策略。这说明同平台做法会缩短回落等待，但它依赖屏幕状态事件，属于设备侧电源策略，不应伪装成内核能自行识别息屏。

本分支没有屏幕状态 Power HAL，也不安装常驻轮询服务，所以采用一个窄的内核默认值：每个 schedutil policy 初始化时仅将 `down_rate_limit_us` 设为 `0`，`up_rate_limit_us` 继续使用原设备转换延迟。负载下降后，schedutil 不再额外等待该降频限速；升频、WALT/uclamp 调度逻辑不变。Android 用户空间或 Power HAL 后续仍可能覆盖这些 sysfs 参数，因此实际值要在设备上检查。

这个策略比屏幕关闭专用的 2 ms 更激进，适用于测试“应用启动/短负载结束后高频驻留是否过长”；它也可能增加频率来回变化，或影响负载突发时的流畅度。源码修改本身不证明省电、温度或帧率会变好，必须在同一 MIX 4 上做 A/B/A。

## 保留不动的部分

SUSFS 2.4 的 SELinux context-to-SID 修复保持原样：过滤后的 context 仍交由 5.4 的 `context_struct_to_sid()` 完成 hash-aware 转换；没有改 enforcing、SELinux policy 或 BakaSU hide 行为。WALT、task/group uclamp、CPUFreq 上限、Qualcomm LPM、TEO、NO_HZ/RCU、QTI thermal/DCVS 与 CPU 热保护配置均保留；不移植其他机型的 OPP、电压、拓扑、IRQ/GPU 或温控数值。

## 脚本与回归测试

构建会先运行 `scripts/apply-odin-schedutil-default.py`：它只匹配固定内核源码中的唯一初始化块，保留原升频默认，并拒绝重复或有歧义的源文件。`scripts/test-odin-schedutil-default.py` 覆盖精准替换、未改动上下文、重复应用、缺失与重复匹配；`scripts/odin-schedutil-fast-down.sh` 仍提供设备侧 `status|apply|restore`，只作临时手动测试并精确恢复运行时原值。

```sh
python3 scripts/test-odin-schedutil-default.py
bash scripts/test-odin-schedutil-fast-down.sh
JOBS=8 INSTALL_DEPS=0 bash scripts/build-kernel.sh
```

完整构建会再运行 SUSFS/BakaSU SID 静态回归检查，校验配置、源码 pin、AnyKernel ZIP 清单、包内 Image 与独立 Image 的一致性，并记录来源与补丁哈希。包名包含 `Xiaomi-MIX4-odin`、内核/SUSFS/BakaSU 版本、`SELinuxSIDHashFix`、`SchedutilFastDown` 与 `UNTESTED`。

## MIX 4 验收

保持 ROM、亮度、刷新率、网络、室温和电量区间一致，先测旧内核，再测此分支，最后恢复旧内核（A/B/A）。记录息屏耗电与唤醒源、CPUFreq policy 实际 governor/rate-limit、cpuidle residency；日常记录触摸到首帧、滚动掉帧；游戏记录帧时间 P50/P95/P99、温度及 thermal 限频。若续航没有稳定改善或交互/游戏退化，恢复此前可启动的内核。构建或 ZIP 校验通过也不能替代冷启动、Termux、网络、相机/音频、休眠唤醒和热控实测。

**当前状态：** 补丁、语法与模拟回归测试通过；本分支完整 `Image`/AnyKernel 包与 MIX 4 实机 A/B 尚未验证。当前工作区仅余约 2.6 GB，而固定 Clang 工具链目录约 3.5 GB；为避免空间耗尽，没有启动会下载并展开工具链的全量构建，也没有覆盖 `out/` 中此前调度实验分支的文件。那些旧文件不可当作本分支产物。
