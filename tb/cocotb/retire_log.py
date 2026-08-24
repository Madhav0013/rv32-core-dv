"""
Retire-trace writer for the RTL testbench.

Produces the log that tb/lockstep/spike_compare.py consumes: one line per
retired instruction, followed by exactly one terminator line recording HOW the
run ended.

WHY THE TERMINATOR EXISTS
-------------------------
Spike does not stop when the test program writes `tohost` -- it keeps retiring
instructions in the `j _halt` loop until its instruction budget runs out. So on
every passing test Spike's trace is legitimately longer than the RTL's.

Without a record of why the RTL stopped, "shorter than Spike" is ambiguous
between "finished normally" and "hung on instruction four". The comparator
refuses to guess: a short trace with no terminator is a FAILURE. This class is
what makes the difference recordable.

GUARANTEE
---------
Used as a context manager, this class ALWAYS writes a terminator -- including
when the test raises. A log that stops mid-run because the simulator crashed
still says so, and the comparator still fails it. There is no path that produces
a silently-truncated log.

USAGE
-----
    from retire_log import RetireLogger

    with RetireLogger(os.environ["RTL_LOG"]) as trace:
        while True:
            await RisingEdge(dut.clk_i)
            cycles += 1

            # one line per RETIRED instruction -- gate on retirement, never on
            # fetch, or flushed instructions will pollute the trace
            if dut.rvfi_valid.value == 1:
                trace.log(
                    pc=int(dut.rvfi_pc_rdata.value),
                    insn=int(dut.rvfi_insn.value),
                    rd=int(dut.rvfi_rd_addr.value),
                    rd_value=int(dut.rvfi_rd_wdata.value),
                )

            if wrote_tohost:
                trace.terminate_tohost(tohost_value, cycles=cycles)
                break

            if cycles >= CYCLE_LIMIT:
                trace.terminate_timeout(cycles=cycles)
                break
"""

from __future__ import annotations

import os
from types import TracebackType


class RetireLogger:
    """Writes a retire trace plus exactly one terminator line."""

    def __init__(self, path: str, flush_every: int = 1024) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._fh = open(path, "w")
        self._path = path
        self._count = 0
        self._flush_every = flush_every
        self._terminated = False

    # -- retire lines ---------------------------------------------------------
    def log(self, pc: int, insn: int, rd: int, rd_value: int) -> None:
        """Record one retired instruction.

        `rd` must be 0 when the instruction performs no architectural register
        write. Do not special-case x0 here -- if the RTL asserts reg_write with
        rd=x0 that is still rd=0 architecturally, and the comparator expects the
        architectural view.
        """
        if self._terminated:
            raise RuntimeError(
                "retire logged after termination -- the testbench kept running "
                "past the point it declared the run over"
            )
        self._fh.write(
            f"{pc & 0xFFFFFFFF:08x} {insn & 0xFFFFFFFF:08x} "
            f"{rd & 0x1F} {rd_value & 0xFFFFFFFF:08x}\n"
        )
        self._count += 1
        if self._count % self._flush_every == 0:
            self._fh.flush()

    @property
    def retired(self) -> int:
        return self._count

    # -- termination ----------------------------------------------------------
    def _terminate(self, reason: str, **fields: object) -> None:
        if self._terminated:
            return  # first terminator wins; never emit two
        parts = [f"reason={reason}"]
        for key, value in fields.items():
            if value is None:
                continue
            if key == "tohost" and isinstance(value, int):
                parts.append(f"tohost=0x{value & 0xFFFFFFFF:08x}")
            else:
                parts.append(f"{key}={value}")
        parts.append(f"retired={self._count}")
        self._fh.write("# TERMINATED " + " ".join(parts) + "\n")
        self._fh.flush()
        self._terminated = True

    def terminate_tohost(self, tohost: int, cycles: int | None = None) -> None:
        """The program reached its end-of-test write. The only clean ending.

        `tohost` is the raw written value. crt0.S encodes it as
        (exit_code << 1) | 1, so 1 means the program passed. Pass the raw value
        through -- the comparator decodes it and reports a failing test
        distinctly from a core mismatch, which matters because they have
        completely different causes.
        """
        self._terminate("tohost", tohost=tohost, cycles=cycles)

    def terminate_timeout(self, cycles: int | None = None) -> None:
        """The cycle limit fired before the program finished. Always a failure."""
        self._terminate("timeout", cycles=cycles)

    def abort(self, detail: str, cycles: int | None = None) -> None:
        """Any other early stop -- a trap loop, an assertion, a simulator error."""
        self._terminate("abort", cycles=cycles, detail=detail.replace(" ", "_"))

    # -- context manager ------------------------------------------------------
    def __enter__(self) -> "RetireLogger":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        # An un-terminated log is the one thing that must never reach disk. If
        # the test raised, or simply fell out of its loop without declaring an
        # ending, record that rather than leaving the log ambiguous.
        if not self._terminated:
            if exc_type is not None:
                self.abort(f"exception_{exc_type.__name__}")
            else:
                self.abort("no_termination_declared")
        self._fh.close()
        return False   # never swallow the exception

    def close(self) -> None:
        if not self._terminated:
            self.abort("closed_without_termination")
        self._fh.close()
