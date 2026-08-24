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

--------------------------------------------------------------------------
THE TRACE-LENGTH PROBLEM, AND WHY THE OBVIOUS FIX IS WRONG
--------------------------------------------------------------------------
Spike does not stop when the test program writes `tohost`. It keeps retiring
instructions inside the `j _halt` loop in sw/crt0.S until its --instructions
budget runs out. The RTL testbench, by contrast, stops the moment it sees the
tohost write. So Spike's trace is legitimately LONGER than the RTL's on every
single passing test.

The tempting fix is to treat any short RTL trace as a pass. **Do not do this.**
It silently converts every one of these into a green run:

    * the core hung on a hazard and stopped making progress
    * the testbench cycle limit fired before the program finished
    * the core took an unexpected trap and stalled
    * the program never reached its end-of-test tohost write at all

A comparator that cannot tell "finished successfully" from "died on instruction
four" is worse than no comparator, because it will be trusted.

The fix implemented here distinguishes those cases by *why* the RTL stopped:

    1. The testbench appends a TERMINATION MARKER to the retire log saying how
       the run ended (see tb/cocotb/retire_log.py).
    2. A short RTL trace is accepted ONLY when that marker says the run ended on
       a tohost write.
    3. Even then, the surplus Spike instructions are validated as harmless: they
       must perform no architectural register writes and must span only a couple
       of distinct PCs -- i.e. they must genuinely be the halt loop. If Spike did
       real work after the RTL stopped, the RTL terminated early and that is a
       bug.
    4. No marker plus a short trace is a FAILURE. There is deliberately no flag
       to disable this. If your logs predate the marker, regenerate them.

TRACE FORMATS
-------------
Spike, invoked with --log-commits, emits lines like:

    core   0: 3 0x0000000080000000 (0x00000297) x5  0x0000000080000000
    core   0: 3 0x0000000080000004 (0x00028067)

The RTL testbench emits one line per retired instruction:

    <pc_hex> <insn_hex> <rd_dec> <rd_wdata_hex>
    80000000 00000297 5 80000000
    80000004 00028067 0 00000000

followed by exactly one terminator line:

    # TERMINATED reason=tohost tohost=0x00000001 cycles=8421 retired=1337
    # TERMINATED reason=timeout cycles=200000 retired=54321
    # TERMINATED reason=abort detail=trap_loop cycles=91 retired=12

rd = 0 means "no architectural register write" (also literally true, since x0 is
hardwired). Emit retire lines from the writeback stage gated on the instruction
actually RETIRING -- not on it being fetched. Instructions flushed by a taken
branch must never appear.

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


@dataclass(frozen=True)
class Termination:
    """How the RTL run ended, per the testbench's terminator line."""

    reason: str                 # "tohost" | "timeout" | "abort"
    tohost: int | None = None
    cycles: int | None = None
    retired: int | None = None
    detail: str = ""

    @property
    def clean(self) -> bool:
        """True only when the program reached its end-of-test tohost write."""
        return self.reason == "tohost" and self.tohost is not None

    @property
    def test_passed(self) -> bool:
        """crt0.S encodes tohost = (exit_code << 1) | 1, so 1 means pass."""
        return self.tohost == 1

    def __str__(self) -> str:
        bits = [f"reason={self.reason}"]
        if self.tohost is not None:
            bits.append(f"tohost=0x{self.tohost:08x}")
        if self.cycles is not None:
            bits.append(f"cycles={self.cycles}")
        if self.retired is not None:
            bits.append(f"retired={self.retired}")
        if self.detail:
            bits.append(f"detail={self.detail}")
        return " ".join(bits)


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
            if "core" in line.strip() and "0x" in line.strip():
                print(f"DEBUG_SPIKE_UNMATCHED: {line.strip()}")
            continue  # banners, mem-only lines, csr lines
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
_TERM_RE = re.compile(r"^#\s*TERMINATED\s+(?P<kv>.*)$")


def _parse_int(s: str) -> int | None:
    try:
        return int(s, 0)
    except ValueError:
        return None


def parse_rtl_log(text: str) -> tuple[list[Retire], Termination | None]:
    """Return (retired instructions, termination marker or None)."""
    out: list[Retire] = []
    term: Termination | None = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#"):
            m = _TERM_RE.match(line)
            if m:
                fields: dict[str, str] = {}
                for tok in m.group("kv").split():
                    if "=" in tok:
                        k, _, v = tok.partition("=")
                        fields[k.strip()] = v.strip()
                if term is not None:
                    raise ValueError(
                        f"RTL log line {lineno}: a second TERMINATED marker. "
                        f"The testbench must emit exactly one."
                    )
                term = Termination(
                    reason=fields.get("reason", "unknown"),
                    tohost=_parse_int(fields["tohost"]) if "tohost" in fields else None,
                    cycles=_parse_int(fields["cycles"]) if "cycles" in fields else None,
                    retired=_parse_int(fields["retired"]) if "retired" in fields else None,
                    detail=fields.get("detail", ""),
                )
            continue  # all other comments ignored

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

    return out, term


