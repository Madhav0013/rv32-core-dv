`include "rv32_pkg.sv"

module branch_unit (
    input  logic [XLEN-1:0] a_i,
    input  logic [XLEN-1:0] b_i,
    input  br_op_e          br_op_i,
    output logic            taken_o
);

  always_comb begin
    taken_o = 1'b0;
    unique case (br_op_i)
      BR_EQ:  taken_o = (a_i == b_i);
      BR_NE:  taken_o = (a_i != b_i);
      BR_LT:  taken_o = ($signed(a_i) < $signed(b_i));
      BR_GE:  taken_o = ($signed(a_i) >= $signed(b_i));
      BR_LTU: taken_o = (a_i < b_i);
      BR_GEU: taken_o = (a_i >= b_i);
      default: taken_o = 1'b0;
    endcase
  end

endmodule : branch_unit
