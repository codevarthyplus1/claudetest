/*
 * distfs-kvmd - DistFS-KVM cluster daemon
 *
 * Copyright (C) 2025 DistFS Contributors
 *
 * This daemon runs on cluster nodes to provide metadata or storage services.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <signal.h>

#define VERSION "1.0.0"

static volatile sig_atomic_t running = 1;

static void signal_handler(int sig)
{
	(void)sig;
	running = 0;
}

static void usage(const char *prog)
{
	printf("DistFS-KVM Cluster Daemon v%s\n\n", VERSION);
	printf("Usage: %s --role <role> [options]\n\n", prog);
	printf("Options:\n");
	printf("  --role ROLE          Node role: metadata or storage (required)\n");
	printf("  --bind ADDR:PORT     Bind address (default: 0.0.0.0:7001)\n");
	printf("  --metadata ADDR:PORT Metadata server address (for storage nodes)\n");
	printf("  --storage-path PATH  Storage path (for storage nodes)\n");
	printf("  --daemon             Run as daemon\n");
	printf("  -h, --help           Show this help\n");
	printf("\n");
	printf("Examples:\n");
	printf("  # Metadata server\n");
	printf("  %s --role metadata --bind 0.0.0.0:7001\n", prog);
	printf("\n");
	printf("  # Storage node\n");
	printf("  %s --role storage --metadata 192.168.1.10:7001 --storage-path /var/lib/distfs\n", prog);
	printf("\n");
}

int main(int argc, char **argv)
{
	char *role = NULL;
	char *bind_addr = "0.0.0.0:7001";
	char *metadata_addr = NULL;
	char *storage_path = "/var/lib/distfs-kvm";
	int daemon_mode = 0;
	int c;

	struct option long_opts[] = {
		{"role", required_argument, 0, 'r'},
		{"bind", required_argument, 0, 'b'},
		{"metadata", required_argument, 0, 'm'},
		{"storage-path", required_argument, 0, 's'},
		{"daemon", no_argument, &daemon_mode, 1},
		{"help", no_argument, 0, 'h'},
		{0, 0, 0, 0}
	};

	while ((c = getopt_long(argc, argv, "r:b:m:s:h", long_opts, NULL)) != -1) {
		switch (c) {
		case 'r':
			role = optarg;
			break;
		case 'b':
			bind_addr = optarg;
			break;
		case 'm':
			metadata_addr = optarg;
			break;
		case 's':
			storage_path = optarg;
			break;
		case 'h':
			usage(argv[0]);
			return 0;
		case 0:
			/* Flag set */
			break;
		default:
			usage(argv[0]);
			return 1;
		}
	}

	if (!role) {
		fprintf(stderr, "Error: --role is required\n\n");
		usage(argv[0]);
		return 1;
	}

	/* Setup signal handlers */
	signal(SIGINT, signal_handler);
	signal(SIGTERM, signal_handler);

	printf("DistFS-KVM Daemon v%s\n", VERSION);
	printf("Role: %s\n", role);

	if (strcmp(role, "metadata") == 0) {
		printf("Metadata server listening on: %s\n", bind_addr);
		printf("TODO: Implement metadata server\n");
	} else if (strcmp(role, "storage") == 0) {
		if (!metadata_addr) {
			fprintf(stderr, "Error: --metadata is required for storage role\n");
			return 1;
		}
		printf("Storage node configuration:\n");
		printf("  Metadata server: %s\n", metadata_addr);
		printf("  Storage path: %s\n", storage_path);
		printf("TODO: Implement storage node\n");
	} else {
		fprintf(stderr, "Error: Unknown role '%s'\n", role);
		return 1;
	}

	/* Main event loop (placeholder) */
	printf("\nDaemon running... (Press Ctrl+C to stop)\n");
	while (running) {
		sleep(1);
	}

	printf("\nShutting down...\n");
	return 0;
}
