/*
 * distfs.h - DistFS-KVM distributed block device driver for KVM
 *
 * Copyright (C) 2025 DistFS Contributors
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 */

#ifndef _DISTFS_KVM_H
#define _DISTFS_KVM_H

#include <linux/types.h>
#include <linux/spinlock.h>
#include <linux/mutex.h>
#include <linux/rbtree.h>
#include <linux/blkdev.h>
#include <linux/blk-mq.h>
#include <linux/genhd.h>
#include <linux/net.h>
#include <linux/in.h>
#include <linux/list.h>
#include <linux/workqueue.h>

/* Version information */
#define DISTFS_VERSION_MAJOR 1
#define DISTFS_VERSION_MINOR 0
#define DISTFS_VERSION_PATCH 0

/* Magic number for identification */
#define DISTFS_MAGIC 0x44495354  /* "DIST" */

/* Block device parameters */
#define DISTFS_MAX_DEVICES       256
#define DISTFS_MINORS_PER_DEVICE 16
#define DISTFS_SECTOR_SIZE       512
#define DISTFS_DEFAULT_QUEUE_DEPTH 128

/* Storage parameters */
#define DISTFS_DEFAULT_CHUNK_SIZE    (4 * 1024 * 1024)  /* 4MB */
#define DISTFS_MAX_CHUNK_SIZE        (64 * 1024 * 1024) /* 64MB */
#define DISTFS_DEFAULT_REPLICAS      2
#define DISTFS_MAX_REPLICAS          8
#define DISTFS_MAX_STORAGE_NODES     256

/* Network parameters */
#define DISTFS_METADATA_PORT         7001
#define DISTFS_STORAGE_PORT          7002
#define DISTFS_MAX_PACKET_SIZE       (128 * 1024)
#define DISTFS_NETWORK_TIMEOUT_MS    30000

/*
 * Protocol commands between client (this module) and cluster
 */
enum distfs_cmd {
	DISTFS_CMD_HELLO = 1,
	DISTFS_CMD_CREATE_DEVICE,
	DISTFS_CMD_DELETE_DEVICE,
	DISTFS_CMD_LIST_DEVICES,
	DISTFS_CMD_GET_DEVICE_INFO,
	DISTFS_CMD_READ_CHUNK,
	DISTFS_CMD_WRITE_CHUNK,
	DISTFS_CMD_GET_CHUNK_LOCATIONS,
	DISTFS_CMD_NODE_REGISTER,
	DISTFS_CMD_NODE_HEARTBEAT,
	DISTFS_CMD_LIST_NODES,
};

/*
 * Node states
 */
enum distfs_node_state {
	DISTFS_NODE_ONLINE = 1,
	DISTFS_NODE_OFFLINE,
	DISTFS_NODE_DEGRADED,
};

/*
 * Request/response structures
 */

/* Network packet header */
struct distfs_packet_hdr {
	__be16 version;			/* Protocol version */
	__be16 command;			/* Command code */
	__be32 length;			/* Payload length */
	__be64 transaction_id;		/* Transaction ID */
	__be32 flags;			/* Flags */
	__be32 checksum;		/* Header checksum */
} __packed;

/* Device creation request */
struct distfs_create_req {
	char name[64];			/* Device name */
	__be64 size;			/* Size in bytes */
	__be32 chunk_size;		/* Chunk size */
	__be32 replicas;		/* Number of replicas */
} __packed;

/* Device info response */
struct distfs_device_info {
	char name[64];			/* Device name */
	__be64 size;			/* Size in bytes */
	__be32 chunk_size;		/* Chunk size */
	__be32 replicas;		/* Number of replicas */
	__be64 device_id;		/* Unique device ID */
	__be32 num_chunks;		/* Number of chunks */
	__be32 flags;			/* Device flags */
} __packed;

/* Chunk location request */
struct distfs_chunk_loc_req {
	__be64 device_id;		/* Device ID */
	__be64 chunk_id;		/* Chunk ID */
} __packed;

