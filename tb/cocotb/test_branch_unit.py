import random
import cocotb
from cocotb.triggers import Timer

BR_EQ  = 0
BR_NE  = 1
BR_LT  = 4
BR_GE  = 5
BR_LTU = 6
BR_GEU = 7

def to_signed(x: int) -> int:
    return x - (1 << 32) if x & 0x80000000 else x

def model(op: int, a: int, b: int) -> int:
    if op == BR_EQ:
        return int(a == b)
    elif op == BR_NE:
        return int(a != b)
    elif op == BR_LT:
        return int(to_signed(a) < to_signed(b))
    elif op == BR_GE:
        return int(to_signed(a) >= to_signed(b))
    elif op == BR_LTU:
        return int(a < b)
    elif op == BR_GEU:
        return int(a >= b)
    return 0

async def check(dut, op: int, a: int, b: int) -> None:
    dut.br_op_i.value = op
    dut.a_i.value = a
    dut.b_i.value = b
    await Timer(1, units="ns")
    
    got = int(dut.taken_o.value)
    exp = model(op, a, b)
    assert got == exp, f"op={op}, a=0x{a:08x}, b=0x{b:08x}, got={got}, want={exp}"

@cocotb.test()
async def test_branch_unit(dut):
    corners = [
        0x00000000, 0x00000001, 0xFFFFFFFF, 0x7FFFFFFF,
        0x80000000, 0xDEADBEEF
    ]
    ops = [BR_EQ, BR_NE, BR_LT, BR_GE, BR_LTU, BR_GEU]
    
    for op in ops:
        for a in corners:
            for b in corners:
                await check(dut, op, a, b)
                
    rng = random.Random(0x1337)
    for _ in range(5000):
        await check(dut, rng.choice(ops), rng.getrandbits(32), rng.getrandbits(32))
