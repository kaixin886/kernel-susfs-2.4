#!/usr/bin/env python3
"""Static regression checks for the pinned odin Linux 5.4.302 Kcompressd port."""

from pathlib import Path
import subprocess
import sys


PINNED_KERNEL_COMMIT = "50e0141b29b62be21632c768e4818348098ac6cd"


def fail(message: str) -> None:
    raise SystemExit(f"Kcompressd 5.4 regression failure: {message}")


def need(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        fail(f"missing or unsafe source file: {relative}")
    return path.read_text(encoding="utf-8")


def between(source: str, start: str, end: str, label: str) -> str:
    left = source.find(start)
    right = source.find(end, left + len(start)) if left >= 0 else -1
    if left < 0 or right < 0:
        fail(f"could not isolate {label}")
    return source[left:right]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <integrated-kernel-root>")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        fail(f"not a directory: {root}")

    git_dir = root / ".git"
    if git_dir.exists():
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        need(commit == PINNED_KERNEL_COMMIT,
             f"kernel commit {commit} does not match pinned {PINNED_KERNEL_COMMIT}")

    kconfig = read(root, "mm/Kconfig")
    makefile = read(root, "mm/Makefile")
    mmzone = read(root, "include/linux/mmzone.h")
    swap_h = read(root, "include/linux/swap.h")
    page_alloc = read(root, "mm/page_alloc.c")
    page_io = read(root, "mm/page_io.c")
    vmscan = read(root, "mm/vmscan.c")
    sysctl = read(root, "kernel/sysctl.c")
    swapfile = read(root, "mm/swapfile.c")
    worker = read(root, "mm/kcompressd.c")

    need("int sysctl_kcompressd;" in worker and "int sysctl_kcompressd = 64;" not in worker,
         "runtime activation must default to disabled")
    need(kconfig.count("config KCOMPRESSD\n") == 1,
         "KCOMPRESSD Kconfig entry missing or duplicated")
    kconfig_entry = between(kconfig, "config KCOMPRESSD\n", "config ZPOOL\n", "Kconfig entry")
    need("depends on SWAP && (ZRAM || ZSWAP)" in kconfig_entry and
         "default n" in kconfig_entry,
         "feature must remain optional and depend on swap plus a compression backend")
    need(makefile.count("obj-$(CONFIG_KCOMPRESSD) += kcompressd.o") == 1,
         "Kcompressd object is not wired exactly once")
    need(mmzone.count("struct kcompressd_state kcompressd;") == 1 and
         "#define KCOMPRESSD_QUEUE_SIZE 128" in mmzone and
         "unsigned int inflight;" in mmzone,
         "per-node bounded queue and in-flight state are missing")
    need("spin_lock_init(&pgdat->kcompressd.lock);" in page_alloc and
         "pgdat->kcompressd.accepting = false;" in page_alloc,
         "per-node queue state is not initialized")
    need("extern bool kcompressd_enqueue(struct page *page);" in swap_h and
         "extern bool kcompressd_writepage(struct page *page);" in swap_h,
         "swap API declarations do not match the worker ownership contract")

    enqueue = between(worker, "bool kcompressd_enqueue(", "static int kcompressd_worker(", "enqueue path")
    need("PageLocked(page)" in enqueue and "PageWriteback(page)" in enqueue,
         "enqueue must accept only a locked, not-already-writing page")
    need(enqueue.find("get_page(page)") < enqueue.find("state->pages[state->tail] = page") <
         enqueue.find("set_page_writeback(page)") < enqueue.find("spin_unlock_irqrestore"),
         "queue ref and writeback barrier must be published before dequeue is possible")
    need(enqueue.find("set_page_writeback(page)") < enqueue.find("wake_up_interruptible"),
         "worker wake must follow publication of the queue writeback barrier")
    need("state->count < limit" in enqueue and "limit > KCOMPRESSD_QUEUE_SIZE" in enqueue,
         "queue bound or runtime depth clamp is missing")

    swap_writepage = between(page_io, "int swap_writepage(",
                             "static inline void count_swpout_vm_event", "swap_writepage")
    need(swap_writepage.find("kcompressd_enqueue(page)") <
         swap_writepage.find("swap_writepage_io(page"),
         "enqueue must happen before the original frontswap/device write path")
    need("current_is_kswapd()" in swap_writepage and "PageAnon(page)" in swap_writepage and
         "frontswap_enabled()" in swap_writepage and "SWP_SYNCHRONOUS_IO" in swap_writepage,
         "submission must be limited to reclaim producers and eligible swap backends")
    need("Success keeps the page locked: 5.4 shrink_page_list() goes PAGE_SUCCESS -> keep." in swap_writepage,
         "5.4 page-lock ownership handoff must remain documented at the enqueue site")

    worker_write = between(page_io, "bool kcompressd_writepage(", "#endif", "worker write path")
    need(worker_write.find("end_page_writeback(page)") <
         worker_write.find("swap_writepage_io(page"),
         "synthetic queue barrier must hand off while the page lock still excludes swapoff")
    need("if (PageWriteback(page))\n\t\twait_on_page_writeback(page);" in worker_write,
         "synchronous bdev_write_page completion must be waited by the worker")
    endio = between(page_io, "static void end_kcompressd_swap_bio_write(",
                    "/* KCOMPRESSD_54_BACKPORT: preserve lock handoff", "Kcompressd end_io")
    need(endio.find("end_swap_bio_write(bio)") < endio.find("put_page(page)") <
         endio.find("kcompressd_bio_end(pgdat)"),
         "async BIO must finish writeback and release its page ref before decrementing in-flight")
    internal = between(page_io, "static int __swap_writepage_internal(",
                       "int __swap_writepage(", "internal swap writepage")
    need(internal.find("*bio_async = true") < internal.find("submit_bio(bio)"),
         "async reference transfer must be published before submit can complete inline")
    need(internal.find("bio->bi_private = pgdat") <
         internal.find("kcompressd_bio_start(pgdat)") < internal.find("submit_bio(bio)"),
         "async BIO must record and count its node before submission")
    need("if (bio == NULL)" in internal and "set_page_dirty(page)" in internal and
         "unlock_page(page)" in internal,
         "BIO allocation failure must dirty and unlock the page")

    io_accounting = between(worker, "void kcompressd_bio_start(",
                            "static int kcompressd_worker(", "BIO in-flight accounting")
    need("state->inflight++" in io_accounting and "state->inflight--" in io_accounting and
         "if (drained)\n\t\twake_up_all(&state->wait);" in io_accounting,
         "per-node BIO count must decrement and wake stop when fully drained")

    worker_loop = between(worker, "static int kcompressd_worker(", "int kcompressd_run(", "worker loop")
    need("wait_event_freezable" in worker_loop and "while ((page = kcompressd_dequeue(pgdat)))" in worker_loop,
         "freezer wait must occur at an empty-queue point and drain queued work")
    need("if (!kcompressd_writepage(page))\n\t\t\t\tput_page(page);" in worker_loop,
         "worker must put its queue ref only when ownership was not transferred to BIO end_io")
    need(worker_loop.find("while ((page = kcompressd_dequeue(pgdat)))") <
         worker_loop.find("if (kthread_should_stop())"),
         "stop must drain the ring before the thread exits")

    stop = between(worker, "void kcompressd_stop(", "\n}", "worker stop")
    need(stop.find("state->accepting = false") < stop.find("kthread_stop(task)") <
         stop.find("wait_event(state->wait, !READ_ONCE(state->inflight))") <
         stop.find("state->task = NULL"),
         "stop must close submissions, join worker, drain async BIOs, then clear its task")
    kswapd_stop = between(vmscan, "void kswapd_stop(int nid)", "static int __init kswapd_init", "kswapd stop")
    need(kswapd_stop.find("kcompressd_stop(NODE_DATA(nid))") <
         kswapd_stop.find("kthread_stop(kswapd)") <
         kswapd_stop.find("multi_kswapd_stop(nid)"),
         "node teardown must stop Kcompressd before primary and auxiliary kswapd threads")
    kswapd_run = between(vmscan, "int kswapd_run(int nid)", "void kswapd_stop(int nid)", "kswapd run")
    need(kswapd_run.find("kcompressd_run(pgdat)") < kswapd_run.find("multi_kswapd_run(nid)"),
         "per-node worker must be started before auxiliary producers")

    need(".procname\t= \"kcompressd\"" in sysctl and
         "SYSCTL_ZERO" in sysctl[sysctl.find('.procname\t= "kcompressd"'):
                                   sysctl.find('.procname\t= "kcompressd"') + 500],
         "vm.kcompressd must expose a nonnegative bounded runtime depth")
    need("max_kcompressd_depth = KCOMPRESSD_QUEUE_SIZE" in sysctl,
         "vm.kcompressd maximum must match the fixed per-node queue capacity")
    need("wait_on_page_writeback(page);" in swapfile and
         "page = find_get_page(swap_address_space(entry), i);" in swapfile,
         "pinned swapoff path must visit swapcache pages and wait for their writeback barrier")
    need("KCOMPRESSD_54_BACKPORT" in page_io and "KCOMPRESSD_54_BACKPORT" in vmscan,
         "5.4-specific adaptation markers are missing")
    shrink = between(vmscan, "static unsigned long shrink_page_list(",
                     "pgactivate = stat->nr_activate[0]", "pinned shrink_page_list")
    pageout_to_keep = shrink.find("if (PageWriteback(page))\n\t\t\t\t\tgoto keep;")
    keep_locked = shrink.find("keep_locked:\n\t\tunlock_page(page);\nkeep:")
    need(pageout_to_keep >= 0 and keep_locked > pageout_to_keep and
         shrink.find("list_add(&page->lru, &ret_pages);", keep_locked) > keep_locked,
         "pinned goto keep must bypass keep_locked unlock, preserving the queue's page-lock handoff")
    putback = between(vmscan, "void putback_lru_page(", "enum page_references", "pinned putback_lru_page")
    need("lru_cache_add(page)" in putback and "put_page(page)" in putback and
         "unlock_page(page)" not in putback,
         "pinned putback_lru_page must not be treated as an extra page unlock")

    print("Kcompressd odin Linux 5.4.302 static regression checks: PASS")
    print("Covered: pinned baseline, optional config, bounded per-node queue, lock/writeback handoff, "
          "frontswap ordering, async BIO refs and in-flight drain, swapoff wait, and hotplug order.")
    print("Not covered: kernel compilation, zswap recursion/PF_MEMALLOC runtime behavior, "
          "MIX 4 boot, suspend, swapoff stress, or memory-hotplug execution.")


if __name__ == "__main__":
    main()
