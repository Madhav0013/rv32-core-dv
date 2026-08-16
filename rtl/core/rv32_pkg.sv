// -----------------------------------------------------------------------------
// rv32_pkg.sv -- shared types and constants for the RV32I core.
//
// This package is the single source of truth for opcode encodings and internal
// control enums. Every module imports it. If you find yourself writing a magic
// number for an opcode anywhere else in the RTL, it belongs here instead.
// -----------------------------------------------------------------------------
`ifndef RV32_PKG_SV
`define RV32_PKG_SV

  parameter int unsigned XLEN = 32;

  // ---------------------------------------------------------------------------
  // Base opcodes (inst[6:0]). Names follow the RISC-V unprivileged spec.
  // ---------------------------------------------------------------------------
  typedef enum logic [6:0] {
    OP_LOAD   = 7'b0000011,
    OP_MISC_MEM = 7'b0001111,  // FENCE
    OP_OPIMM  = 7'b0010011,
    OP_AUIPC  = 7'b0010111,
    OP_STORE  = 7'b0100011,
    OP_OP     = 7'b0110011,
    OP_LUI    = 7'b0110111,
    OP_BRANCH = 7'b1100011,
    OP_JALR   = 7'b1100111,
    OP_JAL    = 7'b1101111,
    OP_SYSTEM = 7'b1110011
  } opcode_e;

  // ---------------------------------------------------------------------------
  // ALU operations. This is an INTERNAL control encoding, deliberately decoupled
  // from the instruction encoding -- the decoder maps instructions onto these.
  // Keeping them separate is what lets you add the M extension (or a custom
  // instruction later) without touching the ALU's interface.
  // ---------------------------------------------------------------------------
  typedef enum logic [3:0] {
    ALU_ADD  = 4'd0,
    ALU_SUB  = 4'd1,
    ALU_SLL  = 4'd2,
    ALU_SLT  = 4'd3,
    ALU_SLTU = 4'd4,
    ALU_XOR  = 4'd5,
    ALU_SRL  = 4'd6,
    ALU_SRA  = 4'd7,
    ALU_OR   = 4'd8,
    ALU_AND  = 4'd9,
    ALU_PASS_B = 4'd10   // used by LUI: result = operand b
  } alu_op_e;

  // ---------------------------------------------------------------------------
  // Immediate formats. The decoder selects one of these; a single immgen block
  // does the actual sign extension.
  // ---------------------------------------------------------------------------
  typedef enum logic [2:0] {
    IMM_I = 3'd0,
    IMM_S = 3'd1,
    IMM_B = 3'd2,
    IMM_U = 3'd3,
    IMM_J = 3'd4,
    IMM_NONE = 3'd5
  } imm_sel_e;

  // ---------------------------------------------------------------------------
  // Branch comparison kinds (funct3 of the BRANCH opcode, named).
  // ---------------------------------------------------------------------------
  typedef enum logic [2:0] {
    BR_EQ  = 3'b000,
    BR_NE  = 3'b001,
    BR_LT  = 3'b100,
    BR_GE  = 3'b101,
    BR_LTU = 3'b110,
    BR_GEU = 3'b111
  } br_op_e;

  // ---------------------------------------------------------------------------
  // Forwarding Selection
  // ---------------------------------------------------------------------------
  typedef enum logic [1:0] {
    FWD_NONE   = 2'd0,
    FWD_EX_EX  = 2'd1,
    FWD_MEM_EX = 2'd2
  } fwd_sel_e;

  // ---------------------------------------------------------------------------
  // Pipeline Registers
  // ---------------------------------------------------------------------------
  typedef struct packed {
    logic [XLEN-1:0] pc;
    logic [XLEN-1:0] pc_plus_4;
    logic [31:0]     insn;
    logic            valid;
  } if_id_t;

  typedef struct packed {
    logic [XLEN-1:0] pc, pc_plus_4;
    logic [31:0]     insn;          // carried solely for the retire trace
    logic [4:0]      rs1_addr, rs2_addr, rd_addr;
    logic [XLEN-1:0] rs1_data, rs2_data, imm;
    alu_op_e         alu_op;
    logic            alu_a_sel;     // 0 = rs1,  1 = pc
    logic            alu_b_sel;     // 0 = rs2,  1 = imm
    br_op_e          br_op;
    logic            is_branch, is_jump, is_jalr;
    logic            mem_read, mem_write, mem_signed;
    logic [1:0]      mem_size;
    logic            reg_write;
    logic [1:0]      wb_sel;        // 0 = alu, 1 = mem, 2 = pc_plus_4
    logic            valid;
  } id_ex_t;

  typedef struct packed {
    logic [XLEN-1:0] pc;
    logic [XLEN-1:0] alu_result;
    logic [XLEN-1:0] rs2_data;
    logic [4:0]      rd_addr;
    logic            mem_read, mem_write, mem_signed;
    logic [1:0]      mem_size;
    logic            reg_write;
    logic [1:0]      wb_sel;
    logic            valid;
    logic [31:0]     insn;
    // For RVFI
    logic [4:0]      rs1_addr, rs2_addr;
    logic [XLEN-1:0] rs1_data;
    logic [XLEN-1:0] next_pc;
  } ex_mem_t;

  typedef struct packed {
    logic [XLEN-1:0] pc;
    logic [XLEN-1:0] alu_result;
    logic [XLEN-1:0] mem_rdata;
    logic [4:0]      rd_addr;
    logic            reg_write;
    logic [1:0]      wb_sel;
    logic            valid;
    logic [31:0]     insn;
    // For RVFI
    logic [4:0]      rs1_addr, rs2_addr;
    logic [XLEN-1:0] rs1_data, rs2_data;
    logic [XLEN-1:0] next_pc;
    logic            mem_read, mem_write;
  } mem_wb_t;



`endif
