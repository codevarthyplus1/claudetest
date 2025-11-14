/*
 * chunk.c - DistFS-KVM chunk management
 *
 * Copyright (C) 2025 DistFS Contributors
 */

#include <linux/slab.h>
#include <linux/rbtree.h>
#include "distfs.h"

/*
 * Find chunk in device's chunk tree
 */
struct distfs_chunk *distfs_chunk_find(struct distfs_device *dev, u64 chunk_id)
{
	struct rb_node *node;
	struct distfs_chunk *chunk;

	spin_lock(&dev->chunks_lock);
	node = dev->chunks.rb_node;

	while (node) {
		chunk = rb_entry(node, struct distfs_chunk, node);

		if (chunk_id < chunk->chunk_id)
			node = node->rb_left;
		else if (chunk_id > chunk->chunk_id)
			node = node->rb_right;
		else {
			spin_unlock(&dev->chunks_lock);
			return chunk;
		}
	}

	spin_unlock(&dev->chunks_lock);
	return NULL;
}

/*
 * Insert chunk into device's chunk tree
 */
static void distfs_chunk_insert(struct distfs_device *dev,
				struct distfs_chunk *chunk)
{
	struct rb_node **new = &dev->chunks.rb_node, *parent = NULL;
	struct distfs_chunk *this;

	spin_lock(&dev->chunks_lock);

	while (*new) {
		this = rb_entry(*new, struct distfs_chunk, node);
		parent = *new;

		if (chunk->chunk_id < this->chunk_id)
			new = &((*new)->rb_left);
		else if (chunk->chunk_id > this->chunk_id)
			new = &((*new)->rb_right);
		else {
			/* Chunk already exists */
			spin_unlock(&dev->chunks_lock);
			return;
		}
	}

	rb_link_node(&chunk->node, parent, new);
	rb_insert_color(&chunk->node, &dev->chunks);

	spin_unlock(&dev->chunks_lock);
}

/*
 * Allocate and initialize a new chunk
 */
struct distfs_chunk *distfs_chunk_alloc(struct distfs_device *dev, u64 chunk_id)
{
	struct distfs_chunk *chunk;
	int ret;

	chunk = kzalloc(sizeof(*chunk), GFP_KERNEL);
	if (!chunk)
		return NULL;

	chunk->chunk_id = chunk_id;
	chunk->size = dev->chunk_size;
	chunk->num_replicas = 0;
	spin_lock_init(&chunk->lock);

	/* Get chunk locations from cluster */
	if (dev->cluster) {
		ret = distfs_chunk_get_locations(dev->cluster, dev->device_id,
						 chunk_id, chunk);
		if (ret < 0) {
			distfs_warn("Failed to get chunk locations: %d\n", ret);
			/* Continue with empty locations, will be populated later */
		}
	}

	/* Insert into device's chunk tree */
	distfs_chunk_insert(dev, chunk);

	distfs_dbg("Allocated chunk %llu for device %s\n",
		   chunk_id, dev->name);

	return chunk;
}

/*
 * Free a chunk
 */
void distfs_chunk_free(struct distfs_chunk *chunk)
{
	if (chunk)
		kfree(chunk);
}

/*
 * Get chunk replica locations from cluster
 * (Placeholder - actual implementation would use network.c)
 */
int distfs_chunk_get_locations(struct distfs_cluster *cluster,
			       u64 device_id, u64 chunk_id,
			       struct distfs_chunk *chunk)
{
	/* TODO: Query metadata server for chunk locations */
	/* For now, just mark as not having any replicas */
	chunk->num_replicas = 0;
	return 0;
}
