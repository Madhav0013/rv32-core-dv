`include "rv32_pkg.sv"

module decoder (
    input  logic [31:0] insn_i,
    
    output logic [4:0]  rs1_addr_o,
    output logic [4:0]  rs2_addr_o,
    output logic [4:0]  rd_addr_o,

    output alu_op_e     alu_op_o,
    output imm_sel_e    imm_sel_o,
    output logic        alu_a_sel_o,
    output logic        alu_b_sel_o,
    
    output logic        reg_write_o,
    
    output logic        mem_read_o,
    output logic        mem_write_o,
    output logic [1:0]  mem_size_o,
    output logic        mem_signed_o,
    
    output br_op_e      br_op_o,
    output logic        is_branch_o,
    output logic        is_jump_o,
    output logic        is_jalr_o,
    
    output logic [1:0]  wb_sel_o,
    output logic        illegal_o
);

  logic [6:0] opcode;
  logic [2:0] funct3;
  logic [6:0] funct7;

  assign opcode = insn_i[6:0];
  assign funct3 = insn_i[14:12];
  assign funct7 = insn_i[31:25];

  assign rs1_addr_o = insn_i[19:15];
  assign rs2_addr_o = insn_i[24:20];
  assign rd_addr_o  = insn_i[11:7];

  always_comb begin
    // Default values
    alu_op_o    = ALU_ADD;
    imm_sel_o   = IMM_NONE;
    alu_a_sel_o = 1'b0; // 0: rs1, 1: pc
    alu_b_sel_o = 1'b0; // 0: rs2, 1: imm
    reg_write_o = 1'b0;
    mem_read_o  = 1'b0;
    mem_write_o = 1'b0;
    mem_size_o  = 2'b00;
    mem_signed_o= 1'b0;
    br_op_o     = BR_EQ;
    is_branch_o = 1'b0;
    is_jump_o   = 1'b0;
    is_jalr_o   = 1'b0;
    wb_sel_o    = 2'b00; // 0: alu, 1: mem, 2: pc_plus_4
    illegal_o   = 1'b0;

    unique case (opcode)
      OP_LUI: begin
        imm_sel_o   = IMM_U;
        alu_b_sel_o = 1'b1;
        alu_op_o    = ALU_PASS_B;
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b00;
      end

      OP_AUIPC: begin
        imm_sel_o   = IMM_U;
        alu_a_sel_o = 1'b1; // pc
        alu_b_sel_o = 1'b1; // imm
        alu_op_o    = ALU_ADD;
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b00;
      end

      OP_JAL: begin
        imm_sel_o   = IMM_J;
        is_jump_o   = 1'b1;
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b10; // pc_plus_4
      end

      OP_JALR: begin
        imm_sel_o   = IMM_I;
        alu_b_sel_o = 1'b1; // imm
        is_jump_o   = 1'b1;
        is_jalr_o   = 1'b1;
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b10; // pc_plus_4
        if (funct3 != 3'b000) illegal_o = 1'b1;
      end

      OP_BRANCH: begin
        imm_sel_o   = IMM_B;
        is_branch_o = 1'b1;
        unique case (funct3)
          3'b000: br_op_o = BR_EQ;
          3'b001: br_op_o = BR_NE;
          3'b100: br_op_o = BR_LT;
          3'b101: br_op_o = BR_GE;
          3'b110: br_op_o = BR_LTU;
          3'b111: br_op_o = BR_GEU;
          default: illegal_o = 1'b1;
        endcase
      end

      OP_LOAD: begin
        imm_sel_o   = IMM_I;
        alu_a_sel_o = 1'b0; // rs1
        alu_b_sel_o = 1'b1; // imm
        alu_op_o    = ALU_ADD;
        mem_read_o  = 1'b1;
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b01; // mem
        unique case (funct3)
          3'b000: begin mem_size_o = 2'b00; mem_signed_o = 1'b1; end // LB
          3'b001: begin mem_size_o = 2'b01; mem_signed_o = 1'b1; end // LH
          3'b010: begin mem_size_o = 2'b10; mem_signed_o = 1'b1; end // LW
          3'b100: begin mem_size_o = 2'b00; mem_signed_o = 1'b0; end // LBU
          3'b101: begin mem_size_o = 2'b01; mem_signed_o = 1'b0; end // LHU
          default: illegal_o = 1'b1;
        endcase
      end

      OP_STORE: begin
        imm_sel_o   = IMM_S;
        alu_a_sel_o = 1'b0; // rs1
        alu_b_sel_o = 1'b1; // imm
        alu_op_o    = ALU_ADD;
        mem_write_o = 1'b1;
        unique case (funct3)
          3'b000: mem_size_o = 2'b00; // SB
          3'b001: mem_size_o = 2'b01; // SH
          3'b010: mem_size_o = 2'b10; // SW
          default: illegal_o = 1'b1;
        endcase
      end

      OP_OPIMM: begin
        imm_sel_o   = IMM_I;
        alu_a_sel_o = 1'b0; // rs1
        alu_b_sel_o = 1'b1; // imm
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b00; // alu
        unique case (funct3)
          3'b000: alu_op_o = ALU_ADD;
          3'b010: alu_op_o = ALU_SLT;
          3'b011: alu_op_o = ALU_SLTU;
          3'b100: alu_op_o = ALU_XOR;
          3'b110: alu_op_o = ALU_OR;
          3'b111: alu_op_o = ALU_AND;
          3'b001: begin
            alu_op_o = ALU_SLL;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b101: begin
            if (funct7 == 7'b0000000) alu_op_o = ALU_SRL;
            else if (funct7 == 7'b0100000) alu_op_o = ALU_SRA;
            else illegal_o = 1'b1;
          end
        endcase
      end

      OP_OP: begin
        imm_sel_o   = IMM_NONE;
        alu_a_sel_o = 1'b0; // rs1
        alu_b_sel_o = 1'b0; // rs2
        reg_write_o = 1'b1;
        wb_sel_o    = 2'b00; // alu
        unique case (funct3)
          3'b000: begin
            if (funct7 == 7'b0000000) alu_op_o = ALU_ADD;
            else if (funct7 == 7'b0100000) alu_op_o = ALU_SUB;
            else illegal_o = 1'b1;
          end
          3'b001: begin
            alu_op_o = ALU_SLL;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b010: begin
            alu_op_o = ALU_SLT;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b011: begin
            alu_op_o = ALU_SLTU;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b100: begin
            alu_op_o = ALU_XOR;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b101: begin
            if (funct7 == 7'b0000000) alu_op_o = ALU_SRL;
            else if (funct7 == 7'b0100000) alu_op_o = ALU_SRA;
            else illegal_o = 1'b1;
          end
          3'b110: begin
            alu_op_o = ALU_OR;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
          3'b111: begin
            alu_op_o = ALU_AND;
            if (funct7 != 7'b0000000) illegal_o = 1'b1;
          end
        endcase
      end

      OP_MISC_MEM: begin
        if (funct3 != 3'b000) illegal_o = 1'b1; // FENCE
      end

      OP_SYSTEM: begin
        if (funct3 == 3'b000 && (insn_i[31:20] == 12'h000 || insn_i[31:20] == 12'h001)) begin
           illegal_o = 1'b0; // ECALL or EBREAK
        end else begin
           illegal_o = 1'b1;
        end
      end

      default: begin
        illegal_o = 1'b1;
      end
    endcase
  end

endmodule : decoder
