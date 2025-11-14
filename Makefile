# Makefile for DistFS-KVM kernel module and tools

# Kernel module name
MODULE_NAME := distfs-kvm
obj-m := $(MODULE_NAME).o

# Source files for the kernel module
$(MODULE_NAME)-objs := src/main.o \
                       src/device.o \
                       src/blkdev.o \
                       src/chunk.o \
                       src/io.o \
                       src/network.o \
                       src/proc.o \
                       src/sync.o

# Kernel build directory
KERNEL_DIR ?= /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

# Compiler flags
ccflags-y := -I$(PWD)/src

# Debug build
ifdef DEBUG
ccflags-y += -DDEBUG -g
endif

# Default target
all: module tools

# Build kernel module
module:
	$(MAKE) -C $(KERNEL_DIR) M=$(PWD) modules

# Build userspace tools
tools:
	$(MAKE) -C tools

# Install kernel module
install: module
	$(MAKE) -C $(KERNEL_DIR) M=$(PWD) modules_install
	depmod -a

# Install tools
install-tools: tools
	$(MAKE) -C tools install

# Clean build artifacts
clean:
	$(MAKE) -C $(KERNEL_DIR) M=$(PWD) clean
	$(MAKE) -C tools clean
	rm -f Module.symvers Module.markers modules.order

# Load module
load:
	sudo insmod $(MODULE_NAME).ko

# Unload module
unload:
	sudo rmmod $(MODULE_NAME) || true

# Reload module
reload: unload load

# Show module info
modinfo:
	modinfo $(MODULE_NAME).ko

# Check coding style
checkpatch:
	$(KERNEL_DIR)/scripts/checkpatch.pl --no-tree -f src/*.c src/*.h

# Test module
test: module
	sudo dmesg -C
	sudo insmod $(MODULE_NAME).ko debug=1
	dmesg | tail -20
	lsmod | grep $(MODULE_NAME)
	cat /proc/distfs-kvm/stats || true
	sudo rmmod $(MODULE_NAME)

# Show help
help:
	@echo "DistFS-KVM Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all          - Build kernel module and tools (default)"
	@echo "  module       - Build only kernel module"
	@echo "  tools        - Build only userspace tools"
	@echo "  install      - Install kernel module"
	@echo "  install-tools - Install userspace tools"
	@echo "  clean        - Remove build artifacts"
	@echo "  load         - Load kernel module"
	@echo "  unload       - Unload kernel module"
	@echo "  reload       - Reload kernel module"
	@echo "  modinfo      - Show module information"
	@echo "  checkpatch   - Check coding style"
	@echo "  test         - Build and test module loading"
	@echo ""
	@echo "Options:"
	@echo "  DEBUG=1      - Build with debug symbols and logging"
	@echo "  KERNEL_DIR=  - Specify kernel build directory"

.PHONY: all module tools install install-tools clean load unload reload modinfo checkpatch test help
