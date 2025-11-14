/*
 * device.c - DistFS-KVM device management
 *
 * Copyright (C) 2025 DistFS Contributors
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/slab.h>
#include <linux/blkdev.h>
#include <linux/genhd.h>
#include <linux/idr.h>
#include "distfs.h"

/* IDR for managing device minors */
static DEFINE_IDA(distfs_minor_ida);

/*
 * Initialize device manager
 */
struct distfs_device_manager *distfs_device_manager_init(void)
{
	struct distfs_device_manager *mgr;
	int ret;

	mgr = kzalloc(sizeof(*mgr), GFP_KERNEL);
	if (!mgr)
		return NULL;

	mutex_init(&mgr->lock);
	mgr->num_devices = 0;

	/* Register block device major */
	ret = register_blkdev(0, "distfs");
	if (ret < 0) {
		distfs_err("Failed to register block device: %d\n", ret);
		kfree(mgr);
		return NULL;
	}

	mgr->major = ret;
	distfs_dbg("Registered block device major: %d\n", mgr->major);

	return mgr;
}

/*
 * Cleanup device manager
 */
void distfs_device_manager_exit(struct distfs_device_manager *mgr)
{
	int i;

	if (!mgr)
		return;

	/* Destroy all devices */
	mutex_lock(&mgr->lock);
	for (i = 0; i < DISTFS_MAX_DEVICES; i++) {
		if (mgr->devices[i]) {
			distfs_device_destroy(mgr->devices[i]);
			mgr->devices[i] = NULL;
		}
	}
	mutex_unlock(&mgr->lock);

	/* Unregister block device */
	if (mgr->major > 0)
		unregister_blkdev(mgr->major, "distfs");

	kfree(mgr);
}

/*
 * Allocate a minor number
 */
static int distfs_alloc_minor(void)
{
	return ida_simple_get(&distfs_minor_ida, 0, 1 << MINORBITS, GFP_KERNEL);
}

/*
 * Free a minor number
 */
static void distfs_free_minor(int minor)
{
	ida_simple_remove(&distfs_minor_ida, minor);
}

/*
 * Create a new block device
 */
struct distfs_device *distfs_device_create(struct distfs_device_manager *mgr,
					   struct distfs_cluster *cluster,
					   const char *name, u64 size,
					   u32 chunk_size, u32 replicas)
{
	struct distfs_device *dev;
	int minor, ret, i;

	if (!mgr || !name || size == 0)
		return ERR_PTR(-EINVAL);

	if (chunk_size == 0)
		chunk_size = distfs_chunk_size;
	if (replicas == 0)
		replicas = DISTFS_DEFAULT_REPLICAS;

	/* Validate parameters */
	if (chunk_size < 4096 || chunk_size > DISTFS_MAX_CHUNK_SIZE)
		return ERR_PTR(-EINVAL);
	if (replicas > distfs_max_replicas)
		return ERR_PTR(-EINVAL);

	/* Check if device already exists */
	if (distfs_device_find_by_name(mgr, name))
		return ERR_PTR(-EEXIST);

	/* Allocate minor number */
	minor = distfs_alloc_minor();
	if (minor < 0)
		return ERR_PTR(minor);

	/* Allocate device structure */
	dev = kzalloc(sizeof(*dev), GFP_KERNEL);
	if (!dev) {
		distfs_free_minor(minor);
		return ERR_PTR(-ENOMEM);
	}

	/* Initialize device */
	dev->minor = minor;
	strncpy(dev->name, name, sizeof(dev->name) - 1);
	dev->size = size;
	dev->chunk_size = chunk_size;
	dev->replicas = replicas;
	dev->num_chunks = (size + chunk_size - 1) / chunk_size;
	dev->cluster = cluster;
	dev->chunks = RB_ROOT;

	spin_lock_init(&dev->lock);
	spin_lock_init(&dev->chunks_lock);
	atomic_set(&dev->open_count, 0);

	/* Initialize statistics */
	atomic64_set(&dev->reads, 0);
	atomic64_set(&dev->writes, 0);
	atomic64_set(&dev->read_bytes, 0);
	atomic64_set(&dev->write_bytes, 0);
	atomic64_set(&dev->errors, 0);

	/* Initialize block device */
	ret = distfs_blkdev_init(dev);
	if (ret < 0) {
		distfs_err("Failed to initialize block device: %d\n", ret);
		goto err_free_dev;
	}

	/* Set gendisk properties */
	snprintf(dev->disk->disk_name, DISK_NAME_LEN, "distfs%d", minor);
	set_capacity(dev->disk, distfs_bytes_to_sectors(size));
	dev->disk->major = mgr->major;
	dev->disk->first_minor = minor;
	dev->disk->minors = DISTFS_MINORS_PER_DEVICE;
	dev->disk->fops = NULL;  /* Set in blkdev.c */
	dev->disk->private_data = dev;

	/* Add to device manager */
	mutex_lock(&mgr->lock);
	for (i = 0; i < DISTFS_MAX_DEVICES; i++) {
		if (!mgr->devices[i]) {
			mgr->devices[i] = dev;
			mgr->num_devices++;
			break;
		}
	}
	mutex_unlock(&mgr->lock);

	if (i >= DISTFS_MAX_DEVICES) {
		distfs_err("Too many devices\n");
		ret = -ENOSPC;
		goto err_cleanup_blkdev;
	}

	/* Add disk to system */
	add_disk(dev->disk);

	distfs_info("Created device %s (%llu bytes, %u chunks, %u replicas) at /dev/%s\n",
		    name, size, dev->num_chunks, replicas, dev->disk->disk_name);

	return dev;

err_cleanup_blkdev:
	distfs_blkdev_cleanup(dev);
err_free_dev:
	distfs_free_minor(minor);
	kfree(dev);
	return ERR_PTR(ret);
}

/*
 * Destroy a block device
 */
void distfs_device_destroy(struct distfs_device *dev)
{
	if (!dev)
		return;

	distfs_info("Destroying device %s\n", dev->name);

	/* Remove from system */
	if (dev->disk) {
		del_gendisk(dev->disk);
		put_disk(dev->disk);
	}

	/* Cleanup block device */
	distfs_blkdev_cleanup(dev);

	/* Free minor */
	distfs_free_minor(dev->minor);

	/* Free device */
	kfree(dev);
}

/*
 * Find device by name
 */
struct distfs_device *distfs_device_find_by_name(
		struct distfs_device_manager *mgr, const char *name)
{
	struct distfs_device *dev = NULL;
	int i;

	if (!mgr || !name)
		return NULL;

	mutex_lock(&mgr->lock);
	for (i = 0; i < DISTFS_MAX_DEVICES; i++) {
		if (mgr->devices[i] &&
		    strcmp(mgr->devices[i]->name, name) == 0) {
			dev = mgr->devices[i];
			break;
		}
	}
	mutex_unlock(&mgr->lock);

	return dev;
}

/*
 * Find device by minor number
 */
struct distfs_device *distfs_device_find_by_minor(
		struct distfs_device_manager *mgr, int minor)
{
	struct distfs_device *dev = NULL;
	int i;

	if (!mgr || minor < 0)
		return NULL;

	mutex_lock(&mgr->lock);
	for (i = 0; i < DISTFS_MAX_DEVICES; i++) {
		if (mgr->devices[i] && mgr->devices[i]->minor == minor) {
			dev = mgr->devices[i];
			break;
		}
	}
	mutex_unlock(&mgr->lock);

	return dev;
}
