`include "rv32_pkg.sv"

/* verilator lint_off UNUSEDSIGNAL */
module immgen (
    input  logic [31:0]     insn_i,
    input  imm_sel_e        sel_i,
    output logic [XLEN-1:0] imm_o
);

  // The B-type and J-type immediates have SCRAMBLED bit orders. This is not an
  // error in the specification -- it is deliberate, so the sign bit and most
  // immediate bits occupy the same instruction positions across all formats,
  // which shrinks the decoder's muxes. It is also why writing this from memory
  // rather than from the spec table produces a core that fails every branch.
  //
  // Note the implicit trailing 0 on B and J: branch and jump offsets are
  // always even, so bit 0 is not encoded.
  always_comb begin
    unique case (sel_i)
      IMM_I: imm_o = {{20{insn_i[31]}}, insn_i[31:20]};
      IMM_S: imm_o = {{20{insn_i[31]}}, insn_i[31:25], insn_i[11:7]};
      IMM_B: imm_o = {{19{insn_i[31]}}, insn_i[31], insn_i[7],
                      insn_i[30:25], insn_i[11:8], 1'b0};
      IMM_U: imm_o = {insn_i[31:12], 12'b0};
      IMM_J: imm_o = {{11{insn_i[31]}}, insn_i[31], insn_i[19:12],
                      insn_i[20], insn_i[30:21], 1'b0};
      default: imm_o = '0;
    endcase
  end

endmodule : immgen
/* verilator lint_on UNUSEDSIGNAL */
