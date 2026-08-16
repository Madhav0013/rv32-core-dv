// -----------------------------------------------------------------------------
// alu.sv -- purely combinational 32-bit ALU.
//
// Deliberately has NO state and NO clock. Everything about it is provable by a
// truth table, which makes it the ideal first thing to verify: if the cocotb
// simulation flow cannot prove this block correct, the problem is the flow and
// not the design. That is exactly why the scaffold starts here.
//
// Note the SRA implementation: `$signed(a) >>> shamt`. Getting arithmetic vs.
// logical right shift wrong is one of the two or three classic RV32I bugs, and
// it will not show up until you run a signed-negative test vector.
// -----------------------------------------------------------------------------
`include "rv32_pkg.sv"

module alu (
    input  alu_op_e            op_i,
    input  logic [XLEN-1:0]    a_i,
    input  logic [XLEN-1:0]    b_i,
    output logic [XLEN-1:0]    result_o,
    output logic               zero_o
);

  // Only the low 5 bits of operand b are the shift amount for RV32.
  logic [4:0] shamt;
  assign shamt = b_i[4:0];

  always_comb begin
    unique case (op_i)
      ALU_ADD:    result_o = a_i + b_i;
      ALU_SUB:    result_o = a_i - b_i;
      ALU_SLL:    result_o = a_i << shamt;
      ALU_SLT:    result_o = {31'b0, ($signed(a_i) < $signed(b_i))};
      ALU_SLTU:   result_o = {31'b0, (a_i < b_i)};
      ALU_XOR:    result_o = a_i ^ b_i;
      ALU_SRL:    result_o = a_i >> shamt;
      ALU_SRA:    result_o = $unsigned($signed(a_i) >>> shamt);
      ALU_OR:     result_o = a_i | b_i;
      ALU_AND:    result_o = a_i & b_i;
      ALU_PASS_B: result_o = b_i;
      default:    result_o = '0;
    endcase
  end

  assign zero_o = (result_o == '0);

endmodule : alu
