"""
Reference-model test for the ALU.

The pattern demonstrated here is the pattern used for the WHOLE project, just
at a smaller scale: never hand-write expected values, always compute them from
an independent model. Here the model is 15 lines of Python. Later it will be
Spike. The structure of the check is identical either way -- drive the DUT,
compute the golden answer separately, diff, and report enough context to debug.

Run:  make -C tb/cocotb alu
"""

import random

import cocotb
from cocotb.triggers import Timer

MASK = 0xFFFFFFFF

# Must match the alu_op_e encoding in rtl/core/rv32_pkg.sv
ALU_ADD, ALU_SUB, ALU_SLL, ALU_SLT, ALU_SLTU = 0, 1, 2, 3, 4
ALU_XOR, ALU_SRL, ALU_SRA, ALU_OR, ALU_AND = 5, 6, 7, 8, 9
ALU_PASS_B = 10

OPS = [
    ALU_ADD, ALU_SUB, ALU_SLL, ALU_SLT, ALU_SLTU,
    ALU_XOR, ALU_SRL, ALU_SRA, ALU_OR, ALU_AND, ALU_PASS_B,
]

NAMES = {
    ALU_ADD: "ADD", ALU_SUB: "SUB", ALU_SLL: "SLL", ALU_SLT: "SLT",
    ALU_SLTU: "SLTU", ALU_XOR: "XOR", ALU_SRL: "SRL", ALU_SRA: "SRA",
    ALU_OR: "OR", ALU_AND: "AND", ALU_PASS_B: "PASS_B",
}


def to_signed(x: int) -> int:
    """Reinterpret a 32-bit unsigned value as two's-complement signed."""
    return x - (1 << 32) if x & 0x80000000 else x


def model(op: int, a: int, b: int) -> int:
    """Independent golden model. Written from the spec, not from the RTL."""
    shamt = b & 0x1F
    if op == ALU_ADD:
        return (a + b) & MASK
    if op == ALU_SUB:
        return (a - b) & MASK
    if op == ALU_SLL:
        return (a << shamt) & MASK
    if op == ALU_SLT:
        return int(to_signed(a) < to_signed(b))
    if op == ALU_SLTU:
        return int(a < b)
    if op == ALU_XOR:
        return a ^ b
    if op == ALU_SRL:
        return a >> shamt
    if op == ALU_SRA:
        return (to_signed(a) >> shamt) & MASK
    if op == ALU_OR:
        return a | b
    if op == ALU_AND:
        return a & b
    if op == ALU_PASS_B:
        return b
    raise ValueError(f"unmodelled op {op}")


async def check(dut, op: int, a: int, b: int) -> None:
    dut.op_i.value = op
    dut.a_i.value = a
    dut.b_i.value = b
    await Timer(1, units="ns")

    got = int(dut.result_o.value)
    exp = model(op, a, b)
    assert got == exp, (
        f"\n  op   = {NAMES[op]}"
        f"\n  a    = 0x{a:08x} ({to_signed(a)})"
        f"\n  b    = 0x{b:08x} ({to_signed(b)})"
        f"\n  got  = 0x{got:08x}"
        f"\n  want = 0x{exp:08x}"
    )

    assert int(dut.zero_o.value) == int(exp == 0), (
        f"zero_o wrong for {NAMES[op]}: result=0x{exp:08x}"
    )


@cocotb.test()
async def test_directed_corners(dut):
    """Corner values that historically break real ALUs."""
    corners = [
        0x00000000, 0x00000001, 0xFFFFFFFF, 0x7FFFFFFF,
        0x80000000, 0xDEADBEEF, 0x0000001F, 0x00000020,
    ]
    for op in OPS:
        for a in corners:
            for b in corners:
                await check(dut, op, a, b)


@cocotb.test()
async def test_sra_sign_extension(dut):
    """
    Isolated regression for the classic SRA bug.

    A logical shift here silently passes every unsigned test vector and fails
    only on negative operands, so it gets its own named test. When this fails
    the test name alone tells you what broke.
    """
    for shamt in range(32):
        await check(dut, ALU_SRA, 0x80000000, shamt)
        await check(dut, ALU_SRA, 0xFFFFFFFF, shamt)
        await check(dut, ALU_SRA, 0x7FFFFFFF, shamt)


@cocotb.test()
async def test_shift_amount_masking(dut):
    """RV32 uses only b[4:0] as the shift amount. Upper bits must be ignored."""
    for shamt in range(32):
        for high_garbage in (0x0, 0x20, 0xFFFFFFE0):
            b = (high_garbage | shamt) & MASK
            await check(dut, ALU_SLL, 0x12345678, b)
            await check(dut, ALU_SRL, 0x12345678, b)
            await check(dut, ALU_SRA, 0x87654321, b)


@cocotb.test()
async def test_random(dut):
    """Constrained-random sweep. Seeded so failures are reproducible."""
    rng = random.Random(0xC0FFEE)
    for _ in range(4000):
        await check(dut, rng.choice(OPS), rng.getrandbits(32), rng.getrandbits(32))
