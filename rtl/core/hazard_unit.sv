`include "rv32_pkg.sv"

module hazard_unit (
    input  logic       id_ex_valid_i,
    input  logic       id_ex_mem_read_i,
    input  logic [4:0] id_ex_rd_addr_i,
    
    input  logic [4:0] id_rs1_addr_i,
    input  logic [4:0] id_rs2_addr_i,
    
    input  logic       branch_taken_i,

    output logic       pc_stall_o,
    output logic       if_id_hold_o,
    output logic       if_id_flush_o,
    output logic       id_ex_bubble_o,
    output logic       id_ex_flush_o
);

  logic load_use_stall_o;

  // Load-use: a load's data is not available until the end of MEM, so an
  // immediately dependent instruction cannot be rescued by forwarding. It must
  // stall exactly one cycle.
  //
  // Detected in ID, not IF: the dependency is only visible once the consumer's
  // source registers have been decoded.
  assign load_use_stall_o =
      id_ex_valid_i && id_ex_mem_read_i && (id_ex_rd_addr_i != 5'd0) &&
      ((id_ex_rd_addr_i == id_rs1_addr_i) || (id_ex_rd_addr_i == id_rs2_addr_i));

  // Stall: hold PC and if_id_q, clear id_ex_q.valid to inject a bubble.
  assign pc_stall_o     = load_use_stall_o;
  assign if_id_hold_o   = load_use_stall_o;
  assign id_ex_bubble_o = load_use_stall_o;

  // Flush on a taken branch or jump resolved in EX. Clear VALID BITS -- do not
  // inject NOP encodings. A NOP is a real instruction that would appear in the
  // retire trace and cause a spurious lockstep mismatch; a cleared valid bit
  // produces nothing at all.
  assign if_id_flush_o = branch_taken_i;
  assign id_ex_flush_o = branch_taken_i;

endmodule : hazard_unit
