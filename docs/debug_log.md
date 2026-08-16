# Debug Log

Every non-trivial bug found during the build gets an entry here, written **as it
happens** rather than reconstructed afterwards. Target: at least five entries by
the end of Phase 6.

The *localization* section is the valuable part. Anyone can state a root cause
once they know it; what demonstrates skill is the search — what was looked at
first, what that ruled out, what hypothesis came next and how it was falsified.
Write it as a narrative, not a summary.

---

## Template — copy for each entry

### YYYY-MM-DD — One-line description

**Symptom**

The exact failure. Paste real output, not a paraphrase.

```
(failing test output, lockstep mismatch report, RISCOF signature diff, ...)
```

**Localization**

How it was narrowed down.

- What the first divergence indicated
- What was checked in the waveform, at which signal and which time
- What hypothesis was formed, and how it was confirmed or falsified
- What was ruled out along the way

**Root cause**

The precise defect. Not "forwarding was broken" but "the forwarding mux checked
MEM→EX before EX→EX, so when both matched the older value won."

**Fix**

```diff
(the actual diff)
```

**Prevention**

The regression test that now catches this, and why it would have caught it
earlier. If no test can catch it, say so and explain why.

---

### Entry 1 — Fault injection: validating the lockstep comparator

*(Phase 3.2. Not a real bug — this records that the checker was proven to work
before it was trusted. A comparator that always passes is worse than no
comparator.)*

**Injection 1:** MEM→EX forwarding path removed.

**Injection 2:** forwarding priority inverted (MEM→EX checked before EX→EX).

**Injection 3:** load-use stall removed.

For each: record whether the comparator failed, which instruction number it
reported, and whether the "likely cause" text pointed at the right subsystem.

**Symptom**

- **Injection 1 (MEM→EX broken):**
  Failed at retired instruction #43 in `test_hazard`.
  ```
  --- divergence ---
    RTL   : pc=0x800001f8 insn=0x00008067 -
    SPIKE : pc=0x800000d8 insn=0xfff00293 x5=0xffffffff

  --- likely cause ---
    * PC differs -> control flow bug (branch/jump target, or a flushed instruction was allowed to retire)
  ```
- **Injection 2 (Priority inverted):**
  Failed at retired instruction #61 in `test_hazard`.
  ```
  --- divergence ---
    RTL   : pc=0x80000120 insn=0x00138293 x5=0x80000001
    SPIKE : pc=0x80000120 insn=0x00138293 x5=0x80000000

  --- likely cause ---
    * WRITEBACK VALUE differs (xor=0x00000001) -> execute or forwarding bug. If only the low bits differ suspect the ALU; if the value equals an OLDER value of that register, suspect a missing forwarding path.
  ```
- **Injection 3 (Load-use stall removed):**
  Failed at retired instruction #63 in `test_hazard`.
  ```
  --- divergence ---
    RTL   : pc=0x80000128 insn=0x001e0e93 x29=0x80000191
    SPIKE : pc=0x80000128 insn=0x001e0e93 x29=0x0000002b

  --- likely cause ---
    * WRITEBACK VALUE differs (xor=0x800001ba) -> execute or forwarding bug.
  ```

**Localization**

For all three fault injections, the lockstep comparator perfectly caught the divergence on the exact instruction that was flawed:
- For Injection 1, the broken MEM→EX forwarding meant a branch or jump read a stale register value, causing an immediate control flow divergence (PC mismatch).
- For Injection 2, the wrong forwarded value was routed to an ALU instruction (`addi`), which the comparator successfully identified as a WRITEBACK VALUE mismatch pointing to an execute/forwarding bug.
- For Injection 3, the missing load-use stall allowed a dependent instruction to read an undefined forwarding path before the load produced the data, resulting in a WRITEBACK VALUE mismatch on the very next instruction.

**Root cause**

Deliberately injected — see above.

**Fix**

Reverted all three injections.

**Prevention**

N/A. This entry documents that the safety net was validated before being relied upon.

---

### Entry 2 — RISCOF `bgeu-01.S` timeout due to instruction memory wrapping

**Symptom**

During the first run of Phase 4 `riscof run`, the architectural test suite failed on `bgeu-01.S` due to a simulation timeout in Verilator.

```
     0.00ns INFO     cocotb.regression                  running test_soc (1/1)
2000000.00ns ERROR    cocotb.soc_top                     Timeout waiting for tohost! (2000000 ns)
2000000.00ns INFO     cocotb.regression                  test_soc failed
```

