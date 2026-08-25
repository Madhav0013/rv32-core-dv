# Microarchitecture Decisions

Every decision here is **locked**. The RTL implements this document. If a
decision turns out to be wrong during the build, change it in a single commit
that updates this document *and* the RTL together, with a message explaining
what the old decision broke. Never let the two drift apart.

Each entry is a question an interviewer can ask, which is why every one has a
rationale rather than just a value.

---

## 1. ISA scope

| Item | Decision | Rationale |
|---|---|---|
| Base ISA | RV32I | The complete base integer set. Nothing is omitted. |
| Extensions | **M** (mul/div), added in Phase 5 after I is fully passing | M is small, self-contained, and doubles the architectural test count for little design risk. C (compressed) is deliberately excluded — it complicates fetch alignment far more than it demonstrates. |
| Privilege modes | M-mode only | User and supervisor modes require a full trap and CSR implementation to mean anything. Claiming them without that is worse than not having them. |
| CSRs | `mcycle`, `minstret`, `mstatus`, `mtvec`, `mepc`, `mcause` only | The minimum needed to make traps observable and to measure CPI. Every other CSR reads as zero and is documented as unimplemented. |
| Traps / exceptions | **Not implemented**. Illegal instructions (including ECALL/EBREAK) are converted to pipeline bubbles and silently dropped. | Note: Originally claimed in scope, but bounded model checking (formal verification) proved the RTL converts them to bubbles rather than trapping. Recorded as a known design gap. |
| Misaligned memory access | **Traps** (raises a misaligned load/store exception) | Spec-permitted and simpler than hardware fixup. Hardware fixup requires splitting an access across two cycles, which touches the whole memory path for no verification benefit. |
| Multiply/divide latency | Multi-cycle iterative, stalls the pipeline | A single-cycle 32×32 multiplier destroys fmax and this project makes no frequency claim worth protecting. An iterative unit is honest and small. |
| Division by zero | Returns the spec-mandated values (quotient all ones, remainder = dividend), does **not** trap | RISC-V explicitly specifies this. Trapping would be a spec violation. |

---

## 2. Pipeline

| Item | Decision | Rationale |
|---|---|---|
| Stages | IF / ID / EX / MEM / WB | The canonical 5-stage. Every reviewer already has the mental model, so discussion goes straight to the hazards rather than to the structure. |
| Branch resolution stage | **EX** | Resolving in ID would need the comparator and its own forwarding paths a stage earlier, adding a critical path for one cycle of penalty. EX is the standard tradeoff. |
| Branch prediction | **Static predict-not-taken** | Honest and simple. A dynamic predictor is a separate project; claiming one and shipping a 2-bit counter attached to nothing is not worth the risk of being asked about it. |
| Misprediction penalty | **2 cycles** (IF and ID are flushed) | Direct consequence of resolving in EX. |
| Structural hazards | None — separate instruction and data memory ports | A unified memory would create a structural hazard between IF and MEM every load/store. Harvard split at the simulation boundary avoids a problem that teaches nothing here. |

### Pipeline register contents

Each boundary is a `struct packed` in `rtl/core/rv32_pkg.sv`. Using structs
rather than loose signals is not cosmetic: flush becomes a single assignment
instead of twenty, and twenty is where one gets forgotten.

- **`if_id_q`** — `pc`, `pc_plus_4`, `insn`, `valid`
- **`id_ex_q`** — `pc`, `pc_plus_4`, `rs1_addr`, `rs2_addr`, `rs1_data`,
  `rs2_data`, `imm`, `rd_addr`, `alu_op`, `alu_a_sel`, `alu_b_sel`, `br_op`,
  `is_branch`, `is_jump`, `mem_read`, `mem_write`, `mem_size`, `mem_signed`,
  `reg_write`, `wb_sel`, `valid`, `insn` *(insn carried for the retire trace)*
- **`ex_mem_q`** — `pc`, `alu_result`, `rs2_data`, `rd_addr`, `mem_*`,
  `reg_write`, `wb_sel`, `valid`, `insn`
- **`mem_wb_q`** — `pc`, `alu_result`, `mem_rdata`, `rd_addr`, `reg_write`,
  `wb_sel`, `valid`, `insn`

`valid` on every stage is what makes flushing a one-bit operation and what keeps
flushed instructions out of the retire trace.

---

## 3. Hazard handling

Three distinct problems, three separate modules. Keeping them separate in the
RTL means a failing test names which mechanism is broken.

### 3.1 Register file ordering

**Decision: WRITE-FIRST (internal forwarding).**

A read in the same cycle as a write to the same address returns the **new**
value.

**Consequence:** the WB→ID hazard is resolved inside the register file, so the
pipeline needs only **two** forwarding paths instead of three.

