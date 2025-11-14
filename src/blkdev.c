/*
 * blkdev.c - DistFS-KVM block device operations using blk-mq
 *
 * Copyright (C) 2025 DistFS Contributors
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 */

#include <linux/module.h>
#include <linux/blkdev.h>
#include <linux/blk-mq.h>
#include <linux/bio.h>
#include "distfs.h"

/* Block device file operations */
static int distfs_open(struct block_device *bdev, fmode_t mode)
{
	struct distfs_device *dev = bdev->bd_disk->private_data;

	atomic_inc(&dev->open_count);
	distfs_dbg("Device %s opened (count=%d)\n",
		   dev->name, atomic_read(&dev->open_count));

	return 0;
}

static void distfs_release(struct gendisk *disk, fmode_t mode)
{
	struct distfs_device *dev = disk->private_data;

	atomic_dec(&dev->open_count);
	distfs_dbg("Device %s released (count=%d)\n",
		   dev->name, atomic_read(&dev->open_count));
}

static int distfs_ioctl(struct block_device *bdev, fmode_t mode,
		       unsigned int cmd, unsigned long arg)
{
	/* TODO: Implement device-specific ioctls */
	return -ENOTTY;
}

static const struct block_device_operations distfs_fops = {
	.owner		= THIS_MODULE,
	.open		= distfs_open,
	.release	= distfs_release,
	.ioctl		= distfs_ioctl,
};

/*
 * Process a single I/O request
 */
static void distfs_process_bio(struct distfs_device *dev, struct bio *bio)
{
	struct bio_vec bvec;
	struct bvec_iter iter;
	sector_t sector = bio->bi_iter.bi_sector;
	u64 offset = distfs_sectors_to_bytes(sector);
	int ret = 0;

	distfs_dbg("Processing %s request: sector=%llu, size=%u\n",
		   bio_op(bio) == REQ_OP_READ ? "read" : "write",
		   (unsigned long long)sector, bio->bi_iter.bi_size);

	bio_for_each_segment(bvec, bio, iter) {
		void *buffer = kmap_atomic(bvec.bv_page);
		void *data = buffer + bvec.bv_offset;
		u32 len = bvec.bv_len;
		u64 chunk_id = distfs_offset_to_chunk_id(offset, dev->chunk_size);
		u32 chunk_offset = distfs_offset_in_chunk(offset, dev->chunk_size);
		struct distfs_chunk *chunk;

		/* Find or allocate chunk */
		chunk = distfs_chunk_find(dev, chunk_id);
		if (!chunk) {
			chunk = distfs_chunk_alloc(dev, chunk_id);
			if (!chunk) {
				ret = -ENOMEM;
				kunmap_atomic(buffer);
				break;
			}
		}

		/* Perform I/O */
		if (bio_op(bio) == REQ_OP_READ) {
			ret = distfs_read_chunk(dev, chunk, data, chunk_offset, len);
			atomic64_add(len, &dev->read_bytes);
		} else {
			ret = distfs_write_chunk(dev, chunk, data, chunk_offset, len);
			atomic64_add(len, &dev->write_bytes);
		}

		kunmap_atomic(buffer);

		if (ret < 0) {
			distfs_err("I/O error on device %s: %d\n",
				   dev->name, ret);
			atomic64_inc(&dev->errors);
			break;
		}

		offset += len;
	}

	bio->bi_status = ret < 0 ? BLK_STS_IOERR : BLK_STS_OK;
	bio_endio(bio);
}

/*
 * blk-mq queue_rq callback
 */
blk_status_t distfs_queue_rq(struct blk_mq_hw_ctx *hctx,
			     const struct blk_mq_queue_data *bd)
{
	struct request *rq = bd->rq;
	struct distfs_device *dev = rq->q->queuedata;
	struct bio *bio;

	/* Start request processing */
	blk_mq_start_request(rq);

	/* Update statistics */
	if (rq_data_dir(rq) == READ)
		atomic64_inc(&dev->reads);
	else
		atomic64_inc(&dev->writes);

	/* Process all bios in the request */
	__rq_for_each_bio(bio, rq) {
		distfs_process_bio(dev, bio);
	}

	/* Complete request */
	blk_mq_end_request(rq, BLK_STS_OK);

	return BLK_STS_OK;
}

/*
 * blk-mq operations
 */
static const struct blk_mq_ops distfs_mq_ops = {
	.queue_rq	= distfs_queue_rq,
};

/*
 * Initialize block device
 */
int distfs_blkdev_init(struct distfs_device *dev)
{
	int ret;

	/* Setup blk-mq tag set */
	memset(&dev->tag_set, 0, sizeof(dev->tag_set));
	dev->tag_set.ops = &distfs_mq_ops;
	dev->tag_set.nr_hw_queues = 1;
	dev->tag_set.queue_depth = DISTFS_DEFAULT_QUEUE_DEPTH;
	dev->tag_set.numa_node = NUMA_NO_NODE;
	dev->tag_set.cmd_size = 0;
	dev->tag_set.flags = BLK_MQ_F_SHOULD_MERGE;
	dev->tag_set.driver_data = dev;

	ret = blk_mq_alloc_tag_set(&dev->tag_set);
	if (ret) {
		distfs_err("Failed to allocate tag set: %d\n", ret);
		return ret;
	}

	/* Allocate disk */
	dev->disk = blk_mq_alloc_disk(&dev->tag_set, dev);
	if (IS_ERR(dev->disk)) {
		ret = PTR_ERR(dev->disk);
		distfs_err("Failed to allocate disk: %d\n", ret);
		goto err_free_tag_set;
	}

	dev->queue = dev->disk->queue;
	dev->disk->fops = &distfs_fops;

	/* Set queue properties */
	blk_queue_logical_block_size(dev->queue, DISTFS_SECTOR_SIZE);
	blk_queue_physical_block_size(dev->queue, DISTFS_SECTOR_SIZE);
	blk_queue_max_hw_sectors(dev->queue, dev->chunk_size >> 9);
	blk_queue_io_opt(dev->queue, dev->chunk_size);

	/* Set queue data */
	dev->queue->queuedata = dev;

	return 0;

err_free_tag_set:
	blk_mq_free_tag_set(&dev->tag_set);
	return ret;
}

/*
 * Cleanup block device
 */
void distfs_blkdev_cleanup(struct distfs_device *dev)
{
	if (!dev)
		return;

	if (dev->tag_set.tags)
		blk_mq_free_tag_set(&dev->tag_set);
}
