# Known Issues

Tests that currently fail, and why they have not been fixed yet.

Per `AGENT_BRIEF.md` §2.1, a failing test is **never** silenced, skipped, or
adjusted to match the DUT. It is left failing and recorded here. An empty file
is fine; a file that is empty because failures were hidden is not.

| ID | Test | Symptom | Suspected cause | Blocked on |
|---|---|---|---|---|
| 1 | `insn_lb`, `insn_lbu`, `insn_lh`, `insn_lhu`, `insn_lw` | `FAIL` | (b) unwired RVFI field. `rvfi_mem_rdata` is hardcoded to 0 in MEM stage instead of tracking the loaded data. | RVFI implementation |
| 2 | `insn_sb`, `insn_sh`, `insn_sw` | `FAIL` | (b) unwired RVFI field. `rvfi_mem_wmask` is hardcoded to `4'b1111` ignoring store size, breaking the property. | RVFI implementation |
| 3 | `pc_fwd_ch0` | `FAIL` | (a) real RTL bug. The core silently drops illegal instructions by clearing `valid` instead of trapping, causing the RVFI trace to skip PC values and fail the forward progress check. | Decoder trap handler |
| 4 | `liveness_ch0` | `FAIL` | (a) real RTL bug. If fed an infinite stream of illegal instructions (e.g. ECALL), they are silently dropped forever and no instruction retires, violating liveness. | Decoder trap handler |
| 5 | `reg_ch0` | `FAIL` | (b) unwired RVFI field (instrumentation defect). The register file write-enable is correctly gated by `valid`, so the RTL is architecturally safe. The failure is an independent RVFI harness defect caused by pipeline bubbles retaining `reg_write=1` into the monitor, or unconditional assignment of `rvfi_rs1_addr`/`rvfi_rs2_addr`. | RVFI implementation |

## Artifact Inventory (post-recovery)

The local WSL environment suffered three filesystem failures. The following
records what survived on the Windows filesystem and what was lost.

| Artifact | Status | Notes |
|---|---|---|
| RTL sources (10 .sv files) | ✅ Intact | `rtl/core/`, `rtl/soc/` |
| Testbench (cocotb, lockstep) | ✅ Intact | `tb/cocotb/`, `tb/lockstep/` |
| RISCOF DUT plugin | ✅ Intact | `tests/riscof/rv32i_core/` |
| `riscof_work/report.html` | ✅ 41/41 passed | Committed as evidence |
| Scripts (setup, env, audit) | ✅ Intact | `scripts/` |
| Documentation | ✅ Intact | `docs/` |
| Formal checks output | ❌ Lost | `formal/checks/` was empty — no SymbiYosys task results exist |
| Random regression logs | ❌ Lost | Only 1 of intended 50 `.rtl.log` files survived |
| Coverage trace | ❌ Lost | WSL crashed during extraction |

## Unsubstantiated Claims Reset

- **Formal verification (43 / 15):** The README previously claimed 43 properties
  proven at bound depth 15. No passing SymbiYosys task output exists to
  substantiate this. The RVFI instrumentation work (`formal/wrapper.sv`,
  `checks.cfg`, the PREUNSAT/anyseq diagnosis in `docs/debug_log.md` Entry 6)
  is real and valuable. The *result* claim has been reset to `—` and will be
  restored only when CI produces passing `.sby` task output.

- **Random regression:** The README already showed `—` for random programs
  co-simulated. This remains `—` until CI produces verified numbers.

## Environment and Infrastructure Failures

- **WSL Filesystem Corruption (×3):** The WSL2 Ubuntu instance suffered three
  separate ext4 filesystem failures under simulation I/O load. The third failure
  (EXT4 I/O error on `/dev/sdd`, automatic read-only remount) rendered the
  instance unbootable. All verification has been moved to GitHub Actions CI.

- **Misdiagnosed workarounds:** Several failures attributed to concurrency bugs
  were actually symptoms of the failing filesystem. See `docs/debug_log.md`
  Entry 7 for the full analysis. The only genuine concurrency fix (per-test
  `SIM_BUILD` directory in `run_sim.py`) has been kept.
