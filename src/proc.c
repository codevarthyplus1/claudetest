/*
 * proc.c - DistFS-KVM /proc interface
 *
 * Copyright (C) 2025 DistFS Contributors
 */

#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include "distfs.h"

/*
 * /proc/distfs-kvm/stats
 */
static int distfs_proc_stats_show(struct seq_file *m, void *v)
{
	struct distfs_context *ctx = m->private;
	struct distfs_device_manager *mgr = ctx->dev_mgr;
	struct distfs_device *dev;
	int i;

	seq_printf(m, "DistFS-KVM Statistics\n");
	seq_printf(m, "Version: %d.%d.%d\n",
		   DISTFS_VERSION_MAJOR, DISTFS_VERSION_MINOR,
		   DISTFS_VERSION_PATCH);
	seq_printf(m, "\nDevices: %d/%d\n\n",
		   mgr->num_devices, distfs_max_devices);

	mutex_lock(&mgr->lock);
	for (i = 0; i < DISTFS_MAX_DEVICES; i++) {
		dev = mgr->devices[i];
		if (!dev)
			continue;

		seq_printf(m, "Device: %s (/dev/%s)\n", dev->name,
			   dev->disk->disk_name);
		seq_printf(m, "  Size: %llu bytes\n", dev->size);
		seq_printf(m, "  Chunks: %u x %u bytes\n",
			   dev->num_chunks, dev->chunk_size);
		seq_printf(m, "  Replicas: %u\n", dev->replicas);
		seq_printf(m, "  Reads: %llu (%llu bytes)\n",
			   atomic64_read(&dev->reads),
			   atomic64_read(&dev->read_bytes));
		seq_printf(m, "  Writes: %llu (%llu bytes)\n",
			   atomic64_read(&dev->writes),
			   atomic64_read(&dev->write_bytes));
		seq_printf(m, "  Errors: %llu\n",
			   atomic64_read(&dev->errors));
		seq_printf(m, "\n");
	}
	mutex_unlock(&mgr->lock);

	return 0;
}

static int distfs_proc_stats_open(struct inode *inode, struct file *file)
{
	return single_open(file, distfs_proc_stats_show, PDE_DATA(inode));
}

static const struct proc_ops distfs_proc_stats_ops = {
	.proc_open	= distfs_proc_stats_open,
	.proc_read	= seq_read,
	.proc_lseek	= seq_lseek,
	.proc_release	= single_release,
};

/*
 * Initialize /proc interface
 */
int distfs_proc_init(struct distfs_context *ctx)
{
	ctx->proc_dir = proc_mkdir("distfs-kvm", NULL);
	if (!ctx->proc_dir)
		return -ENOMEM;

	if (!proc_create_data("stats", 0444, ctx->proc_dir,
			     &distfs_proc_stats_ops, ctx)) {
		remove_proc_entry("distfs-kvm", NULL);
		return -ENOMEM;
	}

	return 0;
}

/*
 * Cleanup /proc interface
 */
void distfs_proc_exit(struct distfs_context *ctx)
{
	if (ctx->proc_dir) {
		remove_proc_entry("stats", ctx->proc_dir);
		remove_proc_entry("distfs-kvm", NULL);
	}
}
