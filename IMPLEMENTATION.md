# Implementation Guide — End to End

This is the complete build manual. [`AGENT_BRIEF.md`](AGENT_BRIEF.md) states the
rules; this file states what to do, in what order, and why.

Work through it start to finish. Each phase ends with a **checkpoint** — a
command that must exit 0 before moving on. Do not skip checkpoints. A bug
introduced in Phase 2 and discovered in Phase 5 costs ten times what it costs
immediately, because by then you cannot tell whether the failure is in the core,
the testbench, the toolchain, or the test generator.

All design decisions are already locked in
[`docs/microarchitecture.md`](docs/microarchitecture.md). Implement that
document. Do not re-derive its choices.

---

## Contents

- [The mental model](#the-mental-model)
- [Phase 0 — Environment and baseline](#phase-0--environment-and-baseline)
- [Phase 1 — Single-cycle core](#phase-1--single-cycle-core)
- [Phase 2 — Pipeline](#phase-2--pipeline)
- [Phase 3 — Spike lockstep co-simulation](#phase-3--spike-lockstep-co-simulation)
- [Phase 4 — RISCOF architectural compliance](#phase-4--riscof-architectural-compliance)
- [Phase 5 — Constrained-random and coverage](#phase-5--constrained-random-and-coverage)
- [Phase 6 — Formal verification](#phase-6--formal-verification)
- [Phase 7 — Presentation](#phase-7--presentation)
- [Troubleshooting](#troubleshooting)
- [Interview preparation](#interview-preparation)

---

## The mental model

Everything here is one idea applied at five scales:

> **Drive a design. Compute the right answer somewhere else. Diff them.**

| Scale | The design | The independent answer | The diff |
|---|---|---|---|
| Block | ALU, decoder, immgen | Python model written from the spec | `tb/cocotb/*` |
| Instruction | Whole core | Spike, per retire | `tb/lockstep/spike_compare.py` |
| ISA | Whole core | Official test signatures | RISCOF |
| System | Whole core | Spike, over random programs | riscv-dv + lockstep |
| Proof | Whole core | RVFI properties | riscv-formal + SymbiYosys |

`tb/cocotb/test_alu.py` computes expected values from a `model()` function
written from the specification rather than hardcoding them. That is a miniature
of the entire repository — understand why, and the rest follows.

The second idea:

> **When something breaks, the first divergence is the bug. Everything after it
> is a consequence.**

This is why `spike_compare.py` stops at the first mismatch. A trace with 4,000
mismatches has one bug in it, at the top.

---

## Phase 0 — Environment and baseline

**Goal:** a green regression before any new RTL exists, so later breakage is
unambiguously new.

**Time: 1–2 hours, mostly waiting for Spike to compile.**

### 0.1 Setup

```bash
./scripts/setup.sh          # 10–20 min; builds Spike from source
source scripts/env.sh
```

`setup.sh` installs Verilator, pinned Python packages, a **prebuilt** RISC-V GCC
cross-compiler, and Spike.

> **Why prebuilt GCC.** Building `riscv-gnu-toolchain` from source takes one to
> three hours and ~30 GB. Nearly every tutorial says to do it. It is
> unnecessary — the xPack release is a standalone relocatable tarball with rv32
> multilib.

### 0.2 Verify

```bash
riscv-none-elf-gcc --version
spike --help | head -3
verilator --version
cocotb-config --version
```

All four must respond. A missing `riscv-none-elf-gcc` means `source
scripts/env.sh` was skipped.

### 0.3 Baseline regression

```bash
make lint
make unit
python3 tb/lockstep/spike_compare.py --selftest
```

### 0.4 Read the scaffold

Read these four files before writing anything:

- `rtl/core/rv32_pkg.sv` — control encodings decoupled from instruction encodings
- `rtl/core/regfile.sv` — write-first bypass and its consequence for forwarding
- `tb/cocotb/test_alu.py` — the reference-model pattern every test follows
- `tb/lockstep/spike_compare.py` — the retire trace format the RTL must emit

### ✅ Checkpoint 0

```bash
make lint && make unit && python3 tb/lockstep/spike_compare.py --selftest
```

---

## Phase 1 — Single-cycle core

**Goal:** a correct, slow, unpipelined RV32I core.

**Time: ~1 week.**

> **Why build something that gets restructured.** In a pipelined core, a wrong
> B-type immediate and a missing forwarding path produce the *same symptom*: a
> branch goes the wrong way. Debugging both at once is miserable. A single-cycle
> core has no hazards by construction, so every Phase 1 failure is unambiguously
> a decode, immediate, ALU, branch, or memory bug. Roughly 60% of this RTL
> survives into Phase 2 untouched.

Build in this order, each module with its own cocotb test against a Python
model, each its own commit.

### 1.1 `rtl/core/immgen.sv`

Start here — it is small, it is pure combinational logic, and it is the single
most common source of "my branches jump to insane addresses".

```systemverilog
`include "rv32_pkg.sv"

module immgen
  import rv32_pkg::*;
(
    input  logic [31:0]     insn_i,
    input  imm_sel_e        sel_i,
    output logic [XLEN-1:0] imm_o
);

  // The B-type and J-type immediates have SCRAMBLED bit orders. This is not an
  // error in the specification -- it is deliberate, so the sign bit and most
  // immediate bits occupy the same instruction positions across all formats,
  // which shrinks the decoder's muxes. It is also why writing this from memory
  // rather than from the spec table produces a core that fails every branch.
  //
  // Note the implicit trailing 0 on B and J: branch and jump offsets are
  // always even, so bit 0 is not encoded.
  always_comb begin
    unique case (sel_i)
      IMM_I: imm_o = {{20{insn_i[31]}}, insn_i[31:20]};
      IMM_S: imm_o = {{20{insn_i[31]}}, insn_i[31:25], insn_i[11:7]};
      IMM_B: imm_o = {{19{insn_i[31]}}, insn_i[31], insn_i[7],
                      insn_i[30:25], insn_i[11:8], 1'b0};
      IMM_U: imm_o = {insn_i[31:12], 12'b0};
      IMM_J: imm_o = {{11{insn_i[31]}}, insn_i[31], insn_i[19:12],
                      insn_i[20], insn_i[30:21], 1'b0};
      default: imm_o = '0;
    endcase
  end

endmodule : immgen
```

The Python model in `tb/cocotb/test_immgen.py` must be written independently
from the spec's immediate-encoding table, not transcribed from the RTL above.
Randomize over all 2³² instruction words for each format.

### 1.2 `rtl/core/decoder.sv`

Instruction in, control signals out. Purely combinational. Outputs everything
`id_ex_q` carries: `alu_op`, `imm_sel`, operand-select muxes, register
addresses, `reg_write`, `mem_read`/`mem_write`/`mem_size`/`mem_signed`,
branch/jump kind, `wb_sel`, and `illegal`.

Structure it as a single `unique case (opcode)` with nested `case (funct3)`,
defaulting to `illegal = 1'b1` with all enables cleared. The default arm is not
optional — an incomplete case here is a latch.

Key points that cost people days:

- `SRLI`/`SRAI` are distinguished by `insn[30]`, as are `ADD`/`SUB`. Nothing
  else in the base ISA uses that bit.
- Shift immediates use only `insn[24:20]`; `insn[31:25]` must be checked and an
  out-of-range shift amount flagged illegal.
- `JALR` ignores bit 0 of the computed target (`target & ~1`), `JAL` does not.
- Writes to `x0` must still set `reg_write` — the register file drops them. Do
  not special-case `x0` in the decoder, or forwarding logic will disagree with
  the register file about whether a write happened.

The decoder test is the highest-value test in Phase 1. Randomize over **all**
encodings, including illegal ones, and check that `illegal` is asserted exactly
when the instruction is not in the base ISA.

### 1.3 `rtl/core/branch_unit.sv`

Two operands plus `br_op_e`, out comes taken/not-taken.

Test signed against unsigned at the boundary: `0x7FFFFFFF` vs `0x80000000` must
compare *differently* for `BLT` and `BLTU`. If both give the same answer,
`$signed` is missing somewhere.

### 1.4 `rtl/soc/imem.sv` and `rtl/soc/dmem.sv`

Per `docs/microarchitecture.md` §4: instruction memory combinational read, data
memory synchronous read, 4-bit write strobe, 256 KB at `0x80000000`.

`dmem` handles sub-word access: `SB`/`SH` write strobes, and `LB`/`LH`
sign-extension vs `LBU`/`LHU` zero-extension. Misaligned access raises the
exception rather than being fixed up in hardware.

### 1.5 `rtl/core/core.sv`

Wire it together with a program counter. Single cycle: PC advances every cycle,
no pipeline registers, no hazards.

### 1.6 `rtl/soc/soc_top.sv`

Core plus both memories plus the `tohost` monitor. The testbench loads the ELF's
`.text` and `.data` into memory, releases reset, and runs until a write to the
`tohost` address.

**Resolve `tohost` from the ELF symbol table with `pyelftools`. Do not hardcode
its address** — it moves whenever a test program's size changes, and a hardcoded
address produces a hang that looks like a core bug.

### 1.7 Directed assembly tests

`tests/asm/test_arith.S` already exists as the pattern: each check is numbered,
`main` returns 0 on success or the failing check number, and `crt0.S` encodes
that into `tohost`.

Write one file per group: `test_arith.S`, `test_logic.S`, `test_shift.S`,
`test_branch.S`, `test_jump.S`, `test_load_store.S`, `test_lui_auipc.S`,
`test_edge.S`.

Build and run:

```bash
mkdir -p build
riscv-none-elf-gcc -march=rv32i -mabi=ilp32 -nostdlib -nostartfiles \
    -T sw/link.ld sw/crt0.S tests/asm/test_arith.S -o build/test_arith.elf
riscv-none-elf-objdump -d build/test_arith.elf | less
spike --isa=rv32i build/test_arith.elf     # MUST pass before touching the RTL
```

> **Always run a new test on Spike first.** If the test program is itself wrong,
> hours disappear "debugging" a core that is behaving correctly. Spike is the
> arbiter of what the program *should* do.

Add a `make asm` target that builds every `tests/asm/*.S`, runs each on Spike,
and fails loudly if any test does not pass on the reference model.

### ✅ Checkpoint 1

```bash
make lint && make unit && make asm
# every tests/asm/ program writes tohost = 1
git tag phase1-single-cycle
```

---

## Phase 2 — Pipeline

**Goal:** 5 stages, hazards handled, identical results.

**Time: ~1 week. The hardest phase.**

### 2.1 Pipeline register structs

Add to `rv32_pkg.sv`, matching `docs/microarchitecture.md` §2 exactly:

```systemverilog
  typedef struct packed {
    logic [XLEN-1:0] pc;
    logic [XLEN-1:0] pc_plus_4;
    logic [31:0]     insn;
    logic            valid;
  } if_id_t;

  typedef struct packed {
    logic [XLEN-1:0] pc, pc_plus_4;
    logic [31:0]     insn;          // carried solely for the retire trace
    logic [4:0]      rs1_addr, rs2_addr, rd_addr;
    logic [XLEN-1:0] rs1_data, rs2_data, imm;
    alu_op_e         alu_op;
    logic            alu_a_sel;     // 0 = rs1,  1 = pc
    logic            alu_b_sel;     // 0 = rs2,  1 = imm
    br_op_e          br_op;
    logic            is_branch, is_jump;
    logic            mem_read, mem_write, mem_signed;
    logic [1:0]      mem_size;
    logic            reg_write;
    logic [1:0]      wb_sel;        // 0 = alu, 1 = mem, 2 = pc_plus_4
    logic            valid;
  } id_ex_t;
```

…and similarly `ex_mem_t`, `mem_wb_t`.

> **Structs, not loose signals.** Flush becomes `id_ex_q.valid <= 1'b0` — one
> assignment instead of twenty. Twenty is where one gets forgotten, and the one
> that gets forgotten is the one that causes a bug three weeks later.

### 2.2 `rtl/core/forwarding_unit.sv`

```systemverilog
`include "rv32_pkg.sv"

module forwarding_unit
  import rv32_pkg::*;
(
    input  logic [4:0] ex_rs1_addr_i,
    input  logic [4:0] ex_rs2_addr_i,

    input  logic [4:0] mem_rd_addr_i,     // instruction currently in MEM
    input  logic       mem_reg_write_i,
    input  logic       mem_valid_i,

    input  logic [4:0] wb_rd_addr_i,      // instruction currently in WB
    input  logic       wb_reg_write_i,
    input  logic       wb_valid_i,

    output fwd_sel_e   fwd_a_o,
    output fwd_sel_e   fwd_b_o
);

  // EX->EX must take priority over MEM->EX. The nearer source is the YOUNGER
  // instruction and therefore holds the value the consumer must observe.
  //
  // Getting this backwards produces a bug that only appears when the same
  // register is written twice within three instructions -- rare in hand-written
  // tests, common under riscv-dv. That is exactly why it is a coverage point.
  function automatic fwd_sel_e select(input logic [4:0] src);
    if (mem_valid_i && mem_reg_write_i && (mem_rd_addr_i != 5'd0)
        && (mem_rd_addr_i == src))       return FWD_EX_EX;
    else if (wb_valid_i && wb_reg_write_i && (wb_rd_addr_i != 5'd0)
        && (wb_rd_addr_i == src))        return FWD_MEM_EX;
    else                                 return FWD_NONE;
  endfunction

  assign fwd_a_o = select(ex_rs1_addr_i);
  assign fwd_b_o = select(ex_rs2_addr_i);

endmodule : forwarding_unit
```

Add `fwd_sel_e` to `rv32_pkg.sv` with values `FWD_NONE`, `FWD_EX_EX`,
`FWD_MEM_EX`.

Note the `rd_addr != 0` guard on both paths: forwarding a write to `x0` would
deliver a value the register file discarded.

### 2.3 `rtl/core/hazard_unit.sv`

```systemverilog
  // Load-use: a load's data is not available until the end of MEM, so an
  // immediately dependent instruction cannot be rescued by forwarding. It must
  // stall exactly one cycle.
  //
  // Detected in ID, not IF: the dependency is only visible once the consumer's
  // source registers have been decoded.
  assign load_use_stall_o =
      id_ex_valid_i && id_ex_mem_read_i && (id_ex_rd_addr_i != 5'd0) &&
      ((id_ex_rd_addr_i == id_rs1_addr_i) || (id_ex_rd_addr_i == id_rs2_addr_i));

  // Stall: hold PC and if_id_q, clear id_ex_q.valid to inject a bubble.
  assign pc_stall_o    = load_use_stall_o;
  assign if_id_hold_o  = load_use_stall_o;
  assign id_ex_bubble_o = load_use_stall_o;

  // Flush on a taken branch or jump resolved in EX. Clear VALID BITS -- do not
  // inject NOP encodings. A NOP is a real instruction that would appear in the
  // retire trace and cause a spurious lockstep mismatch; a cleared valid bit
  // produces nothing at all.
  assign if_id_flush_o = branch_taken_i;
  assign id_ex_flush_o = branch_taken_i;
```

Flush takes priority over stall in the same cycle — a flush discards the stalled
instruction anyway.

### 2.4 The retire trace

From WB, emit one line per retired instruction, gated on `mem_wb_q.valid`:

```
<pc_hex> <insn_hex> <rd_dec> <rd_wdata_hex>
80000000 00000297 5 80000000
80000004 00028067 0 00000000
```

> **Gate on retirement, not on fetch.** An instruction flushed by a taken branch
> must never appear here. If it does, Phase 3 reports "RTL retired MORE than
> Spike" — that message means precisely this bug.

`rd` is 0 when there is no architectural register write, which is also literally
true since `x0` is hardwired.

### 2.5 Directed hazard tests

Write `tests/asm/test_hazard.S` before involving Spike, so failures name
themselves:

```asm
# RAW at distance 1 -- requires EX->EX forwarding
addi x1, x0, 5
addi x2, x1, 3          # x2 must be 8

# RAW at distance 2 -- requires MEM->EX forwarding
addi x1, x0, 5
nop
addi x2, x1, 3

# Double write within 3 instructions -- tests forwarding PRIORITY
addi x1, x0, 1
addi x1, x0, 2
addi x2, x1, 0          # x2 must be 2, not 1

# Load-use -- requires a stall; forwarding cannot help
lw   x1, 0(x3)
addi x2, x1, 1

# Taken branch -- requires a flush
beq  x0, x0, 1f
addi x5, x0, 0xDEAD     # must NOT execute
1:

# x0 forwarding -- a write to x0 must not be forwarded
addi x0, x0, 42
add  x6, x0, x0         # x6 must be 0
```

### ✅ Checkpoint 2

```bash
make lint-top && make unit && make asm
# all Phase 1 programs produce identical results
# test_hazard.S passes
git tag phase2-pipelined
```

---

## Phase 3 — Spike lockstep co-simulation

**Goal:** every retired instruction checked against the golden model,
automatically.

**Time: 2–3 days. The highest value-per-hour phase in the project.**

### 3.1 Wire it up

```bash
python3 tb/lockstep/spike_compare.py \
    --elf build/test_arith.elf \
    --rtl-log build/test_arith.rtl.log
```

The comparator runs Spike, parses both traces, and reports the first divergence
with a decoded "likely cause". Read its module docstring — it documents both
trace formats.

Add a `make cosim` target running this over every program in `tests/asm/`.

### 3.2 Prove the safety net works

**Do not skip this.** A comparator that always passes is worse than none,
because it will be trusted.

Deliberately break the MEM→EX forwarding path, rebuild, and confirm that:

1. the comparator **fails**, and
2. the instruction number and likely-cause text actually point at forwarding.

Then revert, and write it up as the first entry in `docs/debug_log.md`.
Validating a checker by fault injection before trusting it is worth recording.

Repeat with two more injections: swap the forwarding priority, and remove the
load-use stall. Confirm each is caught and correctly localized.

### ✅ Checkpoint 3

```bash
make cosim      # exits 0 for every tests/asm/ program
# three fault injections demonstrated and reverted, logged in docs/debug_log.md
git tag phase3-lockstep
```

---

## Phase 4 — RISCOF architectural compliance

**Goal:** pass the official RISC-V architectural test suite.

**Time: 3–4 days, most of it on the plugin, not the core.**

### 4.1 How RISCOF actually works

The official docs bury this. RISCOF compiles each test **twice** — once for the
DUT, once for a reference model (Spike). Each test writes a **signature**: a
region of memory holding the values it computed. RISCOF diffs the two
signatures. Identical means pass.

So the plugin's entire job is three things:

1. compile the test ELF with the right flags
2. run it on the RTL
3. dump the signature memory region to a text file

Everything else is configuration.

### 4.2 Generate the templates

```bash
riscof setup --dutname=rv32i_core --refname=spike
mkdir -p tests/riscof
mv rv32i_core spike config.ini tests/riscof/
```

### 4.3 Fill in the ISA YAML honestly

`tests/riscof/rv32i_core/rv32i_core_isa.yaml` declares supported extensions,
XLEN, and CSRs.

**Declaring something unimplemented makes RISCOF run tests that cannot pass**,
and a day disappears assuming the core is broken. Start at `RV32I`, M-mode only.
Add `M` only after `I` passes end to end.

### 4.4 Fill in the plugin

Three methods in `riscof_rv32i_core.py`. The core of `runTests` looks like:

```python
def runTests(self, testList):
    for testname in testList:
        testentry = testList[testname]
        test      = testentry['test_path']
        test_dir  = testentry['work_dir']
        elf       = os.path.join(test_dir, 'dut.elf')
        sig_file  = os.path.join(test_dir, self.name[:-1] + ".signature")

        # 1. compile
        compile_cmd = (
            f'{self.compile_cmd} -march={testentry["isa"].lower()} '
            f'{testentry["macros"]} {test} -o {elf}'
        )
        utils.shellCommand(compile_cmd).run(cwd=test_dir)

        # 2. simulate on the RTL, dumping the signature region
        sim_cmd = (
            f'python3 {self.repo_root}/tb/verilator/run_sim.py '
            f'--elf {elf} --signature {sig_file}'
        )
        utils.shellCommand(sim_cmd).run(cwd=test_dir)
```

`run_sim.py` resolves `begin_signature` and `end_signature` from the ELF symbol
table with `pyelftools`, runs the simulation, then writes that memory region as
**one 32-bit word per line, lowercase hex, no `0x` prefix**. Format mismatches
here produce a diff on every test and look like a catastrophic core failure.

### 4.5 Run and iterate

```bash
make arch
xdg-open riscof_work/report.html
```

Expect failures on the first run. Work through them one at a time — the report
links each failing test to its signature diff, and a diff at word N identifies
which test instruction produced it.

Once `RV32I` is at 100%, implement the M extension and add it to the ISA YAML.

### ✅ Checkpoint 4

```bash
make arch     # exits 0, report shows 100% for all declared extensions
# screenshot committed to docs/img/
# arch-tests CI job enabled and green
git tag phase4-riscof
```

---

## Phase 5 — Constrained-random and coverage

**Goal:** stimulus nobody designed, and a measured number for how much of the
design was exercised.

**Time: ~1 week.**

### 5.1 riscv-dv without a licence

riscv-dv's documented flow requires VCS, Xcelium or Questa. Use **pyflow**
instead, which reimplements the generator in Python on PyVSC:

```bash
./scripts/run_random_regression.sh -t riscv_arithmetic_basic_test -n 20
```

The `--simulator=pyflow` flag inside that script is the whole trick. Most
student projects skip this phase because the README says "commercial simulator
required" and they stop reading there.

Run these templates in increasing difficulty:

- `riscv_arithmetic_basic_test` — straight-line ALU work
- `riscv_rand_instr_test` — everything, random
- `riscv_jump_stress_test` — control flow hammer
- `riscv_loop_test` — nested loops

Every generated program goes through the Phase 3 comparator, so a random
regression is simply lockstep at scale.

### 5.2 Functional coverage

Verilator gives line and toggle coverage via `--coverage`. Functional coverage —
the kind that means something — you build by instrumenting the retire trace in
Python. Write `scripts/coverage.py` that consumes retire traces plus a small
amount of extra RTL-emitted state (forwarding selects, stall and flush signals)
and reports bin hits.

Cover every group in [`docs/verification_plan.md`](docs/verification_plan.md) §2.
The crosses matter more than the individual bins:

- branch type × taken/not-taken × forwarding path used
- ALU operation × operand source (register / forwarded / immediate)
- load width × alignment × sign-extension

Add `make coverage`. Put the measured number in the README — if it is 87%, write
87%, not "high coverage".

### 5.3 Close the holes

For each uncovered bin, either write directed stimulus to hit it, or document in
`docs/verification_plan.md` §4 why it is unreachable, with the argument. "Not
reachable, and here is why" is a respectable entry and reasoning about
unreachable coverage is a senior-level skill.

### ✅ Checkpoint 5

```bash
make random      # ≥50 programs, ≥3 templates, all matching Spike
make coverage    # report generated, number recorded in README
git tag phase5-coverage
```

---

## Phase 6 — Formal verification

**Goal:** properties *proven* over all inputs to a bound, not merely tested.

**Time: 3–5 days.**

### 6.1 Why, when the tests already pass

Simulation demonstrates absence of bugs only on the stimulus that was run.
Bounded model checking explores *every* input sequence up to a depth, which
finds the hazard corner no random generator happened to produce.

It is also the rarest item on a new-grad resume in this area, which is the
practical reason it is worth five days.

### 6.2 Install

```bash
# OSS CAD Suite bundles Yosys, SymbiYosys (sby), and the SMT solvers.
# Latest linux-x64 tarball: https://github.com/YosysHQ/oss-cad-suite-build/releases
tar -xzf oss-cad-suite-linux-x64-*.tgz -C ~/riscv-tools/
source ~/riscv-tools/oss-cad-suite/environment
sby --version
```

> The suite also ships a much newer Verilator than Ubuntu's apt. If you switch
> to it, read the comment at the top of `requirements.txt` before touching the
> cocotb pin.

### 6.3 Add the RVFI interface

`riscv-formal` observes the core through **RVFI** — a bundle of outputs
describing each retired instruction: valid, order, insn, pc before and after,
rs1/rs2 addresses and values, rd address and value, memory address, read and
write masks and data.

This is the Phase 2 retire trace as structured wires instead of a text line,
which is exactly why Phase 2 comes first:

```systemverilog
  assign rvfi_valid     = mem_wb_q.valid;
  assign rvfi_order     = retire_counter_q;
  assign rvfi_insn      = mem_wb_q.insn;
  assign rvfi_pc_rdata  = mem_wb_q.pc;
  assign rvfi_pc_wdata  = mem_wb_q.pc + 32'd4;   // except for taken branch/jump
  assign rvfi_rd_addr   = mem_wb_q.reg_write ? mem_wb_q.rd_addr : 5'd0;
  assign rvfi_rd_wdata  = (rvfi_rd_addr != 5'd0) ? wb_data : 32'd0;
```

Carry `rs1_addr`, `rs2_addr`, `rs1_data`, `rs2_data` down the pipeline to WB for
the remaining RVFI fields. They are otherwise unused — that is normal, and their
only consumer is formal.

### 6.4 Wire and run

```bash
git clone https://github.com/YosysHQ/riscv-formal.git
# Use cores/nerv/ as the template -- it is the cleanest reference.
make formal
```

Get these passing in order of difficulty:

1. `insn_*` — one per instruction, proving each instruction's semantics
2. `reg` — register file consistency
3. `pc_fwd` / `pc_bwd` — program counter advances correctly
4. `liveness` — the core cannot deadlock
5. `causal` — no value read that was never written

### 6.5 State the bound honestly

Bounded model checking proves properties to depth *k*. Record *k* in the README.
Writing "formally verified" without the bound is exactly the overstatement
someone who does formal for a living catches in one question.

### ✅ Checkpoint 6

```bash
make formal     # exits 0; bound depth recorded in README
git tag phase6-formal
```

---

## Phase 7 — Presentation

**Goal:** a stranger clones the repo and is convinced in ninety seconds.

**Time: 2–3 days. Do not compress this — it is where the value is realised.**

### 7.1 README

1. One paragraph: what it is and what was proven about it
2. Numbers table (`AGENT_BRIEF.md` §6) — every cell traceable to a log
3. Block diagram as an image — not optional
4. Reproduce: `git clone && ./scripts/setup.sh && make regress`
5. Verification methodology — a paragraph per level, with its command
6. Design decisions — link to `docs/microarchitecture.md`
7. Bugs found — link to `docs/debug_log.md`
8. What is *not* verified
9. CI badge

### 7.2 Test the clean-machine path

```bash
docker run -it --rm ubuntu:24.04 bash
# apt-get update && apt-get install -y git sudo curl
# git clone <repo> && cd riscv-core-dv && ./scripts/setup.sh && make regress
```

**This is the most common way these projects fail a reviewer.** It works on the
build machine because of six things installed in week one and forgotten.

### 7.3 Finish the debug log

At least five entries, each with a real localization narrative. Structure:
symptom, localization, root cause, fix, prevention.

### ✅ Checkpoint 7

```bash
make regress          # green in a clean container
# README numbers table complete, docs/debug_log.md has ≥5 entries
git tag v1.0
```

---

## Troubleshooting

**`cocotb requires Verilator 5.036 or later, but using 5.020`**
cocotb 2.x with Ubuntu's apt Verilator. Either `pip install cocotb==1.9.2` (what
`requirements.txt` pins), or install a newer Verilator and change every
`units="ns"` to `unit="ns"`.

**`Can not find root handle (<module>)`**
Two cocotb targets sharing one `SIM_BUILD`; the second reuses the first's
compiled model. Give each toplevel its own — `tb/cocotb/Makefile` already does.

**`Unknown verilator comment`**
A `//` comment whose first word is "verilator" is parsed as a pragma. Reword it.

**Lockstep diverges on the very first instruction**
Almost always a memory-map mismatch, not a core bug. `sw/link.ld` and Spike must
agree on the base address (`0x80000000`).

**RTL retired more instructions than Spike**
Flushed instructions are reaching the retire trace. Gate on retirement, not
fetch.

**A branch goes to an absurd address**
B-type or J-type immediate bit-scrambling. Check `immgen.sv` against the spec
table field by field, including the implicit trailing zero.

**Forwarding works until a register is written twice quickly**
Forwarding priority is inverted — EX→EX must win over MEM→EX.

**RISCOF fails every test with an empty signature**
The plugin is not finding `begin_signature`/`end_signature` in the ELF, or is
writing to the wrong path. Check the plugin's output directory against what the
report expects.

**Formal runs forever**
Reduce the bound depth and look for an unconstrained input. An unbounded free
memory interface makes the state space explode — constrain the memory model.

---

## Interview preparation

The failure mode when asked to "walk me through your project" is describing the
*core*. Describe the *verification*:

> "I built a 5-stage RV32I core, but the part worth talking about is how it was
> verified. Spike runs in lockstep and architectural state is diffed on every
> retire, so any divergence localizes to a single instruction. On top of that:
> the RISCOF architectural suite for compliance, riscv-dv for constrained-random
> stimulus, and riscv-formal for bounded proofs of the ISA properties. The most
> interesting bug was [entry from the debug log] — it only appeared when [the
> specific condition], and it was found by [how it was localized]."

Then be ready for:

- Draw the forwarding paths. Why two and not three?
- Walk through a load-use hazard cycle by cycle.
- How do you know the testbench isn't the thing that's wrong?
- What did the formal tool prove, and to what depth?
- What's still not verified?

That last one separates candidates. A real answer — "interrupts aren't
implemented, so nothing about interrupt behaviour is verified" — signals more
engineering maturity than claiming completeness.

**Read `docs/debug_log.md` before any interview.** Those entries are the
specifics that make the difference between describing a project and having built
one.
