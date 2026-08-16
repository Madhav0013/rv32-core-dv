`include "rv32_pkg.sv"
module core (
    input  logic        clk_i,
    input  logic        rst_ni,

    // Instruction memory interface
    output logic [31:0] imem_req_addr_o,
    input  logic [31:0] imem_read_data_i,
    input  logic        imem_error_i,

    // Data memory interface
    output logic        dmem_req_o,
    output logic        dmem_write_o,
    output logic [1:0]  dmem_size_o,
    output logic        dmem_signed_o,
    output logic [31:0] dmem_addr_o,
    output logic [31:0] dmem_wdata_o,
    input  logic [31:0] dmem_rdata_i,
    input  logic        dmem_error_i

`ifdef RISCV_FORMAL
    // -------------------------------------------------------------------------
    // RVFI Interface (RISC-V Formal Interface)
    // -------------------------------------------------------------------------
    ,
    output logic        rvfi_valid,
    output logic [63:0] rvfi_order,
    output logic [31:0] rvfi_insn,
    output logic        rvfi_trap,
    output logic        rvfi_halt,
    output logic        rvfi_intr,
    output logic [1:0]  rvfi_mode,
    output logic [1:0]  rvfi_ixl,
    output logic [4:0]  rvfi_rs1_addr,
    output logic [4:0]  rvfi_rs2_addr,
    output logic [31:0] rvfi_rs1_rdata,
    output logic [31:0] rvfi_rs2_rdata,
    output logic [4:0]  rvfi_rd_addr,
    output logic [31:0] rvfi_rd_wdata,
    output logic [31:0] rvfi_pc_rdata,
    output logic [31:0] rvfi_pc_wdata,
    output logic [31:0] rvfi_mem_addr,
    output logic [3:0]  rvfi_mem_rmask,
    output logic [3:0]  rvfi_mem_wmask,
    output logic [31:0] rvfi_mem_rdata,
    output logic [31:0] rvfi_mem_wdata
