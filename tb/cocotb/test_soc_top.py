import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from elftools.elf.elffile import ELFFile
from retire_log import RetireLogger

BASE_ADDR = 0x80000000

def load_elf(dut, elf_path):
    with open(elf_path, 'rb') as f:
        elf = ELFFile(f)
        
        # Find symbols
        tohost_addr = None
        begin_signature = None
        end_signature = None
        symtab = elf.get_section_by_name('.symtab')
        if symtab:
            for sym in symtab.iter_symbols():
                if sym.name == 'tohost':
                    tohost_addr = sym['st_value']
                elif sym.name in ('begin_signature', 'rvtest_sig_begin'):
                    begin_signature = sym['st_value']
                elif sym.name in ('end_signature', 'rvtest_sig_end'):
                    end_signature = sym['st_value']
                    
        if tohost_addr is None:
            raise ValueError("Could not find 'tohost' symbol in ELF")
            
        # Load segments
        for seg in elf.iter_segments():
            if seg['p_type'] == 'PT_LOAD':
                addr = seg['p_paddr']
                data = seg.data()
                offset = addr - BASE_ADDR
                
                # Write to both imem and dmem
                # imem is 32-bit words, dmem is 8-bit bytes
                for i in range(len(data)):
                    dut.u_dmem.mem[offset + i].value = data[i]
                    
                # Write to imem (words)
                # Padding to multiple of 4
                padded_data = bytearray(data)
                while len(padded_data) % 4 != 0:
                    padded_data.append(0)
                    
                word_offset = offset // 4
                for i in range(0, len(padded_data), 4):
                    word = int.from_bytes(padded_data[i:i+4], byteorder='little')
                    dut.u_imem.mem[word_offset + i//4].value = word
                    
    return tohost_addr, begin_signature, end_signature

def dump_signature(dut, begin_sig, end_sig, sig_file):
    # Dmem is byte addressed. We need 32-bit words, formatted as hex, one per line.
    if begin_sig is None or end_sig is None:
        return
        
    start_offset = begin_sig - BASE_ADDR
    end_offset = end_sig - BASE_ADDR
    
    with open(sig_file, 'w') as f:
        for offset in range(start_offset, end_offset, 4):
            # Read 4 bytes, little endian
            b0 = dut.u_dmem.mem[offset].value.integer
            b1 = dut.u_dmem.mem[offset+1].value.integer
            b2 = dut.u_dmem.mem[offset+2].value.integer
            b3 = dut.u_dmem.mem[offset+3].value.integer
            
            word = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
            f.write(f"{word:08x}\n")

@cocotb.test()
async def test_soc(dut):
    elf_path = os.environ.get("TESTCASE_ELF")
    if not elf_path:
        raise ValueError("TESTCASE_ELF environment variable not set")
        
    tohost_addr, begin_sig, end_sig = load_elf(dut, elf_path)
    
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    
    max_cycles = 2_000_000
    cycles = 0
    
    rtl_log_path = cocotb.plusargs.get("rtl_log", "retire.log")
    
    with RetireLogger(rtl_log_path) as trace:
        # We must monitor if there's a write to tohost_addr
        while cycles < max_cycles:
            await RisingEdge(dut.clk_i)
            cycles += 1
            
            # One line per RETIRED instruction. Gate on retirement, never on fetch
            # or decode -- flushed instructions must not appear.
            if dut.u_core.rvfi_valid.value == 1:
                trace.log(
                    pc=int(dut.u_core.rvfi_pc_rdata.value),
                    insn=int(dut.u_core.rvfi_insn.value),
                    rd=int(dut.u_core.rvfi_rd_addr.value),
                    rd_value=int(dut.u_core.rvfi_rd_wdata.value),
                )
            
            if dut.dmem_req.value == 1 and dut.dmem_write.value == 1:
                addr = int(dut.dmem_addr.value)
                if addr == tohost_addr:
                    val = int(dut.dmem_wdata.value)
                    trace.terminate_tohost(val, cycles=cycles)
                    
                    if val == 1:
                        dut._log.info("Test Passed (tohost == 1)")
                        await RisingEdge(dut.clk_i)
                        await RisingEdge(dut.clk_i)
                        
                        sig_file = os.environ.get("SIGNATURE_FILE")
                        if sig_file:
                            dump_signature(dut, begin_sig, end_sig, sig_file)
                            
                        return
                    elif val > 1:
                        fail_code = val >> 1
                        raise cocotb.result.TestFailure(f"Test Failed with code {fail_code} (tohost == {val})")
            
        trace.terminate_timeout(cycles=cycles)
        raise cocotb.result.TestFailure("Timeout waiting for tohost write")
