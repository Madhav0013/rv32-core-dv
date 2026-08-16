import cocotb
from cocotb.triggers import Timer

BASE_ADDR = 0x80000000
MEM_SIZE = 256 * 1024

@cocotb.test()
async def test_imem_bounds_and_alignment(dut):
    dut.req_addr_i.value = BASE_ADDR
    await Timer(1, "ns")
    assert dut.error_o.value == 0

    dut.req_addr_i.value = BASE_ADDR - 4
    await Timer(1, "ns")
    assert dut.error_o.value == 1

    dut.req_addr_i.value = BASE_ADDR + MEM_SIZE
    await Timer(1, "ns")
    assert dut.error_o.value == 1

    dut.req_addr_i.value = BASE_ADDR + 1
    await Timer(1, "ns")
    assert dut.error_o.value == 1

    dut.req_addr_i.value = BASE_ADDR + 2
    await Timer(1, "ns")
    assert dut.error_o.value == 1