`endif
);

  // ---------------------------------------------------------------------------
  // Pipeline Registers
  // ---------------------------------------------------------------------------
  /* verilator lint_off UNUSEDSIGNAL */
  if_id_t  if_id_q,  if_id_d;
  id_ex_t  id_ex_q,  id_ex_d;
  ex_mem_t ex_mem_q, ex_mem_d;
  mem_wb_t mem_wb_q, mem_wb_d;
  /* verilator lint_on UNUSEDSIGNAL */

  // ---------------------------------------------------------------------------
  // Hazard & Forwarding Units
  // ---------------------------------------------------------------------------
  logic pc_stall, if_id_hold, if_id_flush, id_ex_bubble, id_ex_flush;
  fwd_sel_e fwd_a, fwd_b;

  // ---------------------------------------------------------------------------
  // IF Stage
  // ---------------------------------------------------------------------------
  logic [31:0] pc_q, pc_d;
  logic [31:0] if_pc_plus_4;
  logic [31:0] ex_target_pc;
  logic        ex_take_branch;

  assign if_pc_plus_4 = pc_q + 4;
  assign imem_req_addr_o = pc_q;

  always_comb begin
    if (ex_take_branch) begin
      pc_d = ex_target_pc;
    end else if (pc_stall) begin
      pc_d = pc_q;
    end else begin
      pc_d = if_pc_plus_4;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      pc_q <= 32'h8000_0000;
    end else begin
      pc_q <= pc_d;
    end
  end

  always_comb begin
    if_id_d.pc = pc_q;
    if_id_d.pc_plus_4 = if_pc_plus_4;
    if_id_d.insn = imem_read_data_i;
    // We only consider instruction valid if there wasn't an imem error
    if_id_d.valid = !imem_error_i;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      if_id_q <= '0;
    end else if (if_id_flush) begin
      if_id_q.valid <= 1'b0;
    end else if (!if_id_hold) begin
      if_id_q <= if_id_d;
    end
  end

  // ---------------------------------------------------------------------------
  // ID Stage
  // ---------------------------------------------------------------------------
  logic [4:0] id_rs1_addr, id_rs2_addr, id_rd_addr;
  alu_op_e    id_alu_op;
  imm_sel_e   id_imm_sel;
  logic       id_alu_a_sel, id_alu_b_sel;
  logic       id_reg_write;
  logic       id_mem_read, id_mem_write, id_mem_signed;
  logic [1:0] id_mem_size;
  br_op_e     id_br_op;
  logic       id_is_branch, id_is_jump, id_is_jalr;
  logic [1:0] id_wb_sel;
  logic       id_illegal;
  logic [31:0] id_imm;
  logic [31:0] id_rs1_data, id_rs2_data;
  logic [31:0] wb_data; // from WB stage

  decoder u_decoder (
      .insn_i       (if_id_q.insn),
      .rs1_addr_o   (id_rs1_addr),
      .rs2_addr_o   (id_rs2_addr),
      .rd_addr_o    (id_rd_addr),
      .alu_op_o     (id_alu_op),
      .imm_sel_o    (id_imm_sel),
      .alu_a_sel_o  (id_alu_a_sel),
      .alu_b_sel_o  (id_alu_b_sel),
      .reg_write_o  (id_reg_write),
      .mem_read_o   (id_mem_read),
      .mem_write_o  (id_mem_write),
      .mem_size_o   (id_mem_size),
      .mem_signed_o (id_mem_signed),
      .br_op_o      (id_br_op),
      .is_branch_o  (id_is_branch),
      .is_jump_o    (id_is_jump),
      .is_jalr_o    (id_is_jalr),
      .wb_sel_o     (id_wb_sel),
      .illegal_o    (id_illegal)
  );

  immgen u_immgen (
      .insn_i (if_id_q.insn),
      .sel_i  (id_imm_sel),
      .imm_o  (id_imm)
  );

  regfile u_regfile (
      .clk_i      (clk_i),
      .rst_ni     (rst_ni),
      .raddr_a_i  (id_rs1_addr),
      .rdata_a_o  (id_rs1_data),
      .raddr_b_i  (id_rs2_addr),
      .rdata_b_o  (id_rs2_data),
      .we_i       (mem_wb_q.reg_write && mem_wb_q.valid),
      .waddr_i    (mem_wb_q.rd_addr),
      .wdata_i    (wb_data)
  );

  always_comb begin
    id_ex_d.pc         = if_id_q.pc;
    id_ex_d.pc_plus_4  = if_id_q.pc_plus_4;
    id_ex_d.insn       = if_id_q.insn;
    id_ex_d.rs1_addr   = id_rs1_addr;
    id_ex_d.rs2_addr   = id_rs2_addr;
    id_ex_d.rd_addr    = id_rd_addr;
    id_ex_d.rs1_data   = id_rs1_data;
    id_ex_d.rs2_data   = id_rs2_data;
    id_ex_d.imm        = id_imm;
    id_ex_d.alu_op     = id_alu_op;
    id_ex_d.alu_a_sel  = id_alu_a_sel;
    id_ex_d.alu_b_sel  = id_alu_b_sel;
    id_ex_d.br_op      = id_br_op;
    id_ex_d.is_branch  = id_is_branch;
    id_ex_d.is_jump    = id_is_jump;
    id_ex_d.is_jalr    = id_is_jalr;
    id_ex_d.mem_read   = id_mem_read;
    id_ex_d.mem_write  = id_mem_write;
    id_ex_d.mem_signed = id_mem_signed;
    id_ex_d.mem_size   = id_mem_size;
    id_ex_d.reg_write  = id_reg_write;
    id_ex_d.wb_sel     = id_wb_sel;
    
    // Valid only if IF/ID is valid, no exceptions here except illegal (we halt on illegal but don't care now)
    id_ex_d.valid      = if_id_q.valid && !id_illegal;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      id_ex_q <= '0;
    end else if (id_ex_flush || id_ex_bubble) begin
      id_ex_q.valid <= 1'b0;
    end else begin
      id_ex_q <= id_ex_d;
    end
  end

  hazard_unit u_hazard_unit (
      .id_ex_valid_i    (id_ex_q.valid),
      .id_ex_mem_read_i (id_ex_q.mem_read),
      .id_ex_rd_addr_i  (id_ex_q.rd_addr),
      .id_rs1_addr_i    (id_rs1_addr),
      .id_rs2_addr_i    (id_rs2_addr),
      .branch_taken_i   (ex_take_branch),
      .pc_stall_o       (pc_stall),
      .if_id_hold_o     (if_id_hold),
      .if_id_flush_o    (if_id_flush),
      .id_ex_bubble_o   (id_ex_bubble),
      .id_ex_flush_o    (id_ex_flush)
  );

  // ---------------------------------------------------------------------------
  // EX Stage
  // ---------------------------------------------------------------------------
  logic [31:0] ex_fwd_a, ex_fwd_b;
  logic [31:0] ex_alu_a, ex_alu_b, ex_alu_result;
  /* verilator lint_off UNUSEDSIGNAL */
  logic        ex_alu_zero;
  /* verilator lint_on UNUSEDSIGNAL */
  logic        ex_branch_taken;

  // Forwarding Muxes
  always_comb begin
    case (fwd_a)
      FWD_EX_EX:  ex_fwd_a = ex_mem_q.alu_result;
      FWD_MEM_EX: ex_fwd_a = wb_data; // From mem_wb_q logic
      default:    ex_fwd_a = id_ex_q.rs1_data;
    endcase

    case (fwd_b)
      FWD_EX_EX:  ex_fwd_b = ex_mem_q.alu_result;
      FWD_MEM_EX: ex_fwd_b = wb_data;
      default:    ex_fwd_b = id_ex_q.rs2_data;
    endcase
  end

  // ALU Inputs
  assign ex_alu_a = id_ex_q.alu_a_sel ? id_ex_q.pc : ex_fwd_a;
  assign ex_alu_b = id_ex_q.alu_b_sel ? id_ex_q.imm : ex_fwd_b;

  alu u_alu (
      .op_i     (id_ex_q.alu_op),
      .a_i      (ex_alu_a),
      .b_i      (ex_alu_b),
      .result_o (ex_alu_result),
      .zero_o   (ex_alu_zero)
  );

  branch_unit u_branch_unit (
      .a_i      (ex_fwd_a),
      .b_i      (ex_fwd_b),
      .br_op_i  (id_ex_q.br_op),
      .taken_o  (ex_branch_taken)
  );

  assign ex_take_branch = id_ex_q.valid && ((id_ex_q.is_branch && ex_branch_taken) || id_ex_q.is_jump);

  always_comb begin
    if (id_ex_q.is_jalr) begin 
      ex_target_pc = ex_alu_result & ~32'h1;
    end else begin
      ex_target_pc = id_ex_q.pc + id_ex_q.imm;
    end
  end

  always_comb begin
    ex_mem_d.pc         = id_ex_q.pc;
    // For JAL/JALR, we need to save pc+4 to rd, which we can pass through alu_result or compute in WB. 
    // We compute it in WB using mem_wb_q.pc + 4. So alu_result is not needed for pc+4.
    ex_mem_d.alu_result = ex_alu_result;
    ex_mem_d.rs2_data   = ex_fwd_b;
    ex_mem_d.rd_addr    = id_ex_q.rd_addr;
    ex_mem_d.mem_read   = id_ex_q.mem_read;
    ex_mem_d.mem_write  = id_ex_q.mem_write;
    ex_mem_d.mem_signed = id_ex_q.mem_signed;
    ex_mem_d.mem_size   = id_ex_q.mem_size;
    ex_mem_d.reg_write  = id_ex_q.reg_write;
    ex_mem_d.wb_sel     = id_ex_q.wb_sel;
    ex_mem_d.insn       = id_ex_q.insn;
    ex_mem_d.valid      = id_ex_q.valid;
    // For RVFI
    ex_mem_d.rs1_addr   = id_ex_q.rs1_addr;
    ex_mem_d.rs2_addr   = id_ex_q.rs2_addr;
    ex_mem_d.rs1_data   = ex_fwd_a;
    ex_mem_d.next_pc    = ex_take_branch ? ex_target_pc : id_ex_q.pc_plus_4;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      ex_mem_q <= '0;
    end else begin
      ex_mem_q <= ex_mem_d;
    end
  end

  forwarding_unit u_forwarding_unit (
      .ex_rs1_addr_i   (id_ex_q.rs1_addr),
      .ex_rs2_addr_i   (id_ex_q.rs2_addr),
      .mem_rd_addr_i   (ex_mem_q.rd_addr),
      .mem_reg_write_i (ex_mem_q.reg_write),
      .mem_valid_i     (ex_mem_q.valid),
      .wb_rd_addr_i    (mem_wb_q.rd_addr),
      .wb_reg_write_i  (mem_wb_q.reg_write),
      .wb_valid_i      (mem_wb_q.valid),
      .fwd_a_o         (fwd_a),
      .fwd_b_o         (fwd_b)
  );

  // ---------------------------------------------------------------------------
  // MEM Stage
  // ---------------------------------------------------------------------------
  assign dmem_req_o    = (ex_mem_q.mem_read || ex_mem_q.mem_write) && ex_mem_q.valid;
  assign dmem_write_o  = ex_mem_q.mem_write;
  assign dmem_size_o   = ex_mem_q.mem_size;
  assign dmem_signed_o = ex_mem_q.mem_signed;
  assign dmem_addr_o   = ex_mem_q.alu_result;
  assign dmem_wdata_o  = ex_mem_q.rs2_data;
  
  always_comb begin
    mem_wb_d.pc         = ex_mem_q.pc;
    mem_wb_d.alu_result = ex_mem_q.alu_result;
    mem_wb_d.mem_rdata  = 32'h0; // Not used, data read directly from dmem_rdata_i in WB stage
    mem_wb_d.rd_addr    = ex_mem_q.rd_addr;
    mem_wb_d.reg_write  = ex_mem_q.reg_write;
    mem_wb_d.wb_sel     = ex_mem_q.wb_sel;
    mem_wb_d.insn       = ex_mem_q.insn;
    
    // Invalidate if memory error occurs
    mem_wb_d.valid      = ex_mem_q.valid && !dmem_error_i;
    
    // For RVFI
    mem_wb_d.rs1_addr   = ex_mem_q.rs1_addr;
    mem_wb_d.rs2_addr   = ex_mem_q.rs2_addr;
    mem_wb_d.rs1_data   = ex_mem_q.rs1_data;
    mem_wb_d.rs2_data   = ex_mem_q.rs2_data;
    mem_wb_d.next_pc    = ex_mem_q.next_pc;
    mem_wb_d.mem_read   = ex_mem_q.mem_read;
    mem_wb_d.mem_write  = ex_mem_q.mem_write;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      mem_wb_q <= '0;
    end else begin
      mem_wb_q <= mem_wb_d;
    end
  end

  // ---------------------------------------------------------------------------
  // WB Stage
  // ---------------------------------------------------------------------------
  always_comb begin
    case (mem_wb_q.wb_sel)
      2'b00: wb_data = mem_wb_q.alu_result;
      2'b01: wb_data = dmem_rdata_i;
      2'b10: wb_data = mem_wb_q.pc + 4;
      default: wb_data = '0;
    endcase
  end

  // ---------------------------------------------------------------------------
  // Retire Trace
  // ---------------------------------------------------------------------------
`ifndef SYNTHESIS
  int f;
  int f_cov;
  string log_name;
  string cov_log_name;
  initial begin
    if ($value$plusargs("rtl_log=%s", log_name)) begin
      f = $fopen(log_name, "w");
      cov_log_name = {log_name, ".cov"};
      f_cov = $fopen(cov_log_name, "w");
    end else begin
      f = $fopen("rtl.log", "w");
      f_cov = $fopen("coverage.log", "w");
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_ni && mem_wb_q.valid) begin
      if (f != 0) begin
        if (|mem_wb_q.rd_addr && mem_wb_q.reg_write) begin
          $fdisplay(f, "%08x %08x %0d %08x", mem_wb_q.pc, mem_wb_q.insn, mem_wb_q.rd_addr, wb_data);
        end else begin
          $fdisplay(f, "%08x %08x 0 00000000", mem_wb_q.pc, mem_wb_q.insn);
        end
      end
    end
    
    // Coverage trace: emitted every cycle after reset
    if (rst_ni) begin
      if (f_cov != 0) begin
        // Format: C <cycle_num/ignored> <fwd_a> <fwd_b> <load_use_stall> <branch_taken> <all_valid>
        $fdisplay(f_cov, "C %0d %0d %0d %0d %0d", 
                  fwd_a, 
                  fwd_b, 
                  pc_stall, 
                  ex_take_branch,
                  (if_id_q.valid & id_ex_q.valid & ex_mem_q.valid & mem_wb_q.valid)
        );
      end
    end
  end

