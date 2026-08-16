RISCV_FORMAL ?= ../formal_tools/riscv-formal

.PHONY: all generate run clean

all: run

generate:
	python3 $(RISCV_FORMAL)/checks/genchecks.py

run: generate
	$(MAKE) -C checks -j$$(nproc)

clean:
	rm -rf checks