If this is ever changed to read-first,
`tb/cocotb/test_regfile.py::test_write_first_bypass` must be updated and a third
forwarding path added **in the same commit**.

### 3.2 Forwarding paths

Implemented in `rtl/core/forwarding_unit.sv`.

| Path | Source | Destination | Covers |
|---|---|---|---|
| EX→EX | `ex_mem_q.alu_result` | EX operand mux | RAW at distance 1 |
| MEM→EX | writeback data from `mem_wb_q` | EX operand mux | RAW at distance 2 |
| WB→ID | *(inside the register file)* | — | RAW at distance 3 |

**Priority: EX→EX wins over MEM→EX** when both match. The nearer source is the
*younger* instruction and therefore holds the value the consumer must see.
Getting this priority backwards produces a bug that only appears when a register
is written twice within three instructions — rare in hand-written tests, common
under riscv-dv. This is a deliberate coverage point.

Forwarding is suppressed when the producing instruction has `reg_write = 0`, or
when its `rd_addr` is `x0`.

### 3.3 Load-use hazard

Cannot be forwarded: a load's data is not available until the end of MEM.

- **Detection** — in ID: `id_ex_q.mem_read && id_ex_q.valid &&
  (id_ex_q.rd_addr != 0) && (id_ex_q.rd_addr == rs1_addr || id_ex_q.rd_addr == rs2_addr)`
- **Response** — stall **1 cycle**: hold `if_id_q` and the PC, inject a bubble
  into `id_ex_q` by clearing its `valid` bit.
- The stall is generated in ID, not IF, because the dependency is only visible
  once the consumer's source registers have been decoded.

### 3.4 Control hazard

- On a taken branch or a jump resolved in EX: flush **IF and ID** by clearing
  `valid` in `if_id_q` and `id_ex_q`.
- Flush is implemented by **clearing valid bits**, not by injecting NOP
  encodings. A NOP is a real instruction that would appear in the retire trace
  and cause a spurious lockstep mismatch; a cleared valid bit produces nothing.
- Stall (load-use) takes priority over flush in the same cycle: a flush
  discards the stalled instruction anyway.

---

## 4. Memory interface

| Item | Decision | Rationale |
|---|---|---|
| Instruction memory | Combinational read, single cycle | Keeps IF trivial in a project whose subject is hazards, not memory systems. |
| Data memory | Combinational read (Phase 1), Synchronous read (Phase 2) | Phase 1 requires combinational read because the PC advances every cycle with no pipeline registers. Phase 2 requires synchronous read to create the load-use hazard. |
| Latency | Fixed single cycle, no handshake | A variable-latency handshake is realistic but adds a stall mechanism orthogonal to everything being verified. Documented as a simplification. |
| Byte enables | 4-bit write strobe, supports SB / SH / SW | Required for the architectural suite to pass. |
| Load extension | LB/LH sign-extend, LBU/LHU zero-extend | Spec. A classic bug site — gets its own directed test. |
| Base address | `0x80000000` | Matches Spike's default so one ELF runs on both RTL and reference model without relinking. |
| Memory size | 2 MB | Originally 256 KB, but increased to 2 MB (with an 18-bit address truncation fixed in `imem.sv`) after discovering an address-truncation bug where `bgeu-01.S` exceeded 256 KB, causing the PC to silently wrap around and fetch incorrect instructions. |

---

## 5. Reset

| Item | Decision |
|---|---|
| Polarity | Active low (`rst_ni`) |
| Synchronous or asynchronous | **Synchronous**, matching FPGA block-RAM and flip-flop reset behaviour |
| Reset vector | `0x80000000` |
| Register file on reset | All 31 registers zeroed |
| Pipeline registers on reset | All `valid` bits cleared |

Zeroing the register file matters for co-simulation: if the RTL starts at zero
and Spike starts elsewhere, a program that reads an uninitialised register
diverges for reasons unrelated to any real bug. `sw/crt0.S` also explicitly
zeroes all registers for the same reason.

---

## 6. Explicitly out of scope

Stated as decisions rather than left as gaps:

- Compressed instructions (C extension)
- Floating point (F/D)
- Atomics (A)
- Interrupts and the PLIC/CLINT
- Virtual memory, MMU, TLB
- Caches — memory is flat and single-cycle
- Branch prediction beyond static not-taken
- Superscalar or out-of-order execution
- Power and clock gating

---

## 7. Known deviations from the specification

Ideally empty. Every entry needs a reason.

| Deviation | Reason | Impact |
|---|---|---|
| `fence` executes as a NOP | Single-hart, in-order, no caches — there is nothing to order | None observable to any conforming program |
| Unimplemented CSRs read as 0 rather than raising illegal-instruction | Simplifies the CSR file; the architectural suite at M-mode does not test this | Documented in `docs/verification_plan.md` §4 |
