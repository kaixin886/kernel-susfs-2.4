#!/usr/bin/env python3
"""Apply the audited page-based Kcompressd backport to pinned odin Linux 5.4."""

from pathlib import Path
import os
import re
import stat
import sys
import tempfile


QUEUE_SIZE = 128
KCONFIG_BLOCK = f'''# KCOMPRESSD_54_BACKPORT
config KCOMPRESSD
\tbool "Asynchronous swap compression/writeback daemon"
\tdepends on SWAP && (ZRAM || ZSWAP)
\tdefault n
\thelp
\t  Offload anonymous swap compression and synchronous swap writeback from
\t  kswapd to one bounded worker per memory node. The runtime queue depth is
\t  controlled by vm.kcompressd, measured as queued pages per node. The
\t  integrated default is 32 pages per node; writing zero disables new
\t  asynchronous submissions. The sysctl range is 0..128, matching the fixed
\t  per-node queue capacity. This remains experimental and needs target-device
\t  validation before daily use.

'''


class PatchError(Exception):
    pass


def read_regular(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PatchError(f"expected regular, non-symlink file: {path}")
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def insert_before_once(text: str, anchor: str, addition: str, label: str) -> str:
    return replace_once(text, anchor, addition + anchor, label)


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def applied_already(root: Path, source: str) -> bool:
    files = {
        "kconfig": root / "mm/Kconfig",
        "makefile": root / "mm/Makefile",
        "mmzone": root / "include/linux/mmzone.h",
        "swap_h": root / "include/linux/swap.h",
        "page_alloc": root / "mm/page_alloc.c",
        "page_io": root / "mm/page_io.c",
        "vmscan": root / "mm/vmscan.c",
        "sysctl": root / "kernel/sysctl.c",
    }
    texts = {name: read_regular(path) for name, path in files.items()}
    present = [
        "config KCOMPRESSD" in texts["kconfig"],
        "obj-$(CONFIG_KCOMPRESSD) += kcompressd.o" in texts["makefile"],
        "struct kcompressd_state" in texts["mmzone"],
        "bool kcompressd_enqueue(struct page *page);" in texts["swap_h"],
        "pgdat->kcompressd.accepting = false;" in texts["page_alloc"],
        "kcompressd_enqueue(page)" in texts["page_io"],
        "kcompressd_bio_start(pgdat)" in texts["page_io"],
        "kcompressd_bio_end(pgdat)" in texts["page_io"],
        "kcompressd_run(pgdat)" in texts["vmscan"],
        "kcompressd_stop(NODE_DATA(nid))" in texts["vmscan"],
        '.procname\t= "kcompressd"' in texts["sysctl"],
    ]
    module = root / "mm/kcompressd.c"
    if any(present):
        if not all(present) or not module.is_file() or module.is_symlink():
            raise PatchError("partially applied Kcompressd backport; refusing to continue")
        if module.read_text(encoding="utf-8") != source:
            raise PatchError("existing mm/kcompressd.c differs from the pinned port source")
        return True
    if module.exists() or module.is_symlink():
        raise PatchError("unexpected existing mm/kcompressd.c on unpatched baseline")
    return False


def patch_page_io(text: str) -> str:
    start_marker = "int swap_writepage(struct page *page, struct writeback_control *wbc)\n"
    count = text.count(start_marker)
    if count != 1:
        raise PatchError(f"mm/page_io.c: expected one swap_writepage definition, found {count}")
    start = text.index(start_marker)
    end_marker = "static inline void count_swpout_vm_event(struct page *page)"
    end = text.find(end_marker, start)
    if end < 0:
        raise PatchError("mm/page_io.c: could not find count_swpout_vm_event after swap_writepage")
    old = text[start:end]
    if "frontswap_store(page) == 0" not in old or "__swap_writepage(page, wbc, end_swap_bio_write)" not in old:
        raise PatchError("mm/page_io.c: swap_writepage differs from audited 5.4 implementation")

    replacement = '''static int __swap_writepage_internal(struct page *page,
		struct writeback_control *wbc, bio_end_io_t end_write_func,
		bool *bio_async);

static int swap_writepage_io(struct page *page,
			     struct writeback_control *wbc,
			     bio_end_io_t end_write_func,
			     bool *bio_async)
{
	if (bio_async)
		*bio_async = false;
	if (frontswap_store(page) == 0) {
		set_page_writeback(page);
		unlock_page(page);
		end_page_writeback(page);
		return 0;
	}

	return __swap_writepage_internal(page, wbc, end_write_func, bio_async);
}

#ifdef CONFIG_KCOMPRESSD
/* The queue reference remains live until asynchronous BIO completion. */
static void end_kcompressd_swap_bio_write(struct bio *bio)
{
\tpg_data_t *pgdat = bio->bi_private;
\tstruct page *page = bio_first_page_all(bio);

\tend_swap_bio_write(bio);
\tput_page(page);
\tkcompressd_bio_end(pgdat);
}

/* KCOMPRESSD_54_BACKPORT: preserve lock handoff and frontswap ordering. */
bool kcompressd_writepage(struct page *page)
{
	struct writeback_control wbc = {
		.sync_mode = WB_SYNC_NONE,
		.nr_to_write = SWAP_CLUSTER_MAX,
		.range_start = 0,
		.range_end = LLONG_MAX,
		.for_reclaim = 1,
	};
	bool bio_async = false;

	VM_BUG_ON_PAGE(!PageLocked(page), page);
	VM_BUG_ON_PAGE(!PageSwapCache(page), page);
	VM_BUG_ON_PAGE(!PageWriteback(page), page);

	/* Drop only the queue barrier; the page lock still excludes swapoff. */
	end_page_writeback(page);
	(void)swap_writepage_io(page, &wbc, end_kcompressd_swap_bio_write,
				&bio_async);
	if (bio_async)
		return true;

	/* bdev_write_page() has its own completion path, not our BIO callback. */
	if (PageWriteback(page))
		wait_on_page_writeback(page);
	return false;
}
#endif

int swap_writepage(struct page *page, struct writeback_control *wbc)
{
	int ret = 0;
#ifdef CONFIG_KCOMPRESSD
	struct swap_info_struct *sis;
#endif

	if (try_to_free_swap(page)) {
		unlock_page(page);
		goto out;
	}
#ifdef CONFIG_KCOMPRESSD
	/* KCOMPRESSD_54_BACKPORT: enqueue before frontswap compression. */
	sis = page_swap_info(page);
	/* Success keeps the page locked: 5.4 shrink_page_list() goes PAGE_SUCCESS -> keep. */
	if (current_is_kswapd() && PageAnon(page) &&
	    (frontswap_enabled() || (sis->flags & SWP_SYNCHRONOUS_IO)) &&
	    kcompressd_enqueue(page))
		goto out;
#endif
	ret = swap_writepage_io(page, wbc, end_swap_bio_write, NULL);
out:
	return ret;
}

'''
    return text[:start] + replacement + text[end:]


def patch_internal_writepage(text: str) -> str:
    start_marker = "int __swap_writepage(struct page *page, struct writeback_control *wbc,\n"
    if text.count(start_marker) != 1:
        raise PatchError("mm/page_io.c: expected one audited __swap_writepage definition")
    start = text.index(start_marker)
    end_marker = "int swap_readpage(struct page *page, bool synchronous)"
    end = text.find(end_marker, start)
    if end < 0:
        raise PatchError("mm/page_io.c: could not find swap_readpage after __swap_writepage")
    old = text[start:end]
    if "bdev_write_page(sis->bdev" not in old or "submit_bio(bio)" not in old:
        raise PatchError("mm/page_io.c: __swap_writepage differs from audited 5.4 implementation")

    replacement = '''static int __swap_writepage_internal(struct page *page,
\t\tstruct writeback_control *wbc, bio_end_io_t end_write_func,
\t\tbool *bio_async)
{
\tstruct bio *bio;
\tint ret;
\tstruct swap_info_struct *sis = page_swap_info(page);

\tif (bio_async)
\t\t*bio_async = false;
\tVM_BUG_ON_PAGE(!PageSwapCache(page), page);
\tif (sis->flags & SWP_FS) {
\t\tstruct kiocb kiocb;
\t\tstruct file *swap_file = sis->swap_file;
\t\tstruct address_space *mapping = swap_file->f_mapping;
\t\tstruct bio_vec bv = {
\t\t\t.bv_page = page,
\t\t\t.bv_len  = PAGE_SIZE,
\t\t\t.bv_offset = 0
\t\t};
\t\tstruct iov_iter from;

\t\tiov_iter_bvec(&from, WRITE, &bv, 1, PAGE_SIZE);
\t\tinit_sync_kiocb(&kiocb, swap_file);
\t\tkiocb.ki_pos = page_file_offset(page);

\t\tset_page_writeback(page);
\t\tunlock_page(page);
\t\tret = mapping->a_ops->direct_IO(&kiocb, &from);
\t\tif (ret == PAGE_SIZE) {
\t\t\tcount_vm_event(PSWPOUT);
\t\t\tret = 0;
\t\t} else {
\t\t\tset_page_dirty(page);
\t\t\tClearPageReclaim(page);
\t\t\tpr_err_ratelimited("Write error on dio swapfile (%llu)\\n",
\t\t\t\t\t   page_file_offset(page));
\t\t}
\t\tend_page_writeback(page);
\t\treturn ret;
\t}

\tret = bdev_write_page(sis->bdev, swap_page_sector(page), page, wbc);
\tif (!ret) {
\t\tcount_swpout_vm_event(page);
\t\treturn 0;
\t}

\tret = 0;
\tbio = get_swap_bio(GFP_NOIO, page, end_write_func);
\tif (bio == NULL) {
\t\tset_page_dirty(page);
\t\tunlock_page(page);
\t\tret = -ENOMEM;
\t\tgoto out;
\t}
\tbio->bi_opf = REQ_OP_WRITE | REQ_SWAP | wbc_to_write_flags(wbc);
\tbio_associate_blkg_from_page(bio, page);
\tcount_swpout_vm_event(page);
#ifdef CONFIG_KCOMPRESSD
\tif (bio_async) {
\t\tpg_data_t *pgdat = page_zone(page)->zone_pgdat;

\t\tbio->bi_private = pgdat;
\t\tkcompressd_bio_start(pgdat);
\t}
#endif
\tset_page_writeback(page);
\tunlock_page(page);
\t/* Transfer the caller's extra page ref before completion can run. */
\tif (bio_async)
\t\t*bio_async = true;
\tsubmit_bio(bio);
out:
\treturn ret;
}

int __swap_writepage(struct page *page, struct writeback_control *wbc,
\t\tbio_end_io_t end_write_func)
{
\treturn __swap_writepage_internal(page, wbc, end_write_func, NULL);
}

'''
    return text[:start] + replacement + text[end:]


def patch_vmscan(text: str) -> str:
    run_anchor = "\tret = multi_kswapd_run(nid);"
    run_add = '''#ifdef CONFIG_KCOMPRESSD
\t/* KCOMPRESSD_54_BACKPORT: one independent drain worker per node. */
\tif (kcompressd_run(pgdat))
\t\tpr_warn("Failed to start kcompressd on node %d\\n", nid);
#endif
'''
    text = replace_once(text, run_anchor, run_add + run_anchor, "mm/vmscan.c kswapd_run")

    stop_anchor = "\tstruct task_struct *kswapd = NODE_DATA(nid)->kswapd;\n\n\tif (kswapd) {"
    stop_add = '''\tstruct task_struct *kswapd = NODE_DATA(nid)->kswapd;

#ifdef CONFIG_KCOMPRESSD
\t/* KCOMPRESSD_54_BACKPORT: stop accepting, drain, then stop kswapd. */
\tkcompressd_stop(NODE_DATA(nid));
#endif
\tif (kswapd) {'''
    return replace_once(text, stop_anchor, stop_add, "mm/vmscan.c kswapd_stop")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <pinned-kernel-root> <kcompressd.c-template>")

    root = Path(sys.argv[1]).resolve()
    template = Path(sys.argv[2])
    source = read_regular(template)
    if not root.is_dir():
        raise SystemExit(f"kernel source root is not a directory: {root}")
    try:
        if applied_already(root, source):
            print("Kcompressd 5.4 backport already applied and verified")
            return

        files = {
            "mm/Kconfig": read_regular(root / "mm/Kconfig"),
            "mm/Makefile": read_regular(root / "mm/Makefile"),
            "include/linux/mmzone.h": read_regular(root / "include/linux/mmzone.h"),
            "include/linux/swap.h": read_regular(root / "include/linux/swap.h"),
            "mm/page_alloc.c": read_regular(root / "mm/page_alloc.c"),
            "mm/page_io.c": read_regular(root / "mm/page_io.c"),
            "mm/vmscan.c": read_regular(root / "mm/vmscan.c"),
            "kernel/sysctl.c": read_regular(root / "kernel/sysctl.c"),
        }

        files["mm/Kconfig"] = insert_before_once(
            files["mm/Kconfig"], "config ZPOOL\n", KCONFIG_BLOCK,
            "mm/Kconfig Kcompressd option",
        )
        makefile = files["mm/Makefile"]
        swap_lines = list(re.finditer(
            r"(?m)^[ \t]*obj-\$\(CONFIG_SWAP\)[ \t]*\+=[^\n]*\n", makefile
        ))
        if len(swap_lines) != 1:
            raise PatchError(f"mm/Makefile: expected one CONFIG_SWAP object line, found {len(swap_lines)}")
        pos = swap_lines[0].end()
        files["mm/Makefile"] = (
            makefile[:pos]
            + "# KCOMPRESSD_54_BACKPORT\nobj-$(CONFIG_KCOMPRESSD) += kcompressd.o\n"
            + makefile[pos:]
        )

        mmzone = files["include/linux/mmzone.h"]
        queue_struct = '''#ifdef CONFIG_KCOMPRESSD
#define KCOMPRESSD_QUEUE_SIZE 128
struct kcompressd_state {
\tspinlock_t lock;
\twait_queue_head_t wait;
\tstruct task_struct *task;
\tstruct page *pages[KCOMPRESSD_QUEUE_SIZE];
\tunsigned int head;
\tunsigned int tail;
\tunsigned int count;
\tunsigned int inflight;
\tbool accepting;
};
#endif

'''
        mmzone = insert_before_once(mmzone, "struct pglist_data;\n", queue_struct,
                                    "include/linux/mmzone.h queue structure")
        mmzone = replace_once(
            mmzone,
            "\tstruct task_struct *kswapd;\n",
            "\tstruct task_struct *kswapd;\n#ifdef CONFIG_KCOMPRESSD\n"
            "\t/* KCOMPRESSD_54_BACKPORT */\n\tstruct kcompressd_state kcompressd;\n#endif\n",
            "include/linux/mmzone.h pgdat field",
        )
        files["include/linux/mmzone.h"] = mmzone

        swap_h = files["include/linux/swap.h"]
        prototype_anchor = "extern int __swap_writepage(struct page *page, struct writeback_control *wbc,\n\tbio_end_io_t end_write_func);\n"
        kcompressd_prototypes = '''#ifdef CONFIG_KCOMPRESSD
/* KCOMPRESSD_54_BACKPORT */
	extern bool kcompressd_enqueue(struct page *page);
	extern int kcompressd_run(pg_data_t *pgdat);
	extern void kcompressd_stop(pg_data_t *pgdat);
	extern void kcompressd_bio_start(pg_data_t *pgdat);
	extern void kcompressd_bio_end(pg_data_t *pgdat);
	extern bool kcompressd_writepage(struct page *page);
	extern int sysctl_kcompressd;
#endif
'''
        files["include/linux/swap.h"] = replace_once(
            swap_h, prototype_anchor, prototype_anchor + kcompressd_prototypes,
            "include/linux/swap.h Kcompressd API",
        )

        page_alloc = files["mm/page_alloc.c"]
        init_anchor = "\tinit_waitqueue_head(&pgdat->kswapd_wait);\n"
        init_queue = '''#ifdef CONFIG_KCOMPRESSD
\t/* KCOMPRESSD_54_BACKPORT */
\tspin_lock_init(&pgdat->kcompressd.lock);
\tinit_waitqueue_head(&pgdat->kcompressd.wait);
\tpgdat->kcompressd.task = NULL;
\tpgdat->kcompressd.head = 0;
\tpgdat->kcompressd.tail = 0;
\tpgdat->kcompressd.count = 0;
\tpgdat->kcompressd.inflight = 0;
\tpgdat->kcompressd.accepting = false;
#endif
'''
        files["mm/page_alloc.c"] = replace_once(
            page_alloc, init_anchor, init_anchor + init_queue,
            "mm/page_alloc.c pgdat initialization",
        )

        files["mm/page_io.c"] = patch_page_io(files["mm/page_io.c"])
        files["mm/page_io.c"] = patch_internal_writepage(files["mm/page_io.c"])
        files["mm/vmscan.c"] = patch_vmscan(files["mm/vmscan.c"])

        sysctl = files["kernel/sysctl.c"]
        vm_anchor = "static struct ctl_table vm_table[] = {\n"
        sysctl = insert_before_once(
            sysctl, vm_anchor,
            "#ifdef CONFIG_KCOMPRESSD\nstatic int max_kcompressd_depth = KCOMPRESSD_QUEUE_SIZE;\n#endif\n\n",
            "kernel/sysctl.c max queue depth",
        )
        sysctl_entry_anchor = '\t{\n\t\t.procname\t= "watermark_scale_factor",'
        sysctl_entry = '''#ifdef CONFIG_KCOMPRESSD
\t/* KCOMPRESSD_54_BACKPORT */
\t{
\t\t.procname\t= "kcompressd",
\t\t.data\t\t= &sysctl_kcompressd,
\t\t.maxlen\t\t= sizeof(sysctl_kcompressd),
\t\t.mode\t\t= 0644,
\t\t.proc_handler\t= proc_dointvec_minmax,
\t\t.extra1\t\t= SYSCTL_ZERO,
\t\t.extra2\t\t= &max_kcompressd_depth,
\t},
#endif
'''
        files["kernel/sysctl.c"] = insert_before_once(
            sysctl, sysctl_entry_anchor, sysctl_entry,
            "kernel/sysctl.c vm.kcompressd entry",
        )

        module_path = root / "mm/kcompressd.c"
        for relpath, text in files.items():
            atomic_write(root / relpath, text)
        atomic_write(module_path, source, 0o644)
    except PatchError as error:
        raise SystemExit(f"Kcompressd backport refused: {error}") from error

    print("Applied Kcompressd page-based Linux 5.4 backport to pinned source")


if __name__ == "__main__":
    main()