/* Storage node info */
struct distfs_node_info {
	__be64 node_id;			/* Node ID */
	__be32 addr;			/* IPv4 address */
	__be16 port;			/* Port */
	__be16 state;			/* Node state */
	__be64 capacity;		/* Total capacity */
	__be64 used;			/* Used space */
} __packed;

/* Chunk read/write request */
struct distfs_chunk_io_req {
	__be64 device_id;		/* Device ID */
	__be64 chunk_id;		/* Chunk ID */
	__be32 offset;			/* Offset within chunk */
	__be32 length;			/* Length */
} __packed;

/*
 * In-memory structures
 */

/* Storage node representation */
struct distfs_node {
	struct list_head list;		/* Global node list */
	u64 node_id;			/* Unique node ID */
	u32 addr;			/* IPv4 address */
	u16 port;			/* Port */
	enum distfs_node_state state;	/* Node state */
	u64 capacity;			/* Total capacity */
	u64 used;			/* Used space */
	unsigned long last_seen;	/* Last heartbeat time */
	spinlock_t lock;		/* Node lock */
};

/* Chunk descriptor */
struct distfs_chunk {
	struct rb_node node;		/* RB-tree node */
	u64 chunk_id;			/* Chunk ID */
	u32 size;			/* Chunk size */
	struct distfs_node *replicas[DISTFS_MAX_REPLICAS];
	int num_replicas;		/* Number of replicas */
	spinlock_t lock;		/* Chunk lock */
};

/* I/O request wrapper */
struct distfs_io_req {
	struct request *rq;		/* Block layer request */
	struct distfs_device *dev;	/* Target device */
	struct work_struct work;	/* Work item */
	int error;			/* Error code */
	atomic_t ref;			/* Reference count */
};

/* Block device */
struct distfs_device {
	int minor;			/* Device minor number */
	char name[64];			/* Device name */
	u64 device_id;			/* Unique device ID */
	u64 size;			/* Device size in bytes */
	u32 chunk_size;			/* Chunk size */
	u32 replicas;			/* Replication factor */

	struct gendisk *disk;		/* Generic disk */
	struct request_queue *queue;	/* Request queue */
	struct blk_mq_tag_set tag_set;	/* Block MQ tag set */

	/* Chunk management */
	struct rb_root chunks;		/* Chunk tree */
	spinlock_t chunks_lock;		/* Chunk tree lock */
	u32 num_chunks;			/* Number of chunks */

	/* Statistics */
	atomic64_t reads;		/* Read requests */
	atomic64_t writes;		/* Write requests */
	atomic64_t read_bytes;		/* Bytes read */
	atomic64_t write_bytes;		/* Bytes written */
	atomic64_t errors;		/* Error count */

	struct distfs_cluster *cluster;	/* Cluster context */
	atomic_t open_count;		/* Open count */
	spinlock_t lock;		/* Device lock */
};

/* Device manager */
struct distfs_device_manager {
	struct mutex lock;		/* Manager lock */
	struct distfs_device *devices[DISTFS_MAX_DEVICES];
	int num_devices;		/* Number of devices */
	int major;			/* Block device major */
};

/* Cluster context */
struct distfs_cluster {
	struct socket *metadata_sock;	/* Metadata server socket */
	char metadata_addr[128];	/* Metadata server address */
	u16 metadata_port;		/* Metadata server port */

	/* Storage nodes */
	struct list_head nodes;		/* Storage node list */
	spinlock_t nodes_lock;		/* Node list lock */
	int num_nodes;			/* Number of nodes */

	/* Network I/O */
	struct workqueue_struct *io_wq;	/* I/O workqueue */
	atomic64_t transaction_id;	/* Transaction counter */

	/* Connection management */
	struct work_struct reconnect_work;
	struct delayed_work heartbeat_work;
	unsigned long last_connected;	/* Last connection time */

	struct mutex lock;		/* Cluster lock */
};

/* Global context */
struct distfs_context {
	struct distfs_device_manager *dev_mgr;
	struct distfs_cluster *cluster;
	struct proc_dir_entry *proc_dir;
};

/* Module parameters */
extern int distfs_debug;
extern int distfs_max_devices;
extern int distfs_chunk_size;
extern int distfs_max_replicas;
extern int distfs_network_timeout;

