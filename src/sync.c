/*
 * sync.c - DistFS-KVM device synchronization across hosts
 *
 * This module handles synchronization of device state across multiple
 * KVM hosts, ensuring that all hosts see the same devices.
 *
 * Copyright (C) 2025 DistFS Contributors
 */

#include <linux/slab.h>
#include <linux/workqueue.h>
#include <linux/delay.h>
#include "distfs.h"

/* Device synchronization work */
struct distfs_sync_work {
	struct delayed_work work;
	struct distfs_context *ctx;
};

static struct distfs_sync_work *sync_work;

/*
 * Synchronize devices from metadata server
 *
 * This queries the metadata server for all registered devices and ensures
 * that the local kernel module has corresponding block devices created.
 * This allows devices created on one host to automatically appear on all hosts.
 */
static int distfs_sync_devices(struct distfs_context *ctx)
{
	struct distfs_cluster *cluster = ctx->cluster;
	struct distfs_device_manager *mgr = ctx->dev_mgr;
	/* TODO: Actual implementation would:
	 * 1. Query metadata server for device list
	 * 2. Compare with local devices
	 * 3. Create missing devices locally
	 * 4. Remove devices deleted remotely
	 */

	distfs_dbg("Synchronizing devices with cluster\n");

	if (!cluster || !mgr) {
		distfs_warn("Cluster or device manager not initialized\n");
		return -EINVAL;
	}

	/* For now, just log that we would sync */
	distfs_dbg("Device sync: would query metadata server and sync devices\n");

	return 0;
}

/*
 * Device synchronization work function
 *
 * Periodically synchronizes devices with the metadata server to ensure
 * all hosts have consistent view of available devices.
 */
static void distfs_sync_work_fn(struct work_struct *work)
{
	struct distfs_sync_work *sync = container_of(to_delayed_work(work),
						      struct distfs_sync_work,
						      work);
	struct distfs_context *ctx = sync->ctx;

	/* Perform synchronization */
	distfs_sync_devices(ctx);

	/* Reschedule for next sync (every 30 seconds) */
	queue_delayed_work(system_wq, &sync->work, 30 * HZ);
}

/*
 * Initialize device synchronization
 *
 * Sets up periodic synchronization of devices across cluster nodes.
 */
int distfs_sync_init(struct distfs_context *ctx)
{
	if (!ctx)
		return -EINVAL;

	sync_work = kzalloc(sizeof(*sync_work), GFP_KERNEL);
	if (!sync_work)
		return -ENOMEM;

	sync_work->ctx = ctx;
	INIT_DELAYED_WORK(&sync_work->work, distfs_sync_work_fn);

	/* Start synchronization (after 5 second delay) */
	queue_delayed_work(system_wq, &sync_work->work, 5 * HZ);

	distfs_info("Device synchronization initialized\n");
	return 0;
}

/*
 * Cleanup device synchronization
 */
void distfs_sync_exit(void)
{
	if (sync_work) {
		cancel_delayed_work_sync(&sync_work->work);
		kfree(sync_work);
		sync_work = NULL;
	}

	distfs_info("Device synchronization stopped\n");
}

/*
 * Force immediate synchronization
 *
 * Called when a device is created/deleted locally to immediately
 * propagate changes to other hosts.
 */
int distfs_sync_now(struct distfs_context *ctx)
{
	if (!ctx)
		return -EINVAL;

	distfs_info("Forcing immediate device synchronization\n");

	/* Cancel pending work and sync immediately */
	if (sync_work) {
		cancel_delayed_work_sync(&sync_work->work);
		distfs_sync_devices(ctx);
		queue_delayed_work(system_wq, &sync_work->work, 30 * HZ);
	}

	return 0;
}

/*
 * Handle device creation notification from metadata server
 *
 * When metadata server notifies us of a new device (created on another host),
 * we create it locally so it appears on this host.
 */
int distfs_sync_handle_device_created(struct distfs_context *ctx,
				      const char *name, u64 size,
				      u32 chunk_size, u32 replicas,
				      u64 device_id)
{
	struct distfs_device *dev;

	distfs_info("Creating device from cluster notification: %s\n", name);

	/* Check if device already exists */
	dev = distfs_device_find_by_name(ctx->dev_mgr, name);
	if (dev) {
		distfs_dbg("Device %s already exists locally\n", name);
		return 0;
	}

	/* Create device locally */
	dev = distfs_device_create(ctx->dev_mgr, ctx->cluster,
				   name, size, chunk_size, replicas);
	if (IS_ERR(dev)) {
		distfs_err("Failed to create device %s: %ld\n",
			   name, PTR_ERR(dev));
		return PTR_ERR(dev);
	}

	/* Set device ID from metadata server */
	dev->device_id = device_id;

	distfs_info("Device %s now available on this host as %s\n",
		    name, dev->disk->disk_name);

	return 0;
}

/*
 * Handle device deletion notification from metadata server
 */
int distfs_sync_handle_device_deleted(struct distfs_context *ctx,
				      const char *name)
{
	struct distfs_device *dev;

	distfs_info("Deleting device from cluster notification: %s\n", name);

	dev = distfs_device_find_by_name(ctx->dev_mgr, name);
	if (!dev) {
		distfs_dbg("Device %s doesn't exist locally\n", name);
		return 0;
	}

	/* Destroy device locally */
	distfs_device_destroy(dev);

	distfs_info("Device %s removed from this host\n", name);

	return 0;
}
