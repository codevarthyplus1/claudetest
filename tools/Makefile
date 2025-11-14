# Makefile for DistFS-KVM userspace tools

CC := gcc
CFLAGS := -Wall -Wextra -O2 -std=gnu99
PREFIX := /usr/local

TARGETS := distfs-kvm distfs-kvmd

all: $(TARGETS)

distfs-kvm: distfs-kvm.c
	$(CC) $(CFLAGS) -o $@ $<

distfs-kvmd: distfs-kvmd.c
	$(CC) $(CFLAGS) -o $@ $<

install: $(TARGETS)
	install -D -m 0755 distfs-kvm $(PREFIX)/bin/distfs-kvm
	install -D -m 0755 distfs-kvmd $(PREFIX)/sbin/distfs-kvmd

clean:
	rm -f $(TARGETS) *.o

.PHONY: all install clean
