#!/usr/bin/env python3
"""
Spike lockstep comparator -- the heart of the whole project.

WHAT THIS DOES
--------------
Spike (the official RISC-V golden model) is run over the same ELF as the RTL.
Both produce a trace of *retired* instructions. This script diffs those traces
and reports the FIRST divergence with enough context to go straight to a
waveform.

Why "first divergence" and not "all divergences": once architectural state
differs by one bit, every subsequent instruction is executing from a corrupted
machine and the remaining thousands of mismatches are noise. The first one is
the bug. Everything after it is a consequence.

TRACE FORMATS
-------------
Spike, invoked with --log-commits, emits lines like:

    core   0: 3 0x0000000080000000 (0x00000297) x5  0x0000000080000000
    core   0: 3 0x0000000080000004 (0x00028067)
    core   0: 3 0x0000000080000008 (0x00a02223) mem 0x80001000 0x0000000a

Meaning: hart 0, privilege 3, PC, (encoding), then an optional writeback
(register or memory).

Your RTL must emit a much simpler line per retired instruction:

    <pc_hex> <insn_hex> <rd_dec> <rd_wdata_hex>

e.g.

    80000000 00000297 5 80000000
    80000004 00028067 0 00000000

rd = 0 means "no architectural register write" (which is also literally true,
since x0 is hardwired). Emit this from your writeback stage, gated on the
instruction actually retiring -- NOT on it being fetched. Instructions that are
flushed by a branch misprediction must never appear in this log; if they do,
that is itself the bug the comparator will find.

USAGE
-----
    python3 spike_compare.py --elf prog.elf --rtl-log prog.rtl.log
    python3 spike_compare.py --selftest        # verify the comparator itself
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass


# -----------------------------------------------------------------------------
# Trace representation
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Retire:
    """One retired instruction's architecturally visible effect."""

    pc: int
    insn: int
    rd: int          # 0 == no register writeback
    rd_value: int

    def __str__(self) -> str:
        wb = "-" if self.rd == 0 else f"x{self.rd}=0x{self.rd_value:08x}"
        return f"pc=0x{self.pc:08x} insn=0x{self.insn:08x} {wb}"


# -----------------------------------------------------------------------------
# Spike log parsing
# -----------------------------------------------------------------------------
# core   0: 3 0x0000000080000000 (0x00000297) x5  0x0000000080000000
_SPIKE_RE = re.compile(
    r"^core\s+\d+:\s+\d+\s+"
    r"0x(?P<pc>[0-9a-fA-F]+)\s+"
    r"\((?P<insn>0x[0-9a-fA-F]+)\)"
    r"(?:\s+x\s*(?P<rd>\d+)\s+0x(?P<val>[0-9a-fA-F]+))?"
)


def parse_spike_log(text: str) -> list[Retire]:
    out: list[Retire] = []
    for line in text.splitlines():
        m = _SPIKE_RE.match(line.strip())
        if not m:
            continue  # skip banners, mem-only lines, csr lines
        rd = int(m.group("rd")) if m.group("rd") else 0
        val = int(m.group("val"), 16) if m.group("val") else 0
        out.append(
            Retire(
                pc=int(m.group("pc"), 16) & 0xFFFFFFFF,
                insn=int(m.group("insn"), 16) & 0xFFFFFFFF,
                rd=rd,
                rd_value=val & 0xFFFFFFFF,
            )
        )
    return out


# -----------------------------------------------------------------------------
# RTL log parsing
# -----------------------------------------------------------------------------
def parse_rtl_log(text: str) -> list[Retire]:
    out: list[Retire] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(
                f"RTL log line {lineno} malformed: {line!r}\n"
                f"expected: <pc_hex> <insn_hex> <rd_dec> <rd_wdata_hex>"
            )
        pc, insn, rd, val = parts
        out.append(
            Retire(
                pc=int(pc, 16) & 0xFFFFFFFF,
                insn=int(insn, 16) & 0xFFFFFFFF,
                rd=int(rd, 10),
                rd_value=int(val, 16) & 0xFFFFFFFF,
            )
        )
    return out


# -----------------------------------------------------------------------------
# Running Spike
# -----------------------------------------------------------------------------
def run_spike(elf: str, isa: str = "rv32imc", max_instr: int = 200_000) -> list[Retire]:
    spike = shutil.which("spike")
    if spike is None:
        raise RuntimeError(
            "spike not found on PATH. Run ./scripts/setup.sh then "
            "'source scripts/env.sh'."
        )
    with tempfile.NamedTemporaryFile("w+", suffix=".spike.log", delete=False) as fh:
        log_path = fh.name
    try:
        subprocess.run(
            [
                spike,
                f"--isa={isa}",
                "--pc=0x80000000",
                "--log-commits",
                f"--instructions={max_instr}",
                f"--log={log_path}",
                elf,
            ],
            check=False,               # spike exits non-zero on tohost writes
            capture_output=True,
            text=True,
            timeout=600,
        )
        with open(log_path) as fh:
            return parse_spike_log(fh.read())
    finally:
        os.unlink(log_path)


