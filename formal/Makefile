RISCV_FORMAL ?= ../formal_tools/riscv-formal

.PHONY: all generate run clean

all: run

# genchecks.py expects to be run from riscv-formal/cores/<corename>/
# where basedir = ../../ resolves to the riscv-formal root.
# We stage our files into that layout via symlinks.
CORE_DIR := $(RISCV_FORMAL)/cores/rv32i_core
RTL_DIR  := $(CURDIR)/../rtl/core

generate:
	mkdir -p $(CORE_DIR)
	ln -sf $(CURDIR)/checks.cfg $(CORE_DIR)/checks.cfg
	ln -sf $(CURDIR)/wrapper.sv $(CORE_DIR)/wrapper.sv
	@# Symlink all RTL source files so Yosys can find them
	@for f in $(RTL_DIR)/*.sv; do \
		ln -sf "$$f" $(CORE_DIR)/$$(basename "$$f"); \
	done
	cd $(CORE_DIR) && python3 ../../checks/genchecks.py

run: generate
	$(MAKE) -C $(CORE_DIR)/checks -j$$(nproc)

clean:
	rm -rf $(RISCV_FORMAL)/cores/rv32i_core
