# Xiaomi MIX 4 (odin) — RCU nocb diagnostic

**Status: UNTESTED on a physical device.** The cloud build and static package checks do not establish that this kernel boots or is stable on the phone. Do not infer power or performance gains from this package.

## Scope

This package is based on the 2026-11-19 bootable baseline for Xiaomi MIX 4 (odin), Inkypen LineageOS 24.0 GApps / Android 17, Linux 5.4.302, SUSFS 2.4, and BakaSU sync-up `55f3dcb`.

The only kernel configuration delta is the added built-in command-line token `rcu_nocbs=all`. The baseline already had `CONFIG_RCU_NOCB_CPU=y`; the diagnostic does not enable `rcu_nocb_poll` or change the TEO idle governor. Build verification compares the full baseline config snapshot and fails unless only `CONFIG_CMDLINE` gains that token.

## Rollback

Keep this known-good November 19 AnyKernel3 ZIP available in recovery before installing the diagnostic:

`Xiaomi-MIX4-odin-Los24-GApps-A17-k5.4.302-SUSFS2.4-BakaSU-sync-up-55f3dcb-SIDHashFix-DailyPower-LZ4K-Kcompressd-DefaultOn-Q32-MGLRU-EnabledDefault-UNTESTED.zip`

SHA-256: `40ae8ffd6664a695afd06b2d222b91d985426ce6d9ae3c1f36ae57471eea71ac`

If the diagnostic fails to boot or behaves abnormally, use the same custom recovery / kernel-flasher method to install that November 19 ZIP again; it restores the known-good kernel Image to the boot partition. If recovery is unavailable, restore a previously saved full boot image using the device's bootloader/recovery procedure. Do not flash the standalone `Image` file as if it were a complete `boot.img`.
