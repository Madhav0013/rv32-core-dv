import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

BASE_ADDR = 0x80000000

@cocotb.test()
async def test_dmem_rw(dut):
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    dut.req_i.value = 0
    dut.write_i.value = 0
    await RisingEdge(dut.clk_i)
    
    # Write Word
    dut.req_i.value = 1
    dut.write_i.value = 1
    dut.size_i.value = 2 # word
    dut.signed_i.value = 0
    dut.addr_i.value = BASE_ADDR
    dut.wdata_i.value = 0xDEADBEEF
    await RisingEdge(dut.clk_i)
    
    # Read Word (Synchronous now)
    dut.req_i.value = 1
    dut.write_i.value = 0
    dut.size_i.value = 2
    dut.addr_i.value = BASE_ADDR
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    
    assert dut.error_o.value == 0
    assert dut.rdata_o.value == 0xDEADBEEF

@cocotb.test()
async def test_dmem_subword(dut):
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    dut.req_i.value = 0
    dut.write_i.value = 0
    await RisingEdge(dut.clk_i)
    
    # Write Word
    dut.req_i.value = 1
    dut.write_i.value = 1
    dut.size_i.value = 2 # word
    dut.signed_i.value = 0
    dut.addr_i.value = BASE_ADDR + 4
    dut.wdata_i.value = 0x87654321
    await RisingEdge(dut.clk_i)
    
    # Read LB (sign extended)
    dut.req_i.value = 1
    dut.write_i.value = 0
    dut.size_i.value = 0 # byte
    dut.signed_i.value = 1 # signed
    dut.addr_i.value = BASE_ADDR + 4 + 3 # top byte is 0x87
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    
    assert dut.error_o.value == 0
    assert dut.rdata_o.value == 0xFFFFFF87
    
    # Read LBU (zero extended)
    dut.req_i.value = 1
    dut.write_i.value = 0
    dut.size_i.value = 0 # byte
    dut.signed_i.value = 0 # unsigned
    dut.addr_i.value = BASE_ADDR + 4 + 3 # top byte is 0x87
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    
    assert dut.error_o.value == 0
    assert dut.rdata_o.value == 0x00000087
