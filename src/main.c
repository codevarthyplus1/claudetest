/*
 * main.c - DistFS-KVM kernel module initialization
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
#include <linux/init.h>
#include <linux/slab.h>
#include "distfs.h"

/* Module information */
MODULE_AUTHOR("DistFS Contributors");
MODULE_DESCRIPTION("DistFS-KVM: Distributed block storage for KVM");
MODULE_LICENSE("GPL");
MODULE_VERSION("1.0.0");

/* Module parameters */
int distfs_debug = 0;
module_param(distfs_debug, int, 0644);
MODULE_PARM_DESC(distfs_debug, "Enable debug logging (0=off, 1=on)");

int distfs_max_devices = DISTFS_MAX_DEVICES;
module_param(distfs_max_devices, int, 0444);
MODULE_PARM_DESC(distfs_max_devices, "Maximum number of devices");

int distfs_chunk_size = DISTFS_DEFAULT_CHUNK_SIZE;
module_param(distfs_chunk_size, int, 0444);
MODULE_PARM_DESC(distfs_chunk_size, "Default chunk size in bytes");

int distfs_max_replicas = DISTFS_MAX_REPLICAS;
module_param(distfs_max_replicas, int, 0444);
MODULE_PARM_DESC(distfs_max_replicas, "Maximum number of replicas");

int distfs_network_timeout = DISTFS_NETWORK_TIMEOUT_MS;
module_param(distfs_network_timeout, int, 0644);
MODULE_PARM_DESC(distfs_network_timeout, "Network timeout in milliseconds");

static char *metadata_server = NULL;
module_param(metadata_server, charp, 0444);
MODULE_PARM_DESC(metadata_server, "Metadata server address (host:port)");

/* Global context */
static struct distfs_context *distfs_ctx;

/*
 * Parse metadata server address from string
 */
static int distfs_parse_server_addr(const char *addr_str, char *host, u16 *port)
{
	char *colon;
	int len;

	if (!addr_str || !host || !port)
		return -EINVAL;

	colon = strchr(addr_str, ':');
	if (!colon) {
		/* No port specified, use default */
		strncpy(host, addr_str, 127);
		host[127] = '\0';
		*port = DISTFS_METADATA_PORT;
		return 0;
	}

	len = colon - addr_str;
	if (len >= 127)
		return -EINVAL;

	memcpy(host, addr_str, len);
	host[len] = '\0';

	if (kstrtou16(colon + 1, 10, port) < 0)
		return -EINVAL;

	return 0;
}

/*
 * Module initialization
 */
static int __init distfs_init(void)
{
	char host[128];
	u16 port;
	int ret;

	distfs_info("DistFS-KVM v%d.%d.%d initializing\n",
		    DISTFS_VERSION_MAJOR, DISTFS_VERSION_MINOR,
		    DISTFS_VERSION_PATCH);

	/* Validate parameters */
	if (distfs_chunk_size < 4096 || distfs_chunk_size > DISTFS_MAX_CHUNK_SIZE) {
		distfs_err("Invalid chunk size: %d\n", distfs_chunk_size);
		return -EINVAL;
	}

	if (distfs_max_devices < 1 || distfs_max_devices > DISTFS_MAX_DEVICES) {
		distfs_err("Invalid max_devices: %d\n", distfs_max_devices);
		return -EINVAL;
	}

	/* Allocate global context */
	distfs_ctx = kzalloc(sizeof(*distfs_ctx), GFP_KERNEL);
	if (!distfs_ctx) {
		distfs_err("Failed to allocate context\n");
		return -ENOMEM;
	}

	/* Initialize device manager */
	distfs_ctx->dev_mgr = distfs_device_manager_init();
	if (!distfs_ctx->dev_mgr) {
		distfs_err("Failed to initialize device manager\n");
		ret = -ENOMEM;
		goto err_free_ctx;
	}

	/* Initialize cluster connection if metadata server specified */
	if (metadata_server) {
		ret = distfs_parse_server_addr(metadata_server, host, &port);
		if (ret < 0) {
			distfs_err("Invalid metadata server address: %s\n",
				   metadata_server);
			goto err_dev_mgr;
		}

		distfs_ctx->cluster = distfs_cluster_init(host, port);
		if (!distfs_ctx->cluster) {
			distfs_err("Failed to initialize cluster connection\n");
			ret = -ENOMEM;
			goto err_dev_mgr;
		}

		/* Connect to cluster */
		ret = distfs_cluster_connect(distfs_ctx->cluster);
		if (ret < 0) {
			distfs_warn("Failed to connect to cluster: %d\n", ret);
			distfs_warn("Cluster features will be unavailable\n");
			/* Don't fail module load, allow manual connection later */
		} else {
			distfs_info("Connected to metadata server: %s:%u\n",
				    host, port);
		}
	}

	/* Initialize /proc interface */
	ret = distfs_proc_init(distfs_ctx);
	if (ret < 0) {
		distfs_warn("Failed to create /proc entries: %d\n", ret);
		/* Continue anyway, /proc is not critical */
	}

	/* Initialize device synchronization (multi-host support) */
	if (distfs_ctx->cluster) {
		ret = distfs_sync_init(distfs_ctx);
		if (ret < 0) {
			distfs_warn("Failed to initialize device sync: %d\n", ret);
			/* Continue anyway, sync not critical for basic operation */
		} else {
			distfs_info("Device synchronization enabled (multi-host mode)\n");
		}
	}

	distfs_info("DistFS-KVM initialized successfully\n");
	distfs_info("  Block device major: %d\n", distfs_ctx->dev_mgr->major);
	distfs_info("  Max devices: %d\n", distfs_max_devices);
	distfs_info("  Chunk size: %d bytes\n", distfs_chunk_size);
	distfs_info("  Max replicas: %d\n", distfs_max_replicas);
	if (metadata_server)
		distfs_info("  Multi-host mode: ENABLED (metadata: %s)\n", metadata_server);
	else
		distfs_info("  Multi-host mode: DISABLED (standalone)\n");

	return 0;

err_dev_mgr:
	distfs_device_manager_exit(distfs_ctx->dev_mgr);
err_free_ctx:
	kfree(distfs_ctx);
	return ret;
}

/*
 * Module cleanup
 */
static void __exit distfs_exit(void)
{
	distfs_info("DistFS-KVM shutting down\n");

	/* Stop device synchronization */
	distfs_sync_exit();

	/* Remove /proc entries */
	if (distfs_ctx->proc_dir)
		distfs_proc_exit(distfs_ctx);

	/* Disconnect from cluster */
	if (distfs_ctx->cluster) {
		distfs_cluster_disconnect(distfs_ctx->cluster);
		distfs_cluster_exit(distfs_ctx->cluster);
	}

	/* Cleanup all devices */
	if (distfs_ctx->dev_mgr)
		distfs_device_manager_exit(distfs_ctx->dev_mgr);

	/* Free context */
	kfree(distfs_ctx);

	distfs_info("DistFS-KVM unloaded\n");
}

module_init(distfs_init);
module_exit(distfs_exit);

/* Export symbols for other modules (if needed) */
EXPORT_SYMBOL_GPL(distfs_device_create);
EXPORT_SYMBOL_GPL(distfs_device_destroy);
EXPORT_SYMBOL_GPL(distfs_device_find_by_name);
