`include "rvfi_macros.vh"
module rvfi_wrapper (
  input         clock,
  input         reset,
  `RVFI_OUTPUTS
);

  logic [31:0] imem_req_addr;
  (* anyseq *) logic [31:0] imem_read_data;
  (* anyseq *) logic        imem_error;

  logic        dmem_req;
  logic        dmem_write;
  logic [1:0]  dmem_size;
  logic        dmem_signed;
  logic [31:0] dmem_addr;
  logic [31:0] dmem_wdata;
  (* anyseq *) logic [31:0] dmem_rdata;
  (* anyseq *) logic        dmem_error;

  // Assuming riscv-formal's RVFI_CONN macros map directly to our rvfi_* ports
  core u_core (
    .clk_i            (clock),
    .rst_ni           (!reset), // riscv-formal is active-high reset
    
    .imem_req_addr_o  (imem_req_addr),
    .imem_read_data_i (imem_read_data),
    .imem_error_i     (imem_error),
    
    .dmem_req_o       (dmem_req),
    .dmem_write_o     (dmem_write),
    .dmem_size_o      (dmem_size),
    .dmem_signed_o    (dmem_signed),
    .dmem_addr_o      (dmem_addr),
    .dmem_wdata_o     (dmem_wdata),
    .dmem_rdata_i     (dmem_rdata),
    .dmem_error_i     (dmem_error),
    
    // RVFI Ports (from core.sv)
    .rvfi_valid       (rvfi_valid),
    .rvfi_order       (rvfi_order),
    .rvfi_insn        (rvfi_insn),
    .rvfi_trap        (rvfi_trap),
    .rvfi_halt        (rvfi_halt),
    .rvfi_intr        (rvfi_intr),
    .rvfi_mode        (rvfi_mode),
    .rvfi_ixl         (rvfi_ixl),
    .rvfi_rs1_addr    (rvfi_rs1_addr),
    .rvfi_rs2_addr    (rvfi_rs2_addr),
    .rvfi_rs1_rdata   (rvfi_rs1_rdata),
    .rvfi_rs2_rdata   (rvfi_rs2_rdata),
    .rvfi_rd_addr     (rvfi_rd_addr),
    .rvfi_rd_wdata    (rvfi_rd_wdata),
    .rvfi_pc_rdata    (rvfi_pc_rdata),
    .rvfi_pc_wdata    (rvfi_pc_wdata),
    .rvfi_mem_addr    (rvfi_mem_addr),
    .rvfi_mem_rmask   (rvfi_mem_rmask),
    .rvfi_mem_wmask   (rvfi_mem_wmask),
    .rvfi_mem_rdata   (rvfi_mem_rdata),
    .rvfi_mem_wdata   (rvfi_mem_wdata)
  );

  // Assertions to constrain memory interface behaviour can be added here
  // so that the formal solver understands instruction/data fetch latency.
  
  // Constrain the memory interface to never throw errors, since our core doesn't handle bus faults.
  always @* begin
    assume(!imem_error);
    assume(!dmem_error);
  end

endmodule