`endif

`ifdef RISCV_FORMAL
  // ---------------------------------------------------------------------------
  // RVFI Output Assignments
  // ---------------------------------------------------------------------------
  logic [63:0] rvfi_order_q;
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      rvfi_order_q <= '0;
    end else if (mem_wb_q.valid) begin
      rvfi_order_q <= rvfi_order_q + 1;
    end
  end

  assign rvfi_valid     = mem_wb_q.valid;
  assign rvfi_order     = rvfi_order_q;
  assign rvfi_insn      = mem_wb_q.insn;
  assign rvfi_trap      = 1'b0; // Traps not implemented
  assign rvfi_halt      = 1'b0; // Halt not implemented
  assign rvfi_intr      = 1'b0; // Interrupts not implemented
  assign rvfi_mode      = 2'b11; // Machine mode
  assign rvfi_ixl       = 2'b01; // XLEN=32
  
  assign rvfi_rs1_addr  = mem_wb_q.rs1_addr;
  assign rvfi_rs2_addr  = mem_wb_q.rs2_addr;
  assign rvfi_rs1_rdata = (mem_wb_q.rs1_addr == 5'd0) ? 32'd0 : mem_wb_q.rs1_data;
  assign rvfi_rs2_rdata = (mem_wb_q.rs2_addr == 5'd0) ? 32'd0 : mem_wb_q.rs2_data;
  
  assign rvfi_rd_addr   = mem_wb_q.reg_write ? mem_wb_q.rd_addr : 5'd0;
  assign rvfi_rd_wdata  = (rvfi_rd_addr == 5'd0) ? 32'd0 : wb_data;
  
  assign rvfi_pc_rdata  = mem_wb_q.pc;
  
  assign rvfi_pc_wdata  = mem_wb_q.next_pc;

  // Memory interface (stubbed to 0 if not mem_read/mem_write)
  assign rvfi_mem_addr  = mem_wb_q.alu_result; // The address used in MEM stage
  assign rvfi_mem_rmask = mem_wb_q.mem_read ? 4'b1111 : 4'b0000; // Simplified
  assign rvfi_mem_wmask = mem_wb_q.mem_write ? 4'b1111 : 4'b0000;
  assign rvfi_mem_rdata = mem_wb_q.mem_rdata;
  assign rvfi_mem_wdata = mem_wb_q.rs2_data; // Original write data

`endif

endmodule : core
