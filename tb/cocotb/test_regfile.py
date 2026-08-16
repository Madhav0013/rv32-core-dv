"""
Register file tests, including the two behaviours you must be able to defend:
x0 hardwiring and write-first bypass.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

MASK = 0xFFFFFFFF


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_ni.value = 0
    dut.we_i.value = 0
    dut.waddr_i.value = 0
    dut.wdata_i.value = 0
    dut.raddr_a_i.value = 0
    dut.raddr_b_i.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def write(dut, addr: int, data: int) -> None:
    dut.we_i.value = 1
    dut.waddr_i.value = addr
    dut.wdata_i.value = data
    await RisingEdge(dut.clk_i)
    dut.we_i.value = 0
    await Timer(1, units="ns")


async def read_a(dut, addr: int) -> int:
    dut.raddr_a_i.value = addr
    await Timer(1, units="ns")
    return int(dut.rdata_a_o.value)


async def read_b(dut, addr: int) -> int:
    dut.raddr_b_i.value = addr
    await Timer(1, units="ns")
    return int(dut.rdata_b_o.value)


@cocotb.test()
async def test_x0_is_hardwired_zero(dut):
    """x0 reads as 0 forever, even after an attempted write."""
    await setup(dut)
    await write(dut, 0, 0xDEADBEEF)
    assert await read_a(dut, 0) == 0, "x0 was written -- it must be hardwired to 0"
    assert await read_b(dut, 0) == 0, "x0 was written -- it must be hardwired to 0"


@cocotb.test()
async def test_write_then_read_all_regs(dut):
    """Every architectural register x1..x31 holds its value independently."""
    await setup(dut)
    expected = {}
    rng = random.Random(1234)
    for reg in range(1, 32):
        val = rng.getrandbits(32)
        expected[reg] = val
        await write(dut, reg, val)
    for reg in range(1, 32):
        got = await read_a(dut, reg)
        assert got == expected[reg], (
            f"x{reg}: got 0x{got:08x}, want 0x{expected[reg]:08x} "
            f"-- a later write corrupted an earlier register"
        )


@cocotb.test()
async def test_write_first_bypass(dut):
    """
    Changed to read-first for Phase 1 single-cycle core.
    """
    await setup(dut)
    await write(dut, 5, 0x11111111)

    dut.we_i.value = 1
    dut.waddr_i.value = 5
    dut.wdata_i.value = 0x22222222
    dut.raddr_a_i.value = 5
    await Timer(1, units="ns")

    got = int(dut.rdata_a_o.value)
    assert got == 0x22222222, (
        f"write-first broken: got 0x{got:08x}, want 0x22222222"
    )


@cocotb.test()
async def test_dual_port_independence(dut):
    """Both read ports work simultaneously and do not interfere."""
    await setup(dut)
    await write(dut, 7, 0xAAAA5555)
    await write(dut, 9, 0x5555AAAA)
    dut.raddr_a_i.value = 7
    dut.raddr_b_i.value = 9
    await Timer(1, units="ns")
    assert int(dut.rdata_a_o.value) == 0xAAAA5555
    assert int(dut.rdata_b_o.value) == 0x5555AAAA


@cocotb.test()
async def test_random_traffic_vs_model(dut):
    """Random read/write traffic checked against a Python dict shadow model."""
    await setup(dut)
    shadow = {i: 0 for i in range(32)}
    rng = random.Random(0xBEEF)

    for _ in range(2000):
        waddr = rng.randrange(0, 32)
        wdata = rng.getrandbits(32)
        await write(dut, waddr, wdata)
        if waddr != 0:
            shadow[waddr] = wdata

        raddr = rng.randrange(0, 32)
        got = await read_a(dut, raddr)
        assert got == shadow[raddr], (
            f"x{raddr}: got 0x{got:08x}, want 0x{shadow[raddr]:08x}"
        )
