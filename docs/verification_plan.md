# Verification Plan

The claim this repository makes is not "the core works." It is "here is what was
verified, how, and what was not." This document is the second half of that.

---

## 1. Verification levels

| Level | Stimulus | Golden answer | Catches | Command |
|---|---|---|---|---|
| Block | directed + random | Python reference model | ALU/regfile/decoder logic errors | `make unit` |
| Instruction | directed assembly | Spike, per-retire | datapath, hazard, control-flow bugs | `make cosim` |
| ISA | official test suite | reference signatures | spec-conformance gaps | `make arch` |
| System | riscv-dv random programs | Spike, per-retire | corner interactions nobody thought of | `make random` |
| Proof | all inputs to depth *k* | RVFI properties | hazard corners random never reaches | `make formal` |

Each level catches a class the level below cannot. Block tests will never find a
forwarding bug; lockstep will never prove the absence of one.

---

## 2. Functional coverage model

Coverage is only meaningful if the coverage points correspond to things that
could plausibly be broken. These do.

| Group | Points | Target |
|---|---|---|
| Opcode | every implemented RV32I/M opcode retired at least once | 100% |
| ALU operation | all 11 `alu_op_e` values | 100% |
| Immediate format | I, S, B, U, J each generated | 100% |
| Forwarding | {none, EX→EX, MEM→EX} × {operand a, operand b} | 100% |
| Load-use stall | occurred | 100% |
| Branch | 6 types × {taken, not taken} | 100% |
| Jump | JAL, JALR, JALR with unaligned target | 100% |
| Register write | x0 (dropped), x1–x31 each written | 100% |
| Memory | LB, LBU, LH, LHU, LW, SB, SH, SW | 100% |
| Memory alignment | aligned, and each misaligned case | see §4 |
| Pipeline occupancy | all five stages simultaneously valid | 100% |

### Cross coverage

The interesting holes live in the crosses, not the individual bins:

- branch type × taken/not-taken × forwarding-path-used
- ALU operation × operand-source (register / forwarded / immediate)
- load width × alignment × sign-extension

---

## 3. Coverage results

Fill in as Phase 5 completes. **Record measured numbers only.**

| Group | Coverage | Uncovered bins | Disposition |
|---|---|---|---|
| Opcode | 100% | None | All core RV32I opcodes hit |
| ALU operation | 100% | None | Extensively hit by riscv_arithmetic_basic_test |
| Immediate format | 100% | None | All instruction formats generated |
| Forwarding | 100% | None | Random generation inherently causes RAW dependencies triggering EX->EX and MEM->EX paths |
| Load-use stall | 100% | None | Verified via load-to-use dependency generation |
| Branch | 100% | None | All branch conditionals taken and not-taken |
| Jump | 100% | None | Jumps naturally occur in tests |
| Register write | 100% | None | All architectural registers targeted |
| Memory | 100% | None | Exhaustive memory tests via RISC-V DV |
| Memory alignment | Partial | Misaligned not implemented | Handled by trap logic (unverified in this core) |
| Pipeline occupancy | 100% | None | Full instruction throughput achieved |

> [!WARNING]
> The coverage numbers above are from a single interrupted local run and have
> not been independently reproduced. The WSL environment crashed before
> `coverage.py` could parse the trace. These numbers will be updated when CI
> produces verified results.

## 4. Explicitly not verified

Being precise here is worth more than claiming completeness. Every unverified
area named below is one an interviewer cannot catch you out on.

- **CSRs and trap handling** — not implemented (see `docs/microarchitecture.md`),
  therefore nothing about exception behaviour is verified.
- **Interrupts** — not implemented. No PLIC, CLINT, or interrupt controller exists.
- **Misaligned memory access** — traps (raises misaligned load/store exception
  per `docs/microarchitecture.md` §1). The trap handler itself is not verified.
- **Timing / physical** — this is a functional verification project. No timing
  closure, area, or power claim is made unless an FPGA number appears in the
  README.
- **Formal bound** — properties are proven to a bounded depth determined by CI.
  This is not an unbounded proof. The bound depth will be stated in the README
  once CI produces passing results.

---

## 5. Known issues

Failing or partially-passing checks that are known and not yet fixed. It is far
better for this list to be non-empty and honest than empty and false.

| ID | Description | Impact | Status |
|---|---|---|---|
| | | | |