**Localization**

- We first suspected the testbench timeout (`max_cycles = 200000`) was simply too small for RISCOF's massive test programs, which compile to >75k instructions. We increased it to 2,000,000 ns, but the test *still* timed out.
- By looking at the disassembled `.elf` and inspecting the compiled size of `bgeu-01.S`, we noticed it was over 300KB in size.
- A quick review of our SoC memories (`rtl/soc/imem.sv` and `dmem.sv`) showed that while we had instantiated 1MB blocks in `soc_top.sv`, the actual implementation of `imem.sv` had a hardcoded truncation in the array access: `read_data_o = mem[offset[17:2]];`.
- 18 bits of address space equals exactly 256KB!
- Because `bgeu-01.S` exceeded 256KB, the program counter wrapped around once it crossed `0x80040000`, fetching instructions from the beginning of the program instead of the actual test code, sending the processor into an infinite execution loop.

**Root cause**

The instruction memory `imem.sv` truncated addresses at 18 bits (`offset[17:2]`), restricting the maximum fetch range to 256KB regardless of the parameterized `MEM_SIZE`. When RISCOF compiled a test larger than 256KB, the PC silently wrapped around and executed the wrong instructions.

**Fix**

```diff
--- rtl/soc/imem.sv
+++ rtl/soc/imem.sv
@@ -26,3 +26,3 @@
     always_comb begin
-      read_data_o = mem[offset[17:2]];
+      read_data_o = mem[offset[31:2]];
     end
```

**Prevention**

RISCOF tests catch this immediately because their programs are generated dynamically and often span hundreds of kilobytes for exhaustive branch coverage. Our previous directed tests were less than a few kilobytes, so they never exercised the upper address space.

---

### Entry 3 — RISCOF `jal-01.S` memory Out-of-Bounds crash

**Symptom**

After fixing the instruction memory and running RISCOF again, the suite crashed on `jal-01.S`.

```
     0.00ns ERROR    gpi                                Invalid Index - Index 1048576 is not in the range of [0:1048575]
     0.00ns INFO     cocotb.regression                  test_soc failed
                                                        Traceback (most recent call last):
                                                          File "/mnt/c/Users/sai29/.gemini/antigravity/scratch/riscv-core-dv/tb/cocotb/test_soc_top.py", line 40, in load_elf
                                                            dut.u_dmem.mem[offset + i].value = data[i]
                                                        IndexError: mem(GPI_ARRAY) contains no object at index 1048576
```

**Localization**

- The `IndexError` occurred exactly at index `1,048,576` during ELF loading in `test_soc_top.py`.
- 1,048,576 is exactly 1MB.
- `jal-01.S` places a massive signature region at the end of its instructions. This test required memory just beyond the 1MB limit we had assigned to `dmem` in `soc_top.sv`.

**Root cause**

The data memory was parameterized to `1024 * 1024` (1MB). `jal-01.S` allocates data regions that push the required contiguous memory footprint beyond 1MB.

**Fix**

```diff
--- rtl/soc/soc_top.sv
+++ rtl/soc/soc_top.sv
@@ -32,3 +32,3 @@
   imem #(
-      .MEM_SIZE (1024 * 1024)
+      .MEM_SIZE (2097152)
   ) u_imem (
@@ -40,3 +40,3 @@
   dmem #(
-      .MEM_SIZE (1024 * 1024)
+      .MEM_SIZE (2097152)
   ) u_dmem (
```

**Prevention**

Memory bounds checks in Python via Cocotb correctly aborted simulation rather than silently ignoring out-of-bounds writes. The test size itself stresses the architectural configuration boundaries.

### Entry 4 — Cocotb/Verilator compatibility mismatch breaking simulation

**Symptom**

When running `make random` during the Phase 5 test generation and execution pipeline, the RTL compilation suddenly failed with a missing `verilator.cpp` file and a `WIDTHTRUNC` warning.

```text
--- riscv_arithmetic_basic_test_0
%Warning-WIDTHTRUNC: /root/riscv-core-dv/rtl/core/../soc/imem.sv:27:24: Bit extraction of array[524287:0] requires 19 bit index, not 30 bits.
...
make[4]: *** No rule to make target '/root/.local/lib/python3.14/site-packages/cocotb/share/lib/verilator/verilator.cpp', needed by 'verilator.o'.  Stop.
make[3]: *** [/root/riscv-core-dv/venv/lib/python3.10/site-packages/cocotb/share/makefiles/simulators/Makefile.verilator:68: sim_build/soc_top/Vtop] Error 2
```

