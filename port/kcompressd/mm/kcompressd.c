// SPDX-License-Identifier: GPL-2.0
/*
 * Kcompressd: move anonymous swap compression/writeback off kswapd.
 *
 * This is a page-based Linux 5.4 backport. Queueing is bounded and
 * serialized because this vendor tree can run multiple kswapd producers
 * for a node. A successful enqueue transfers the locked page and its
 * synthetic writeback barrier to this worker; the caller must not touch it
 * again. The worker or its I/O completion path releases the queue reference.
 */
#include <linux/freezer.h>
#include <linux/kthread.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/sched.h>
#include <linux/swap.h>

/* Keep the experimental path opt-in until MIX 4 runtime testing is done. */
int sysctl_kcompressd;

static struct page *kcompressd_dequeue(pg_data_t *pgdat)
{
	struct kcompressd_state *state = &pgdat->kcompressd;
	struct page *page = NULL;
	unsigned long flags;

	spin_lock_irqsave(&state->lock, flags);
	if (state->count) {
		page = state->pages[state->head];
		state->pages[state->head] = NULL;
		state->head = (state->head + 1) % KCOMPRESSD_QUEUE_SIZE;
		state->count--;
	}
	spin_unlock_irqrestore(&state->lock, flags);

	return page;
}

bool kcompressd_enqueue(struct page *page)
{
	struct pglist_data *pgdat = page_zone(page)->zone_pgdat;
	struct kcompressd_state *state = &pgdat->kcompressd;
	unsigned long flags;
	int limit = READ_ONCE(sysctl_kcompressd);
	bool queued = false;

	if (limit <= 0 || !PageLocked(page) || PageWriteback(page))
		return false;
	if (limit > KCOMPRESSD_QUEUE_SIZE)
		limit = KCOMPRESSD_QUEUE_SIZE;

	spin_lock_irqsave(&state->lock, flags);
	if (state->accepting && state->task && state->count < limit) {
		get_page(page);
		state->pages[state->tail] = page;
		state->tail = (state->tail + 1) % KCOMPRESSD_QUEUE_SIZE;
		state->count++;
		/*
		 * Publish a swapoff/reclaim barrier before the worker can dequeue.
		 * The page lock remains held until the real write path takes over.
		 */
		set_page_writeback(page);
		queued = true;
	}
	spin_unlock_irqrestore(&state->lock, flags);

	if (queued)
		wake_up_interruptible(&state->wait);

	return queued;
}

/* Called before submitting a BIO; stop waits for the matching completion. */
void kcompressd_bio_start(pg_data_t *pgdat)
{
	struct kcompressd_state *state = &pgdat->kcompressd;
	unsigned long flags;

	spin_lock_irqsave(&state->lock, flags);
	state->inflight++;
	spin_unlock_irqrestore(&state->lock, flags);
}

/* Called last in end_io, after writeback and the BIO's page ref are released. */
void kcompressd_bio_end(pg_data_t *pgdat)
{
	struct kcompressd_state *state = &pgdat->kcompressd;
	unsigned long flags;
	bool drained = false;

	spin_lock_irqsave(&state->lock, flags);
	if (WARN_ON_ONCE(!state->inflight)) {
		spin_unlock_irqrestore(&state->lock, flags);
		return;
	}
	state->inflight--;
	drained = !state->inflight;
	spin_unlock_irqrestore(&state->lock, flags);

	if (drained)
		wake_up_all(&state->wait);
}

static int kcompressd_worker(void *arg)
{
	pg_data_t *pgdat = arg;
	struct kcompressd_state *state = &pgdat->kcompressd;
	struct page *page;
	unsigned int saved_flags;

	/* Match the reclaim/writeback privileges of the kswapd producer. */
	saved_flags = current->flags & (PF_MEMALLOC | PF_SWAPWRITE | PF_KSWAPD);
	current->flags |= PF_MEMALLOC | PF_SWAPWRITE | PF_KSWAPD;
	set_freezable();

	for (;;) {
		wait_event_freezable(state->wait,
				     kthread_should_stop() ||
				     READ_ONCE(state->count));

		while ((page = kcompressd_dequeue(pgdat))) {
			/* true means async BIO end_io owns and drops the queue ref. */
			if (!kcompressd_writepage(page))
				put_page(page);
			cond_resched();
		}

		if (kthread_should_stop())
			break;
	}

	current->flags &= ~(PF_MEMALLOC | PF_SWAPWRITE | PF_KSWAPD);
	current->flags |= saved_flags;
	return 0;
}

int kcompressd_run(pg_data_t *pgdat)
{
	struct kcompressd_state *state = &pgdat->kcompressd;
	struct task_struct *task;
	unsigned long flags;

	spin_lock_irqsave(&state->lock, flags);
	if (state->task) {
		spin_unlock_irqrestore(&state->lock, flags);
		return 0;
	}
	if (WARN_ON_ONCE(state->count || state->inflight)) {
		spin_unlock_irqrestore(&state->lock, flags);
		return -EBUSY;
	}
	spin_unlock_irqrestore(&state->lock, flags);

	task = kthread_run(kcompressd_worker, pgdat, "kcompressd%d",
			   pgdat->node_id);
	if (IS_ERR(task))
		return PTR_ERR(task);

	spin_lock_irqsave(&state->lock, flags);
	state->task = task;
	state->accepting = true;
	spin_unlock_irqrestore(&state->lock, flags);

	return 0;
}

void kcompressd_stop(pg_data_t *pgdat)
{
	struct kcompressd_state *state = &pgdat->kcompressd;
	struct task_struct *task;
	unsigned long flags;

	spin_lock_irqsave(&state->lock, flags);
	state->accepting = false;
	task = state->task;
	spin_unlock_irqrestore(&state->lock, flags);

	if (!task)
		return;

	wake_up_all(&state->wait);
	/* Drain the ring before returning from the worker. */
	kthread_stop(task);
	/* A dequeued async BIO can outlive its worker; keep pgdat alive for end_io. */
	wait_event(state->wait, !READ_ONCE(state->inflight));

	spin_lock_irqsave(&state->lock, flags);
	state->task = NULL;
	spin_unlock_irqrestore(&state->lock, flags);
}
