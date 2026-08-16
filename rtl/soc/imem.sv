module imem #(
    parameter int unsigned MEM_SIZE  = 256 * 1024,
    parameter logic [31:0] BASE_ADDR = 32'h8000_0000
) (
    input  logic [31:0] req_addr_i,
    output logic [31:0] read_data_o,
    output logic        error_o
);

  logic [31:0] mem [0:(MEM_SIZE/4)-1];

  logic [31:0] offset;
  assign offset = req_addr_i - BASE_ADDR;
  
  logic out_of_bounds;
  assign out_of_bounds = (req_addr_i < BASE_ADDR) || (req_addr_i >= BASE_ADDR + MEM_SIZE);
  
  logic misaligned;
  assign misaligned = (req_addr_i[1:0] != 2'b00);

  assign error_o = out_of_bounds || misaligned;

  always_comb begin
    if (error_o) begin
      read_data_o = 32'h0;
    end else begin
      read_data_o = mem[offset[31:2]];
    end
  end

endmodule : imem