/* Debug macros */
#define distfs_dbg(fmt, ...) \
	do { \
		if (distfs_debug) \
			pr_info("distfs-kvm: " fmt, ##__VA_ARGS__); \
	} while (0)

#define distfs_err(fmt, ...) \
	pr_err("distfs-kvm: " fmt, ##__VA_ARGS__)

#define distfs_warn(fmt, ...) \
	pr_warn("distfs-kvm: " fmt, ##__VA_ARGS__)

#define distfs_info(fmt, ...) \
	pr_info("distfs-kvm: " fmt, ##__VA_ARGS__)

/* device.c */
struct distfs_device_manager *distfs_device_manager_init(void);
void distfs_device_manager_exit(struct distfs_device_manager *mgr);
struct distfs_device *distfs_device_create(struct distfs_device_manager *mgr,
					   struct distfs_cluster *cluster,
					   const char *name, u64 size,
					   u32 chunk_size, u32 replicas);
void distfs_device_destroy(struct distfs_device *dev);
struct distfs_device *distfs_device_find_by_name(
		struct distfs_device_manager *mgr, const char *name);
struct distfs_device *distfs_device_find_by_minor(
		struct distfs_device_manager *mgr, int minor);

/* blkdev.c - Block device operations */
int distfs_blkdev_init(struct distfs_device *dev);
void distfs_blkdev_cleanup(struct distfs_device *dev);
blk_status_t distfs_queue_rq(struct blk_mq_hw_ctx *hctx,
			     const struct blk_mq_queue_data *bd);
void distfs_complete_rq(struct request *rq);

/* chunk.c - Chunk management */
struct distfs_chunk *distfs_chunk_find(struct distfs_device *dev, u64 chunk_id);
struct distfs_chunk *distfs_chunk_alloc(struct distfs_device *dev, u64 chunk_id);
void distfs_chunk_free(struct distfs_chunk *chunk);
int distfs_chunk_get_locations(struct distfs_cluster *cluster,
			       u64 device_id, u64 chunk_id,
			       struct distfs_chunk *chunk);

/* io.c - I/O operations */
int distfs_do_io(struct distfs_device *dev, struct request *rq);
int distfs_read_chunk(struct distfs_device *dev, struct distfs_chunk *chunk,
		     void *buf, u32 offset, u32 length);
int distfs_write_chunk(struct distfs_device *dev, struct distfs_chunk *chunk,
		      const void *buf, u32 offset, u32 length);

/* network.c - Network operations */
struct distfs_cluster *distfs_cluster_init(const char *metadata_addr,
					   u16 metadata_port);
void distfs_cluster_exit(struct distfs_cluster *cluster);
int distfs_cluster_connect(struct distfs_cluster *cluster);
void distfs_cluster_disconnect(struct distfs_cluster *cluster);
int distfs_net_send(struct socket *sock, const void *buf, size_t len);
int distfs_net_recv(struct socket *sock, void *buf, size_t len);
int distfs_net_rpc(struct distfs_cluster *cluster, enum distfs_cmd cmd,
		  const void *req, size_t req_len,
		  void *resp, size_t resp_len);

/* proc.c - /proc interface */
int distfs_proc_init(struct distfs_context *ctx);
void distfs_proc_exit(struct distfs_context *ctx);

/* Utility functions */
static inline u64 distfs_offset_to_chunk_id(u64 offset, u32 chunk_size)
{
	return offset / chunk_size;
}

static inline u32 distfs_offset_in_chunk(u64 offset, u32 chunk_size)
{
	return offset % chunk_size;
}

static inline u64 distfs_chunk_to_offset(u64 chunk_id, u32 chunk_size)
{
	return chunk_id * chunk_size;
}

static inline sector_t distfs_bytes_to_sectors(u64 bytes)
{
	return bytes >> 9;  /* Divide by 512 */
}

static inline u64 distfs_sectors_to_bytes(sector_t sectors)
{
	return (u64)sectors << 9;  /* Multiply by 512 */
}

#endif /* _DISTFS_KVM_H */