# -----------------------------------------------------------------------------
# Running Spike
# -----------------------------------------------------------------------------
def run_spike(elf: str, isa: str = "rv32i", max_instr: int = 200_000) -> list[Retire]:
    spike = shutil.which("spike")
    if spike is None:
        raise RuntimeError(
            "spike not found on PATH. Run ./scripts/setup.sh then "
            "'source scripts/env.sh'."
        )
    with tempfile.NamedTemporaryFile("w+", suffix=".spike.log", delete=False) as fh:
        log_path = fh.name
    try:
        proc = subprocess.run(
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
            file_out = fh.read()
            out = parse_spike_log(file_out if file_out.strip() else proc.stderr)
            if not out:
                import sys
                print(f"SPIKE FAILURE DEBUG:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}\nfile:\n{file_out}", file=sys.stderr)
            return out
    finally:
        os.unlink(log_path)


# -----------------------------------------------------------------------------
# Tail validation
# -----------------------------------------------------------------------------
def _describe_tail(tail: list[Retire], limit: int = 6) -> str:
    return "\n".join(f"    #{i:<5} {r}" for i, r in enumerate(tail[:limit]))


def validate_halt_tail(
    tail: list[Retire], max_distinct_pcs: int = 4
) -> tuple[bool, str]:
    """
    Spike's surplus instructions must genuinely be the post-tohost halt loop.

    Two independent checks, because either alone is foolable:

      * no architectural register writes -- `j _halt` is `jal x0, 0`, so a
        writeback in the tail means real computation happened
      * few distinct PCs -- the halt loop is one or two addresses; a spread of
        addresses means the program carried on doing work

    If either fails, the RTL stopped BEFORE the program was actually finished
    and the tohost write it saw was premature. That is a bug in the core or the
    testbench, not an artefact of Spike over-running.
    """
    if not tail:
        return True, ""

    writers = [r for r in tail if r.rd != 0]
    if writers:
        return False, (
            f"{len(writers)} of the {len(tail)} surplus Spike instruction(s) "
            f"write architectural registers, so Spike was still doing real work "
            f"after the RTL stopped.\n  First such instruction:\n"
            f"    {writers[0]}"
        )

    pcs = {r.pc for r in tail}
    if len(pcs) > max_distinct_pcs:
        return False, (
            f"the {len(tail)} surplus Spike instruction(s) span {len(pcs)} "
            f"distinct PCs (limit {max_distinct_pcs}); a halt loop spans one or "
            f"two. Spike was still executing real code after the RTL stopped."
        )

    return True, ""


# -----------------------------------------------------------------------------
# The diff
# -----------------------------------------------------------------------------
def compare(
    rtl: list[Retire],
    ref: list[Retire],
    termination: Termination | None = None,
    context: int = 8,
    max_distinct_tail_pcs: int = 4,
) -> int:
    """Return 0 if the run is good, 1 otherwise. Prints a debuggable report."""
    n = min(len(rtl), len(ref))

    # -- instruction-by-instruction divergence --------------------------------
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
                    "the imem model and Spike disagree about program layout"
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
                    f"forwarding bug. If only low bits differ suspect the ALU; "
                    f"if the value equals an OLDER value of that register, "
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

    # -- RTL retired MORE than Spike ------------------------------------------
    if len(rtl) > len(ref):
        print("=" * 72)
        print("RTL RETIRED MORE INSTRUCTIONS THAN SPIKE")
        print("=" * 72)
        if len(ref) == 0:
            print("--- SPIKE LOG HEAD ---")
            try:
                import sys
                print("raw spike output was empty or didn't match regex", file=sys.stderr)
            except Exception: pass
        print(f"  RTL retired  : {len(rtl)}")
        print(f"  SPIKE retired: {len(ref)}")
        print(
            "\n  Usual cause: instructions that should have been flushed after a "
            "\n  taken branch are reaching the retire trace. Gate the trace on "
            "\n  actual retirement, not on fetch or decode."
        )
        print(f"  First extra: {rtl[len(ref)]}")
        return 1

    # -- RTL retired FEWER than Spike -----------------------------------------
    if len(rtl) < len(ref):
        missing = len(ref) - len(rtl)

        if termination is None:
            print("=" * 72)
            print("RTL STOPPED EARLY -- NO TERMINATION MARKER")
            print("=" * 72)
            print(f"  RTL retired  : {len(rtl)}")
            print(f"  SPIKE retired: {len(ref)}  ({missing} more)")
            print(
                "\n  The RTL trace is short and the testbench did not record why "
                "\n  the run ended, so this cannot be distinguished from a hang."
                "\n"
                "\n  Emit a terminator line from the testbench (see"
                "\n  tb/cocotb/retire_log.py):"
                "\n      # TERMINATED reason=tohost tohost=0x00000001 ..."
                "\n"
                "\n  Until then this is a FAILURE by design. A missing marker is "
                "\n  never assumed benign."
            )
            if len(rtl) < len(ref):
                print(f"\n  Next expected: {ref[len(rtl)]}")
            return 1

        if not termination.clean:
            print("=" * 72)
            print("RTL STOPPED EARLY -- RUN DID NOT COMPLETE")
            print("=" * 72)
            print(f"  Termination  : {termination}")
            print(f"  RTL retired  : {len(rtl)}")
            print(f"  SPIKE retired: {len(ref)}  ({missing} more)")
            if termination.reason == "timeout":
                print(
                    "\n  The testbench cycle limit fired before the program wrote "
                    "\n  tohost. Either the core hung -- check for a stall "
                    "\n  condition that never clears -- or the limit is too low "
                    "\n  for this program."
                )
            else:
                print(
                    "\n  The run was aborted before reaching the program's "
                    "\n  end-of-test tohost write."
                )
            print(f"\n  Next expected: {ref[len(rtl)]}")
            return 1

        # Clean tohost termination: the surplus must be the halt loop.
        tail = ref[len(rtl):]
        ok, why = validate_halt_tail(tail, max_distinct_pcs=max_distinct_tail_pcs)
        if not ok:
            print("=" * 72)
            print("RTL TERMINATED PREMATURELY")
            print("=" * 72)
            print(f"  Termination  : {termination}")
            print(f"  RTL retired  : {len(rtl)}")
            print(f"  SPIKE retired: {len(ref)}  ({missing} more)")
            print(f"\n  The RTL reported a clean tohost write, but {why}")
            print("\n--- surplus SPIKE instructions ---")
            print(_describe_tail(tail))
            print(
                "\n  Something wrote the tohost address before the program was "
                "\n  finished -- a stray store, a wrong address decode, or a "
                "\n  testbench that matches too broadly."
            )
            return 1

        if not termination.test_passed:
            code = (termination.tohost or 0) >> 1
            print("=" * 72)
            print("TEST PROGRAM REPORTED FAILURE")
            print("=" * 72)
            print(f"  Termination  : {termination}")
            print(
                f"\n  The traces agree with Spike, so the CORE is behaving "
                f"\n  correctly -- but the program itself failed check #{code}."
                f"\n  tohost = (exit_code << 1) | 1, so 1 means pass."
                f"\n"
                f"\n  Look at the test source, not the RTL."
            )
            return 1

        print(
            f"MATCH: {len(rtl)} retired instructions identical to Spike.\n"
            f"  Clean termination: {termination}\n"
            f"  Spike ran {missing} further instruction(s) in the halt loop "
            f"(no register writes, {len({r.pc for r in tail})} distinct PC(s)) "
            f"-- expected, since Spike does not stop at tohost."
        )
        return 0

    # -- Equal lengths ---------------------------------------------------------
    if termination is not None and termination.clean and not termination.test_passed:
        code = (termination.tohost or 0) >> 1
        print("=" * 72)
        print("TEST PROGRAM REPORTED FAILURE")
        print("=" * 72)
        print(f"  Termination  : {termination}")
        print(f"\n  Traces agree with Spike; the program failed check #{code}.")
        return 1

    print(f"MATCH: {len(ref)} retired instructions identical to Spike.")
    if termination is not None:
        print(f"  Termination: {termination}")
    return 0


# -----------------------------------------------------------------------------
# Self-test -- proves the comparator works before anything trusts it
# -----------------------------------------------------------------------------
_SPIKE_LOG = """\
core   0: 3 0x0000000080000000 (0x00000297) x5  0x0000000080000000
core   0: 3 0x0000000080000004 (0x00550513) x10 0x0000000080000005
core   0: 3 0x0000000080000008 (0x00a02223)
core   0: 3 0x000000008000000c (0x0000006f)
core   0: 3 0x000000008000000c (0x0000006f)
core   0: 3 0x000000008000000c (0x0000006f)
"""

_RTL_FULL = (
    "80000000 00000297 5 80000000\n"
    "80000004 00550513 10 80000005\n"
    "80000008 00a02223 0 0\n"
)

_TERM_OK = "# TERMINATED reason=tohost tohost=0x00000001 cycles=42 retired=3\n"


def _case(name: str, rtl_text: str, ref, expect: int) -> None:
    rtl, term = parse_rtl_log(rtl_text)
    got = compare(rtl, ref, term)
    status = "ok" if got == expect else "WRONG"
    print(f"\n>>> selftest [{status}] {name}: expected {expect}, got {got}\n")
    assert got == expect, (
        f"self-test case {name!r} returned {got}, expected {expect}. "
        f"The comparator is not behaving correctly -- do NOT trust any lockstep "
        f"result until this passes."
    )


def selftest() -> int:
    ref = parse_spike_log(_SPIKE_LOG)
    assert len(ref) == 6, ref
    assert ref[0] == Retire(0x80000000, 0x00000297, 5, 0x80000000)
    assert ref[2].rd == 0

    # 1. Identical prefix + clean tohost termination + halt-loop tail -> PASS.
    _case("clean run, Spike over-runs into halt loop", _RTL_FULL + _TERM_OK, ref, 0)

    # 2. A value mismatch is still caught.
    _case(
        "writeback value differs",
        "80000000 00000297 5 80000000\n"
        "80000004 00550513 10 80000004\n"      # off by one
        "80000008 00a02223 0 0\n" + _TERM_OK,
        ref,
        1,
    )

    # 3. THE REGRESSION GUARD. Short trace, no marker -> FAIL.
    #    A previous revision returned 0 here, which made every hang and every
    #    testbench timeout report success.
    _case("short trace with NO terminator (hang)", "80000000 00000297 5 80000000\n", ref, 1)

    # 4. Short trace with a timeout marker -> FAIL.
    _case(
        "short trace, testbench timed out",
        "80000000 00000297 5 80000000\n"
        "# TERMINATED reason=timeout cycles=200000 retired=1\n",
        ref,
        1,
    )

    # 5. Short trace claiming clean tohost, but Spike kept doing real work
    #    (register writes in the tail) -> premature termination, FAIL.
    _case(
        "premature tohost -- Spike still writing registers",
        "80000000 00000297 5 80000000\n"
        "# TERMINATED reason=tohost tohost=0x00000001 cycles=10 retired=1\n",
        ref,
        1,
    )

    # 6. RTL retired more than Spike -> flushed instructions retiring, FAIL.
    _case(
        "RTL retired more than Spike",
        _RTL_FULL
        + "8000000c 0000006f 0 0\n"
          "80000010 00000013 1 1\n"
          "80000014 00000013 2 2\n"
          "80000018 00000013 3 3\n"
          "8000001c 00000013 4 4\n" + _TERM_OK,
        ref,
        1,
    )

    # 7. Clean termination but the program itself failed (tohost != 1) -> FAIL.
    _case(
        "core correct, test program failed",
        _RTL_FULL
        + "# TERMINATED reason=tohost tohost=0x00000007 cycles=42 retired=3\n",
        ref,
        1,
    )

    # 8. Exact-length match with a clean pass marker -> PASS.
    short_ref = parse_spike_log(
        "\n".join(_SPIKE_LOG.splitlines()[:3]) + "\n"
    )
    _case("exact length match", _RTL_FULL + _TERM_OK, short_ref, 0)

    # 9. Two terminator lines is a malformed log, not a pass.
    try:
        parse_rtl_log(_RTL_FULL + _TERM_OK + _TERM_OK)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate TERMINATED markers must be rejected")

    print("\n" + "=" * 72)
    print("self-test: OK -- 9/9 cases behave correctly")
    print("  A short RTL trace without a termination marker FAILS, which is the")
    print("  property that makes every lockstep result meaningful.")
    print("=" * 72)
    return 0


# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--elf", help="program to run on Spike")
    ap.add_argument("--rtl-log", help="trace produced by the RTL testbench")
    ap.add_argument("--spike-log", help="pre-existing spike log instead of running spike")
    ap.add_argument("--isa", default="rv32i")
    ap.add_argument("--max-instr", type=int, default=200_000)
    ap.add_argument("--context", type=int, default=8)
    ap.add_argument(
        "--max-tail-pcs", type=int, default=4,
        help="distinct PCs permitted in Spike's post-tohost tail (default 4)",
    )
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.rtl_log:
        ap.error("--rtl-log is required (or use --selftest)")

    with open(args.rtl_log) as fh:
        rtl, termination = parse_rtl_log(fh.read())

    if args.spike_log:
        with open(args.spike_log) as fh:
            ref = parse_spike_log(fh.read())
    elif args.elf:
        ref = run_spike(args.elf, isa=args.isa, max_instr=args.max_instr)
    else:
        ap.error("provide --elf or --spike-log")

    return compare(
        rtl, ref, termination,
        context=args.context,
        max_distinct_tail_pcs=args.max_tail_pcs,
    )


if __name__ == "__main__":
    sys.exit(main())
