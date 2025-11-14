/*
 * distfs-kvm - DistFS-KVM management utility
 *
 * Copyright (C) 2025 DistFS Contributors
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>

#define VERSION "1.0.0"

static void usage(const char *prog)
{
	printf("DistFS-KVM Management Utility v%s\n\n", VERSION);
	printf("Usage: %s <command> [options]\n\n", prog);
	printf("Commands:\n");
	printf("  create    Create a new block device\n");
	printf("  delete    Delete a block device\n");
	printf("  list      List all devices\n");
	printf("  info      Show device information\n");
	printf("  stats     Show device statistics\n");
	printf("  health    Check cluster health\n");
	printf("  nodes     List storage nodes\n");
	printf("\n");
	printf("Options for 'create':\n");
	printf("  -n, --name NAME      Device name (required)\n");
	printf("  -s, --size SIZE      Device size (e.g., 10G, 500M)\n");
	printf("  -r, --replicas N     Number of replicas (default: 2)\n");
	printf("  -c, --chunk-size SIZE Chunk size (default: 4M)\n");
	printf("\n");
	printf("Examples:\n");
	printf("  %s create -n vm1-disk -s 20G -r 3\n", prog);
	printf("  %s list\n", prog);
	printf("  %s info -n vm1-disk\n", prog);
	printf("  %s stats\n", prog);
	printf("\n");
}

static int cmd_create(int argc, char **argv)
{
	char *name = NULL, *size = NULL;
	int replicas = 2;
	char *chunk_size = "4M";
	int c;

	struct option long_opts[] = {
		{"name", required_argument, 0, 'n'},
		{"size", required_argument, 0, 's'},
		{"replicas", required_argument, 0, 'r'},
		{"chunk-size", required_argument, 0, 'c'},
		{0, 0, 0, 0}
	};

	while ((c = getopt_long(argc, argv, "n:s:r:c:", long_opts, NULL)) != -1) {
		switch (c) {
		case 'n':
			name = optarg;
			break;
		case 's':
			size = optarg;
			break;
		case 'r':
			replicas = atoi(optarg);
			break;
		case 'c':
			chunk_size = optarg;
			break;
		default:
			return 1;
		}
	}

	if (!name || !size) {
		fprintf(stderr, "Error: name and size are required\n");
		return 1;
	}

	/* TODO: Implement actual device creation via ioctl or netlink */
	printf("Creating device '%s' (size=%s, replicas=%d, chunk-size=%s)\n",
	       name, size, replicas, chunk_size);
	printf("TODO: Implement device creation\n");

	return 0;
}

static int cmd_list(void)
{
	FILE *f;
	char line[256];

	printf("DistFS-KVM Block Devices:\n\n");

	/* Read from /proc/distfs-kvm/stats */
	f = fopen("/proc/distfs-kvm/stats", "r");
	if (!f) {
		fprintf(stderr, "Error: Unable to read /proc/distfs-kvm/stats\n");
		fprintf(stderr, "Is the distfs-kvm module loaded?\n");
		return 1;
	}

	while (fgets(line, sizeof(line), f)) {
		printf("%s", line);
	}

	fclose(f);
	return 0;
}

static int cmd_stats(void)
{
	return cmd_list();  /* Same as list for now */
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		usage(argv[0]);
		return 1;
	}

	const char *cmd = argv[1];

	if (strcmp(cmd, "create") == 0) {
		return cmd_create(argc - 1, argv + 1);
	} else if (strcmp(cmd, "list") == 0) {
		return cmd_list();
	} else if (strcmp(cmd, "stats") == 0) {
		return cmd_stats();
	} else if (strcmp(cmd, "help") == 0 || strcmp(cmd, "--help") == 0) {
		usage(argv[0]);
		return 0;
	} else {
		fprintf(stderr, "Unknown command: %s\n", cmd);
		usage(argv[0]);
		return 1;
	}
}