**Localization**

- We initially thought `WIDTHTRUNC` was the fatal error causing the crash, but Verilator warnings typically don't halt make unless `-Werror` is set (which we disabled via `-Wno-fatal`).
- Looking closely at the `No rule to make target` error, Cocotb was trying to compile against a global `/root/.local/lib/python3.14/` installation despite us explicitly running inside a Python 3.10 `venv`. 
- However, after tracking down the exact `Makefile.verilator` trace, we noticed a critical line higher up in the logs:
  `cocotb requires Verilator 5.036 or later, but using 5.032. Stop.`
- The latest version of `cocotb` (2.0.1) silently required a newer version of Verilator than what was available in the system packages (5.032). This caused the Makefiles to break and attempt to fall back on missing `.cpp` shims.

**Root cause**

Incompatible toolchain versions. The virtual environment installed the latest `cocotb 2.0.1` package by default, which hard-requires Verilator >= 5.036, breaking the simulation compilation step against the system's Verilator 5.032.

**Fix**

```diff
- pip install cocotb cocotb-bus
+ pip install cocotb==1.9.2 cocotb-bus
```

We downgraded to `cocotb 1.9.2` which perfectly supports Verilator 5.032.

**Prevention**

This issue could be prevented by explicitly pinning versions in a `requirements.txt` file (`cocotb==1.9.2`) to ensure reproducible builds across different CI environments and developer machines.

---

### Entry 5 — WSL Read-Only kernel panic during final coverage extraction

**Symptom**

After successfully running 50,000 instructions of constrained-random tests in lockstep, the final step in the pipeline (`scripts/coverage.py`) silently failed to output any results.

```text
$ wsl -e bash -c "python3 scripts/coverage.py build/riscv_dv_out"
(silent exit with code 1)

$ wsl -e bash -c "cp /root/riscv-core-dv/build/riscv_dv_out/*.log* /mnt/c/.../"
cp: error writing '...': Input/output error
```

**Localization**

- First, we assumed `coverage.py` had a silent syntax error or was not matching the `__main__` block, but basic Python `print()` statements also failed to run.
- When we attempted to `cat` or `cp` the generated coverage log (`riscv_arithmetic_basic_test_0.rtl.log.cov`), we received `Input/output error`.
- Running standard system commands like `ps aux` also resulted in `bash: /usr/bin/ps: Input/output error`.
- Finally, attempting to write a simple text file returned: `bash: /root/cov_out.txt: Read-only file system`.

**Root cause**

The underlying Windows Subsystem for Linux (WSL2) virtual machine suffered a catastrophic kernel I/O panic (likely due to the intense disk I/O and memory usage of Verilator simulating 50k instructions rapidly). To protect the virtual `.vhdx` disk from corruption, the Linux kernel remounted the entire `/` filesystem as `Read-Only`, blocking Python from executing and preventing our scripts from reading the 6.8MB coverage trace.

**Fix**

A hard shutdown of the virtual machine from the Windows host (`wsl --shutdown`) was required to reboot the kernel and restore read-write access to the filesystem.

**Prevention**

This is an infrastructure-level failure outside the scope of RTL verification. To mitigate this in a production environment, CI pipelines should run natively on Linux containers or bare-metal runners rather than virtualization wrappers like WSL, which are prone to I/O exhaustion under heavy compile/simulation loads.

---

### Entry 6 — SymbiYosys Formal Verification `PREUNSAT` on `imem_read_data` initialization

**Symptom**

During Phase 6 (Formal Verification), the `riscv-formal` proof engine failed on all instruction semantic checks (e.g., `insn_add_ch0`, `insn_beq_ch0`) with a `PREUNSAT` error before completing a single step of bounded model checking.

```
SBY 18:05:49 [insn_add_ch0] engine_0: ##   0:00:00  Checking assumptions in step 10..
SBY 18:05:49 [insn_add_ch0] engine_0: ##   0:00:00  Assumptions are unsatisfiable!
SBY 18:05:49 [insn_add_ch0] engine_0: ##   0:00:00  Status: PREUNSAT
SBY 18:05:49 [insn_add_ch0] engine_0: finished (returncode=1)
```

