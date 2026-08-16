import random

import cocotb
from cocotb.triggers import Timer

MASK = 0xFFFFFFFF

IMM_I = 0
IMM_S = 1
IMM_B = 2
IMM_U = 3
IMM_J = 4
IMM_NONE = 5

def sign_extend(val, bits):
    sign_bit = 1 << (bits - 1)
    return (val & (sign_bit - 1)) - (val & sign_bit)

def model(insn: int, sel: int) -> int:
    if sel == IMM_I:
        imm = (insn >> 20) & 0xFFF
        return sign_extend(imm, 12) & MASK
    elif sel == IMM_S:
        imm11_5 = (insn >> 25) & 0x7F
        imm4_0 = (insn >> 7) & 0x1F
        imm = (imm11_5 << 5) | imm4_0
        return sign_extend(imm, 12) & MASK
    elif sel == IMM_B:
        imm12 = (insn >> 31) & 0x1
        imm11 = (insn >> 7) & 0x1
        imm10_5 = (insn >> 25) & 0x3F
        imm4_1 = (insn >> 8) & 0xF
        imm = (imm12 << 12) | (imm11 << 11) | (imm10_5 << 5) | (imm4_1 << 1)
        return sign_extend(imm, 13) & MASK
    elif sel == IMM_U:
        imm = insn & 0xFFFFF000
        return imm & MASK
    elif sel == IMM_J:
        imm20 = (insn >> 31) & 0x1
        imm19_12 = (insn >> 12) & 0xFF
        imm11 = (insn >> 20) & 0x1
        imm10_1 = (insn >> 21) & 0x3FF
        imm = (imm20 << 20) | (imm19_12 << 12) | (imm11 << 11) | (imm10_1 << 1)
        return sign_extend(imm, 21) & MASK
    else:
        return 0

async def check(dut, insn: int, sel: int) -> None:
    dut.insn_i.value = insn
    dut.sel_i.value = sel
    await Timer(1, units="ns")
    got = int(dut.imm_o.value)
    exp = model(insn, sel)
    assert got == exp, (
        f"\n  sel  = {sel}"
        f"\n  insn = 0x{insn:08x}"
        f"\n  got  = 0x{got:08x}"
        f"\n  want = 0x{exp:08x}"
    )

@cocotb.test()
async def test_random(dut):
    """Constrained-random sweep. Seeded so failures are reproducible."""
    rng = random.Random(0xDEADBEEF)
    sels = [IMM_I, IMM_S, IMM_B, IMM_U, IMM_J, IMM_NONE]
    for _ in range(10000):
        await check(dut, rng.getrandbits(32), rng.choice(sels))
