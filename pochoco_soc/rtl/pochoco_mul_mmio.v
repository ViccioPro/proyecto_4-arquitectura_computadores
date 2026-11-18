// Proyecto 4 - Pochoco Trader
// pochoco_mul_mmio: multiplicador como periférico MMIO (MUL_MODE = 2).
// Base 0x8002_0000.
//
//   offset 0x0  escritura: A
//               lectura  : estado (bit 0 = 1 mientras multiplica)
//   offset 0x4  escritura: B y empieza la multiplicación
//   offset 0x8  lectura  : producto (A * B) mod 2^32
//
// Uso desde assembly:
//   sw   a, 0(base)
//   sw   b, 4(base)
// esp: lw   t, 0(base)
//   bnez t, esp
//   lw   p, 8(base)

module pochoco_mul_mmio #(
  parameter integer RADIX = 1
) (
  input  wire        clk_i,
  input  wire        rst_ni,
  input  wire        sel_i,
  input  wire        req_i,
  input  wire        we_i,
  input  wire [7:0]  addr_i,
  input  wire [31:0] wdata_i,
  output reg  [31:0] rdata_o
);

  wire [5:0] off    = addr_i[7:2];
  wire       access = sel_i & req_i;

  reg  [31:0] a_q;
  wire        start = access & we_i & (off == 6'd1);
  wire        busy;
  wire [31:0] p;

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni)                              a_q <= 32'b0;
    else if (access & we_i & (off == 6'd0))   a_q <= wdata_i;
  end

  pochoco_mul #(.RADIX(RADIX)) u_mul (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .start_i (start),
    .a_i     (a_q),
    .b_i     (wdata_i),
    .busy_o  (busy),
    .done_o  (),
    .p_o     (p)
  );

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) rdata_o <= 32'b0;
    else if (access & ~we_i) begin
      case (off)
        6'd0:    rdata_o <= {31'b0, busy};
        6'd2:    rdata_o <= p;
        default: rdata_o <= 32'b0;
      endcase
    end
  end

endmodule