**Localization**

- `PREUNSAT` means the formal solver found the constraints (assumptions) contradictory or impossible to satisfy, preventing it from even generating a valid starting state.
- `riscv-formal` assumes that the core will eventually fetch and retire the specific instruction under test (e.g., `ADD`).
- I checked `formal/wrapper.sv`, which instantiates the core and wires it to `riscv-formal`. The instruction memory and data memory data input signals (`imem_read_data` and `dmem_rdata`) were declared and initialized to zero:
  `logic [31:0] imem_read_data = '0;`
- Because there was no logic driving these signals, the synthesizer treated them as constant `0x00000000`.
- The formal solver was trying to find a path where the CPU fetches an `ADD` instruction, but the CPU could only ever fetch `0x00000000` (which is not a valid `ADD` instruction), making the solver's goal impossible to reach.

**Root cause**

Memory input signals in the formal wrapper were initialized to `'0`, forcing them to a constant zero. Formal verification requires unconstrained external inputs so the solver can arbitrarily explore all possible instruction sequences.

**Fix**

```diff
--- formal/wrapper.sv
+++ formal/wrapper.sv
@@ -8,3 +8,3 @@
   logic [31:0] imem_req_addr;
-  logic [31:0] imem_read_data = '0;
-  logic        imem_error = '0;
+  (* anyseq *) logic [31:0] imem_read_data;
+  (* anyseq *) logic        imem_error;
```

**Prevention**

Understanding the formal semantics of `(* anyseq *)` variables ensures that external stimulus is correctly marked as free variables for the SMT solver. Simulation testbenches drive inputs explicitly, whereas formal harnesses require inputs to remain unassigned unless explicitly constrained by `assume()`.

### Entry 7 — Misdiagnosed concurrency bugs that were actually a failing filesystem

**Symptom**

Multiple failures during RISCOF test execution on WSL:

1. `make arch` hanging on `git cat-file` inside `riscv-arch-test`
2. `results.xml was not written by the simulation!` after cocotb runs
3. `Vtop` binary corruption (`Can not find root handle`)
4. `Read-only file system` errors on all writes

```
[  922.668797] EXT4-fs warning (device sdd): ext4_end_bio:368: I/O error 10 writing to inode 942
[  922.672329] EXT4-fs error (device sdd): ext4_journal_check_start:87: Detected aborted journal
[  922.672597] EXT4-fs (sdd): Remounting filesystem read-only
```

**Localization**

- Symptom 1 was initially attributed to git contention in riscv-arch-test, and
  the `.git` directory was moved to `.git.bak` as a workaround.
- Symptom 2 was attributed to concurrent cocotb runs sharing a `results.xml`
  file, and `config.ini` was changed from `jobs=8` to `jobs=1`.
- Symptom 3 was attributed to concurrent Verilator compilations sharing a build
  directory. This diagnosis was **independently correct** — the per-test
  `SIM_BUILD` fix reproduces on healthy hardware.
- Symptom 4 made the real cause obvious: `dmesg` showed EXT4 I/O errors on
  `/dev/sdd`, journal abort, and automatic read-only remount.

The key insight was that hanging I/O, silently dropped writes, and corrupted
binaries are the textbook signature of a dying ext4 volume. Symptoms 1, 2, and
4 were all manifestations of the same root cause. Only symptom 3 had an
independent explanation.

**Root cause**

The WSL2 virtual disk (`ext4.vhdx`) suffered I/O block errors under the heavy
write load of concurrent Verilator compilations. The ext4 filesystem detected
the journal corruption and remounted as read-only to prevent data loss. This
was the third such filesystem failure during the project.

**Fix**

No fix for the filesystem itself — the WSL instance is unrecoverable. The
strategic fix is moving all verification to GitHub Actions CI, which runs on
fresh, disposable `ubuntu-24.04` runners that cannot accumulate disk damage.

**Prevention**

1. Never run heavy simulation workloads on WSL virtual disks for extended
   periods. Use native Linux or CI runners.
2. When multiple failures appear simultaneously, consider whether they share a
   common infrastructure cause before diagnosing each independently.
3. A workaround built on a wrong diagnosis becomes permanent damage — the
   `.git.bak` and `jobs=1` changes would have been carried forward indefinitely
   if the disk had not failed hard enough to make the real cause visible.
