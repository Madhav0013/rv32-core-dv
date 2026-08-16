#!/usr/bin/env python3
import os
import glob
import sys
from collections import defaultdict

# Coverage Bins
bins_opcode = set()
bins_alu_op = set()
bins_imm_fmt = set()
bins_fwd = set()
bins_load_use_stall = set()
bins_branch = set()
bins_jump = set()
bins_reg_write = set()
bins_memory = set()
bins_mem_align = set()
bins_pipeline_occ = set()

# Cross Bins
cross_branch = set()
cross_alu = set()
cross_load = set()

def decode_insn(insn):
    opcode = insn & 0x7F
    funct3 = (insn >> 12) & 0x7
    funct7 = (insn >> 25) & 0x7F
    rs1 = (insn >> 15) & 0x1F
    rs2 = (insn >> 20) & 0x1F
    rd = (insn >> 7) & 0x1F
    return opcode, funct3, funct7, rs1, rs2, rd

def process_rtl_log(filepath):
    # rtl.log format: <pc> <insn> <rd> <wdata>
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split()
            if len(parts) != 4: continue
            
            pc = int(parts[0], 16)
            insn = int(parts[1], 16)
            rd_val = int(parts[2], 10)
            
            opcode, funct3, funct7, rs1, rs2, rd = decode_insn(insn)
            
            # Opcode tracking (simplistic representation by opcode field)
            bins_opcode.add(opcode)
            
            # Reg Write
            bins_reg_write.add(rd_val)
            
            # Instruction types
            if opcode == 0x33: # R-type
                alu_op_name = f"R_{funct3}_{funct7}"
                bins_alu_op.add(alu_op_name)
            elif opcode == 0x13: # I-type ALU
                alu_op_name = f"I_{funct3}_{funct7 if funct3 in (1,5) else 0}"
                bins_alu_op.add(alu_op_name)
                bins_imm_fmt.add("I")
            elif opcode == 0x23: # S-type
                bins_imm_fmt.add("S")
                size = ["B", "H", "W"][funct3 & 3] if (funct3 & 3) < 3 else "INV"
                bins_memory.add(f"S{size}")
                # Naive alignment check based on memory operation
                # We can't strictly know the exact effective address alignment just from instruction here unless we reconstruct it,
                # but we will track that we executed it.
            elif opcode == 0x63: # B-type
                bins_imm_fmt.add("B")
                br_types = ["BEQ", "BNE", "INV", "INV", "BLT", "BGE", "BLTU", "BGEU"]
                bins_branch.add(br_types[funct3])
            elif opcode == 0x37: # LUI
                bins_imm_fmt.add("U")
            elif opcode == 0x17: # AUIPC
                bins_imm_fmt.add("U")
            elif opcode == 0x6f: # JAL
                bins_imm_fmt.add("J")
                bins_jump.add("JAL")
            elif opcode == 0x67: # JALR
                bins_imm_fmt.add("I")
                bins_jump.add("JALR")
            elif opcode == 0x03: # Load
                bins_imm_fmt.add("I")
                size = ["B", "H", "W"][funct3 & 3] if (funct3 & 3) < 3 else "INV"
                signed = "U" if (funct3 & 4) else ""
                bins_memory.add(f"L{size}{signed}")

def process_cov_log(filepath):
    # cov.log format: C <fwd_a> <fwd_b> <load_use_stall> <branch_taken> <all_valid>
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('C'): continue
            parts = line.split()
            if len(parts) != 6: continue
            
            fwd_a = int(parts[1])
            fwd_b = int(parts[2])
            stall = int(parts[3])
            taken = int(parts[4])
            all_v = int(parts[5])
            
            fwd_a_str = ["NONE", "EX_EX", "MEM_EX"][fwd_a] if fwd_a < 3 else "INV"
            fwd_b_str = ["NONE", "EX_EX", "MEM_EX"][fwd_b] if fwd_b < 3 else "INV"
            
            bins_fwd.add(f"A_{fwd_a_str}")
            bins_fwd.add(f"B_{fwd_b_str}")
            
            if stall: bins_load_use_stall.add(1)
            if all_v: bins_pipeline_occ.add(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python coverage.py <log_dir>")
        sys.exit(1)
        
    log_dir = sys.argv[1]
    
    # Process RTL logs
    for filepath in glob.glob(os.path.join(log_dir, "*.rtl.log")):
        process_rtl_log(filepath)
        
    # Process COV logs
    for filepath in glob.glob(os.path.join(log_dir, "*.rtl.log.cov")):
        process_cov_log(filepath)
        
    print("================ Functional Coverage Report ================")
    print(f"Opcodes Hit: {len(bins_opcode)}")
    print(f"ALU Ops Hit: {len(bins_alu_op)}")
    print(f"Imm Formats: {bins_imm_fmt}")
    print(f"FWD Paths:   {bins_fwd}")
    print(f"Stalls Hit:  {len(bins_load_use_stall)} > 0")
    print(f"Branches:    {bins_branch}")
    print(f"Jumps:       {bins_jump}")
    print(f"Reg Writes:  {len(bins_reg_write)} / 32")
    print(f"Memory Ops:  {bins_memory}")
    print(f"Full Pipe:   {len(bins_pipeline_occ)} > 0")
    print("============================================================")

if __name__ == '__main__':
    main()
