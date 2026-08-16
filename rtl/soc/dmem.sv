module dmem #(
    parameter int unsigned MEM_SIZE  = 256 * 1024,
    parameter logic [31:0] BASE_ADDR = 32'h8000_0000
) (
    input  logic        clk_i,
    input  logic        rst_ni,
    
    input  logic        req_i,
    input  logic        write_i,
    input  logic [1:0]  size_i,     // 00: byte, 01: half, 10: word
    input  logic        signed_i,   // 1: sign extend, 0: zero extend
    input  logic [31:0] addr_i,
    input  logic [31:0] wdata_i,
    
    output logic [31:0] rdata_o,
    output logic        error_o
);

  logic [7:0] mem [0:MEM_SIZE-1];

  logic [31:0] offset;
  assign offset = addr_i - BASE_ADDR;
  
  logic out_of_bounds;
  assign out_of_bounds = (addr_i < BASE_ADDR) || (addr_i >= BASE_ADDR + MEM_SIZE) || (offset + (1 << size_i) > MEM_SIZE);

  logic misaligned;
  always_comb begin
    misaligned = 1'b0;
    if (size_i == 2'b01 && addr_i[0] != 1'b0) misaligned = 1'b1;
    if (size_i == 2'b10 && addr_i[1:0] != 2'b00) misaligned = 1'b1;
  end

  assign error_o = req_i && (out_of_bounds || misaligned);

  logic [31:0] rdata_raw_comb;
  logic [31:0] rdata_raw_q;
  logic [1:0]  size_q;
  logic        signed_q;

  always_comb begin
    rdata_raw_comb = 32'h0;
    if (req_i && !write_i && !error_o) begin
      rdata_raw_comb[7:0] = mem[offset];
      if (size_i == 2'b01 || size_i == 2'b10) begin
        rdata_raw_comb[15:8] = mem[offset+1];
      end
      if (size_i == 2'b10) begin
        rdata_raw_comb[23:16] = mem[offset+2];
        rdata_raw_comb[31:24] = mem[offset+3];
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (req_i && write_i && !error_o) begin
      mem[offset] <= wdata_i[7:0];
      if (size_i == 2'b01 || size_i == 2'b10) begin
        mem[offset+1] <= wdata_i[15:8];
      end
      if (size_i == 2'b10) begin
        mem[offset+2] <= wdata_i[23:16];
        mem[offset+3] <= wdata_i[31:24];
      end
    end
    rdata_raw_q <= rdata_raw_comb;
    size_q <= size_i;
    signed_q <= signed_i;
  end

  always_comb begin
    rdata_o = rdata_raw_q;
    if (size_q == 2'b00 && signed_q && rdata_raw_q[7]) begin
      rdata_o[31:8] = 24'hFFFFFF;
    end else if (size_q == 2'b01 && signed_q && rdata_raw_q[15]) begin
      rdata_o[31:16] = 16'hFFFF;
    end
  end

endmodule : dmem
