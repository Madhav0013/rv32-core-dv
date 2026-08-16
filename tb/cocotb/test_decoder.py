import random
import cocotb
from cocotb.triggers import Timer

OP_LOAD   = 0b0000011
OP_MISC_MEM = 0b0001111
OP_OPIMM  = 0b0010011
OP_AUIPC  = 0b0010111
OP_STORE  = 0b0100011
OP_OP     = 0b0110011
OP_LUI    = 0b0110111
OP_BRANCH = 0b1100011
OP_JALR   = 0b1100111
OP_JAL    = 0b1101111
OP_SYSTEM = 0b1110011

def is_legal(insn):
    opcode = insn & 0x7F
    funct3 = (insn >> 12) & 0x7
    funct7 = (insn >> 25) & 0x7F
    imm12  = (insn >> 20) & 0xFFF
    
    if opcode == OP_LUI or opcode == OP_AUIPC or opcode == OP_JAL:
        return True
    elif opcode == OP_JALR:
        return funct3 == 0
    elif opcode == OP_BRANCH:
        return funct3 != 2 and funct3 != 3
    elif opcode == OP_LOAD:
        return funct3 in (0, 1, 2, 4, 5)
    elif opcode == OP_STORE:
        return funct3 in (0, 1, 2)
    elif opcode == OP_OPIMM:
        if funct3 in (0, 2, 3, 4, 6, 7):
            return True
        elif funct3 == 1:
            return funct7 == 0
        elif funct3 == 5:
            return funct7 == 0 or funct7 == 0x20
        return False
    elif opcode == OP_OP:
        if funct3 in (0, 5):
            return funct7 == 0 or funct7 == 0x20
        elif funct3 in (1, 2, 3, 4, 6, 7):
            return funct7 == 0
        return False
    elif opcode == OP_MISC_MEM:
        return funct3 == 0
    elif opcode == OP_SYSTEM:
        return funct3 == 0 and (imm12 == 0 or imm12 == 1)
    else:
        return False

async def check(dut, insn: int) -> None:
    dut.insn_i.value = insn
    await Timer(1, units="ns")
    
    exp_illegal = not is_legal(insn)
    got_illegal = bool(dut.illegal_o.value)
    
    assert got_illegal == exp_illegal, (
        f"insn=0x{insn:08x}: got illegal={got_illegal}, want {exp_illegal}"
    )

@cocotb.test()
async def test_decoder_illegal(dut):
    """Constrained-random test for instruction decoder legality."""
    rng = random.Random(0xCAFE)
    
    # 1. Test completely random instructions
    for _ in range(50000):
        await check(dut, rng.getrandbits(32))
        
    # 2. Test valid base opcodes but with random funct3/funct7
    opcodes = [OP_LOAD, OP_MISC_MEM, OP_OPIMM, OP_AUIPC, OP_STORE, OP_OP, OP_LUI, OP_BRANCH, OP_JALR, OP_JAL, OP_SYSTEM]
    for _ in range(50000):
        opcode = rng.choice(opcodes)
        insn = rng.getrandbits(32) & ~0x7F | opcode
        await check(dut, insn)
