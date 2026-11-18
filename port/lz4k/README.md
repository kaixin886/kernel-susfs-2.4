# LZ4K 移植来源与 5.4 适配

实现以 openEuler kernel PR [#1277](https://gitee.com/openeuler/kernel/pulls/1277.patch) 为起点；原始两提交 patch 保存在 `openEuler-pr-1277.patch`，SHA-256 为 `51f0fe4e7e2b9bdc782a59f7f977c37bd710140fb0613fd27f84b2743c7d997b`。移植器只应用 PR 的第一提交（crypto codec 与 Kconfig/Makefile），并单独处理 zram backend，让上游实现可追溯且不会把上游 5.10 假设直接带进 MIX 4 的 5.4.302。

## Linux 5.4 的两项适配

- `CRYPTO_LZ4K` 除 `CRYPTO_ALGAPI` 外显式选择 `CRYPTO_ACOMP2`。这是 5.4 同一 crypto compression API 中 `CRYPTO_LZ4`、`CRYPTO_LZ4HC` 等算法使用的依赖；LZ4K 通过 zram 的 `crypto_comp` 路径注册。
- 5.4 的 `drivers/block/zram/zcomp.c` backend 数组以 `NULL` 结尾。移植器在该哨兵之前有条件地加入 `lz4k`，不会替换或移动哨兵。

构建将 `CONFIG_CRYPTO_LZ4K=y` 编入内核，使其在 zram 可用算法列表中可选；不修改 zram 启动配置或既有默认压缩算法，也不切换启动参数。真正选择 LZ4K 运行 zram 需要在设备端另行显式设置并测试。

## 验证边界

`python3 scripts/test_lz4k.py` 会对上游 encoder/decoder 做主机侧 4 KiB 回环、边界及随机损坏输入检查，并检查 5.4 适配函数的幂等和哨兵顺序。该测试不等于内核完整构建、启动或 MIX 4 实测。没有设备端 zram 压缩率、耗电、温度或游戏测试前，不宣称 LZ4K 带来性能或能效提升。
