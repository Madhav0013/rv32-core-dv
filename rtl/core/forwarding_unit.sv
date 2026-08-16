`include "rv32_pkg.sv"

module forwarding_unit (
    input  logic [4:0] ex_rs1_addr_i,
    input  logic [4:0] ex_rs2_addr_i,

    input  logic [4:0] mem_rd_addr_i,     // instruction currently in MEM
    input  logic       mem_reg_write_i,
    input  logic       mem_valid_i,

    input  logic [4:0] wb_rd_addr_i,      // instruction currently in WB
    input  logic       wb_reg_write_i,
    input  logic       wb_valid_i,

    output fwd_sel_e   fwd_a_o,
    output fwd_sel_e   fwd_b_o
);

  // EX->EX must take priority over MEM->EX. The nearer source is the YOUNGER
  // instruction and therefore holds the value the consumer must observe.
  //
  // Getting this backwards produces a bug that only appears when the same
  // register is written twice within three instructions -- rare in hand-written
  // tests, common under riscv-dv. That is exactly why it is a coverage point.
  function automatic fwd_sel_e select(input logic [4:0] src);
    if (mem_valid_i && mem_reg_write_i && (mem_rd_addr_i != 5'd0)
        && (mem_rd_addr_i == src))       select = FWD_EX_EX;
    else if (wb_valid_i && wb_reg_write_i && (wb_rd_addr_i != 5'd0)
        && (wb_rd_addr_i == src))        select = FWD_MEM_EX;
    else                                 select = FWD_NONE;
  endfunction

  assign fwd_a_o = select(ex_rs1_addr_i);
  assign fwd_b_o = select(ex_rs2_addr_i);

endmodule : forwarding_unit
