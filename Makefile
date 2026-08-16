# =============================================================================
# Top-level entry points. Everything the CI runs is reachable from here, and
# nothing in CI is a command that only exists inside a YAML file. If you can't
# reproduce a CI failure with a single `make` target locally, that's a bug in
# this Makefile, not in CI.
# =============================================================================

.PHONY: help lint lint-top test unit arch random formal regress clean

help:
	@echo "Targets:"
	@echo "  make lint      Verilator lint on all RTL (must be clean, always)"
	@echo "  make unit      cocotb block-level tests (ALU, regfile, ...)"
	@echo "  make arch      RISCOF architectural compliance suite"
	@echo "  make random    riscv-dv random regression + Spike lockstep"
	@echo "  make formal    riscv-formal bounded model checking"
	@echo "  make regress   lint + unit + arch (the CI gate)"
	@echo "  make asm       build asm tests, run on spike and RTL"
	@echo "  make clean     remove all build artefacts"

# -----------------------------------------------------------------------------
# Lint. Runs on every commit. A lint warning is a bug you haven't found yet:
# Verilator's WIDTH and CASEINCOMPLETE warnings in particular catch real RTL
# defects, so this is -Wall.
#
# THE ONLY PERMITTED WAIVER is MULTITOP, and only until rtl/core/core.sv exists.
# Linting a directory of standalone modules legitimately has several "top"
# modules; it is a statement about how we invoked the linter, not about the RTL.
# The moment the core top exists, switch this to `--top-module core` and delete
# the waiver -- see the lint-top target below. Any OTHER waiver you are tempted
# to add is a bug you should fix instead.
# -----------------------------------------------------------------------------
RTL_SRCS := rtl/core/rv32_pkg.sv \
            $(filter-out rtl/core/rv32_pkg.sv rtl/core/all_rtl.sv,$(wildcard rtl/core/*.sv))

lint:
	verilator --lint-only -Wall -Irtl/core --top-module core $(RTL_SRCS)

unit:
	$(MAKE) -C tb/cocotb test

arch:
	./scripts/run_arch_tests.sh

random:
	./scripts/run_random_regression.sh

coverage:
	python3 scripts/coverage.py build/riscv_dv_out

formal:
	$(MAKE) -C formal all

regress: lint unit arch coverage

ASM_SRCS := $(wildcard tests/asm/*.S)
ASM_ELFS := $(patsubst tests/asm/%.S,build/%.elf,$(ASM_SRCS))

build/%.elf: tests/asm/%.S sw/link.ld sw/crt0.S
	@mkdir -p build
	riscv-none-elf-gcc -march=rv32i -mabi=ilp32 -nostdlib -nostartfiles -T sw/link.ld sw/crt0.S $< -o $@

.PHONY: asm
asm: $(ASM_ELFS)
	@for elf in $(ASM_ELFS); do \
		echo "Running spike on $$elf"; \
		spike --isa=rv32i $$elf || exit 1; \
		echo "Running soc_top sim on $$elf"; \
		TESTCASE_ELF=$$(realpath $$elf) $(MAKE) -C tb/cocotb soc_top || exit 1; \
	done

.PHONY: cosim
cosim: $(ASM_ELFS)
	@for elf in $(ASM_ELFS); do \
		echo "Running cosim on $$elf"; \
		TESTCASE_ELF=$$(realpath $$elf) $(MAKE) -C tb/cocotb soc_top PLUSARGS="+rtl_log=$$(realpath $${elf%.elf}.rtl.log)" || exit 1; \
		python3 tb/lockstep/spike_compare.py --elf $$elf --rtl-log $${elf%.elf}.rtl.log || exit 1; \
	done

clean:
	$(MAKE) -C tb/cocotb clean
	rm -rf build riscof_work sim_build formal/checks
	find . -name '__pycache__' -type d -exec rm -rf {} +
