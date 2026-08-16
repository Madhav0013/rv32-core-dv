// -----------------------------------------------------------------------------
// regfile.sv -- 32x32 register file, 2 read ports, 1 write port.
//
// TWO THINGS HERE WILL BE ASKED ABOUT IN AN INTERVIEW. Know both cold:
//
//   1. x0 is hardwired to zero. Writes to it are silently dropped, reads always
//      return 0. This is architectural, not an optimisation.
//
//   2. WRITE-FIRST (internal forwarding). When a read address matches the write
//      address in the same cycle, we return the NEW value, not the old one.
//      In a 5-stage pipeline this removes the WB->ID hazard so your forwarding
//      logic only has to handle EX->EX and MEM->EX. If you instead choose
//      read-first, you MUST add a third forwarding path. Either is defensible;
//      what is not defensible is not knowing which one you built.
//
// This file documents choice (2) as WRITE-FIRST. If you change it, change
// docs/microarchitecture.md in the same commit.
// -----------------------------------------------------------------------------
`include "rv32_pkg.sv"

module regfile (
    input  logic             clk_i,
    input  logic             rst_ni,      // active-low synchronous reset

    input  logic [4:0]       raddr_a_i,
    output logic [XLEN-1:0]  rdata_a_o,

    input  logic [4:0]       raddr_b_i,
    output logic [XLEN-1:0]  rdata_b_o,

    input  logic             we_i,
    input  logic [4:0]       waddr_i,
    input  logic [XLEN-1:0]  wdata_i
);

  logic [XLEN-1:0] mem [1:31];

  // Write port. x0 is never written.
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      for (int i = 1; i < 32; i++) mem[i] <= '0;
    end else if (we_i && (waddr_i != 5'd0)) begin
      mem[waddr_i] <= wdata_i;
    end
  end

  // Read ports, combinational, with write-first bypass.
  always_comb begin
    if (raddr_a_i == 5'h0) begin
      rdata_a_o = 32'h0;
    end else if (we_i && waddr_i == raddr_a_i) begin
      rdata_a_o = wdata_i;
    end else begin
      rdata_a_o = mem[raddr_a_i];
    end
  end

  always_comb begin
    if (raddr_b_i == 5'h0) begin
      rdata_b_o = 32'h0;
    end else if (we_i && waddr_i == raddr_b_i) begin
      rdata_b_o = wdata_i;
    end else begin
      rdata_b_o = mem[raddr_b_i];
    end
  end

endmodule : regfile