# -----------------------------------------------------------------------------
# The diff
# -----------------------------------------------------------------------------
def compare(rtl: list[Retire], ref: list[Retire], context: int = 8) -> int:
    """Return 0 if traces agree, 1 otherwise. Prints a debuggable report."""
    n = min(len(rtl), len(ref))

    for i in range(n):
        if rtl[i] != ref[i]:
            print("=" * 72)
            print(f"MISMATCH at retired instruction #{i}")
            print("=" * 72)
            lo = max(0, i - context)
            print(f"\n--- last {i - lo} matching instruction(s) ---")
            for j in range(lo, i):
                print(f"  #{j:<6} {ref[j]}")

            print("\n--- divergence ---")
            print(f"  RTL   : {rtl[i]}")
            print(f"  SPIKE : {ref[i]}")

            reasons = []
            if rtl[i].pc != ref[i].pc:
                reasons.append(
                    "PC differs -> control flow bug (branch/jump target, or a "
                    "flushed instruction was allowed to retire)"
                )
            if rtl[i].insn != ref[i].insn:
                reasons.append(
                    "INSTRUCTION differs at the same PC -> fetch/memory bug, or "
                    "your imem model and Spike disagree about program layout"
                )
            if rtl[i].rd != ref[i].rd:
                reasons.append(
                    "DESTINATION REGISTER differs -> decoder bug (wrong rd field "
                    "or wrong regfile write-enable)"
                )
            elif rtl[i].rd_value != ref[i].rd_value:
                delta = rtl[i].rd_value ^ ref[i].rd_value
                reasons.append(
                    f"WRITEBACK VALUE differs (xor=0x{delta:08x}) -> execute or "
                    f"forwarding bug. If only the low bits differ suspect the "
                    f"ALU; if the value equals an OLDER value of that register, "
                    f"suspect a missing forwarding path."
                )
            print("\n--- likely cause ---")
            for r in reasons:
                print(f"  * {r}")

            print(f"\n--- next {min(context, len(ref) - i - 1)} SPIKE instruction(s) ---")
            for j in range(i + 1, min(len(ref), i + 1 + context)):
                print(f"  #{j:<6} {ref[j]}")

            print(
                f"\nOpen the waveform and go to retired instruction #{i} "
                f"(pc=0x{ref[i].pc:08x}).\n"
            )
            return 1

    if len(rtl) < len(ref):
        print(f"MATCH: {len(rtl)} retired instructions identical to Spike. (Spike continued for {len(ref) - len(rtl)} more instructions)")
        return 0
    elif len(rtl) > len(ref):
        print("=" * 72)
        print("TRACE LENGTH MISMATCH (all compared instructions agreed)")
        print("=" * 72)
        print(f"  RTL retired  : {len(rtl)}")
        print(f"  SPIKE retired: {len(ref)}")
        print(
            "\n  RTL retired MORE than Spike. Usual cause: instructions that "
            "should have been flushed after a taken branch are retiring."
        )
        print(f"  First extra: {rtl[len(ref)]}")
        return 1

    print(f"MATCH: {len(ref)} retired instructions identical to Spike.")
    return 0


# -----------------------------------------------------------------------------
# Self-test -- proves the comparator itself works before you trust it
# -----------------------------------------------------------------------------
def selftest() -> int:
    spike_log = """\
core   0: 3 0x0000000080000000 (0x00000297) x5  0x0000000080000000
core   0: 3 0x0000000080000004 (0x00550513) x10 0x0000000080000005
core   0: 3 0x0000000080000008 (0x00028067)
"""
    ref = parse_spike_log(spike_log)
    assert len(ref) == 3, ref
    assert ref[0] == Retire(0x80000000, 0x00000297, 5, 0x80000000)
    assert ref[2].rd == 0

    good = parse_rtl_log(
        "80000000 00000297 5 80000000\n"
        "80000004 00550513 10 80000005\n"
        "80000008 00028067 0 0\n"
    )
    assert compare(good, ref) == 0, "identical traces must compare equal"

    bad_value = parse_rtl_log(
        "80000000 00000297 5 80000000\n"
        "80000004 00550513 10 80000004\n"   # off by one
        "80000008 00028067 0 0\n"
    )
    assert compare(bad_value, ref) == 1, "value mismatch must be detected"

    short = parse_rtl_log("80000000 00000297 5 80000000\n")
    assert compare(short, ref) == 1, "short trace must be detected"

    print("\nself-test: OK -- parser and comparator behave correctly")
    return 0


# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--elf", help="program to run on Spike")
    ap.add_argument("--rtl-log", help="trace produced by the RTL testbench")
    ap.add_argument("--spike-log", help="use a pre-existing spike log instead of running spike")
    ap.add_argument("--isa", default="rv32imc")
    ap.add_argument("--max-instr", type=int, default=200_000)
    ap.add_argument("--context", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.rtl_log:
        ap.error("--rtl-log is required (or use --selftest)")

    with open(args.rtl_log) as fh:
        rtl = parse_rtl_log(fh.read())

    if args.spike_log:
        with open(args.spike_log) as fh:
            ref = parse_spike_log(fh.read())
    elif args.elf:
        ref = run_spike(args.elf, isa=args.isa, max_instr=args.max_instr)
    else:
        ap.error("provide --elf or --spike-log")

    return compare(rtl, ref, context=args.context)


if __name__ == "__main__":
    sys.exit(main())
