# -----------------------------------------------------------------------------
# cocotb + Verilator test runner.
#
#   make alu             run the ALU tests
#   make regfile         run the register file tests
#   make all             run everything
#   make WAVES=1 alu     same, but dump dump.vcd for GTKWave/Surfer
#
# Verilator is the simulator because it is free, fast, and installs from a
# package manager. Nothing here needs a licence server.
#
# NOTE ON SIM_BUILD: each DUT gets its OWN build directory. cocotb caches the
# compiled Verilator model in $(SIM_BUILD), and if two DUTs share one directory
# the second target silently reuses the first one's binary and dies with
# "Can not find root handle". This is a real half-hour bug -- do not remove the
# per-toplevel SIM_BUILD below.
# -----------------------------------------------------------------------------

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog
RTL_DIR       := $(realpath ../../rtl/core)

EXTRA_ARGS += --trace --trace-structs -Wall -Wno-fatal
EXTRA_ARGS += -I$(RTL_DIR)

# Target is called `test`, NOT `all`: cocotb's Makefile.sim already defines an
# `all` target, and make would merge the prerequisites so that `make all` also
# tries to run a third, unconfigured simulation.
.PHONY: test alu regfile immgen decoder branch_unit imem dmem soc_top clean

test: alu regfile immgen decoder branch_unit imem dmem

alu:
	$(MAKE) sim TOPLEVEL=alu MODULE=test_alu SIM_BUILD=sim_build/alu \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/alu.sv"

regfile:
	$(MAKE) sim TOPLEVEL=regfile MODULE=test_regfile SIM_BUILD=sim_build/regfile \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/regfile.sv"

immgen:
	$(MAKE) sim TOPLEVEL=immgen MODULE=test_immgen SIM_BUILD=sim_build/immgen \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/immgen.sv"

decoder:
	$(MAKE) sim TOPLEVEL=decoder MODULE=test_decoder SIM_BUILD=sim_build/decoder \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/decoder.sv"

branch_unit:
	$(MAKE) sim TOPLEVEL=branch_unit MODULE=test_branch_unit SIM_BUILD=sim_build/branch_unit \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/branch_unit.sv"

imem:
	$(MAKE) sim TOPLEVEL=imem MODULE=test_imem SIM_BUILD=sim_build/imem \
		VERILOG_SOURCES="$(RTL_DIR)/../soc/imem.sv"

dmem:
	$(MAKE) sim TOPLEVEL=dmem MODULE=test_dmem SIM_BUILD=sim_build/dmem \
		VERILOG_SOURCES="$(RTL_DIR)/../soc/dmem.sv"

SOC_TOP_SIM_BUILD ?= sim_build/soc_top
soc_top:
	$(MAKE) sim TOPLEVEL=soc_top MODULE=test_soc_top SIM_BUILD=$(SOC_TOP_SIM_BUILD) \
		VERILOG_SOURCES="$(RTL_DIR)/rv32_pkg.sv $(RTL_DIR)/core.sv $(RTL_DIR)/alu.sv $(RTL_DIR)/regfile.sv $(RTL_DIR)/immgen.sv $(RTL_DIR)/decoder.sv $(RTL_DIR)/branch_unit.sv $(RTL_DIR)/forwarding_unit.sv $(RTL_DIR)/hazard_unit.sv $(RTL_DIR)/../soc/imem.sv $(RTL_DIR)/../soc/dmem.sv $(RTL_DIR)/../soc/soc_top.sv"

include $(shell cocotb-config --makefiles)/Makefile.sim

# Must come AFTER the include, otherwise Makefile.sim's own default wins.
.DEFAULT_GOAL := test

clean::
	rm -rf sim_build __pycache__ results.xml dump.vcd
