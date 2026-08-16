module soc_top (
    input  logic clk_i,
    input  logic rst_ni
);

  logic [31:0] imem_addr, imem_rdata;
  logic        imem_error;

  logic        dmem_req, dmem_write;
  logic [1:0]  dmem_size;
  logic        dmem_signed;
  logic [31:0] dmem_addr, dmem_wdata, dmem_rdata;
  logic        dmem_error;

  core u_core (
      .clk_i            (clk_i),
      .rst_ni           (rst_ni),
      .imem_req_addr_o  (imem_addr),
      .imem_read_data_i (imem_rdata),
      .imem_error_i     (imem_error),
      .dmem_req_o       (dmem_req),
      .dmem_write_o     (dmem_write),
      .dmem_size_o      (dmem_size),
      .dmem_signed_o    (dmem_signed),
      .dmem_addr_o      (dmem_addr),
      .dmem_wdata_o     (dmem_wdata),
      .dmem_rdata_i     (dmem_rdata),
      .dmem_error_i     (dmem_error)
  );

  imem #(
      .MEM_SIZE (2097152)
  ) u_imem (
      .req_addr_i   (imem_addr),
      .read_data_o  (imem_rdata),
      .error_o      (imem_error)
  );

  dmem #(
      .MEM_SIZE (2097152)
  ) u_dmem (
      .clk_i        (clk_i),
      .rst_ni       (rst_ni),
      .req_i        (dmem_req),
      .write_i      (dmem_write),
      .size_i       (dmem_size),
      .signed_i     (dmem_signed),
      .addr_i       (dmem_addr),
      .wdata_i      (dmem_wdata),
      .rdata_o      (dmem_rdata),
      .error_o      (dmem_error)
  );

endmodule : soc_top
