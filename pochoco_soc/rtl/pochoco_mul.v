// Proyecto 4 - Pochoco Trader
// pochoco_mul: multiplicador secuencial sin signo (shift-and-add).
//
//   p = (a * b) mod 2^32,  con b < 2^BW
//
// Procesa RADIX bits de b por ciclo y termina apenas no quedan bits en
// 1 en b (terminación temprana): un b de L bits toma ceil(L/RADIX)
// ciclos (mínimo 1). Los shifts de este módulo son cableado fijo
// dentro del hardware, no instrucciones del Espino.
//
// Interfaz:
//   start_i : pulso de 1 ciclo; carga a_i y b_i y empieza.
//   busy_o  : 1 mientras multiplica.
//   done_o  : pulso de 1 ciclo cuando p_o tiene el resultado final.
//   p_o     : resultado (se mantiene hasta el próximo start_i).
//
// Lo usan dos variantes:
//   - espino_core  (instrucción custom-0 "mulc", MUL_MODE = 1)
//   - pochoco_mul_mmio (periférico MMIO, MUL_MODE = 2)

module pochoco_mul #(
  parameter integer RADIX = 1,   // bits de b por ciclo (1, 2 o 4)
  parameter integer BW    = 16   // bits de b soportados
) (
  input  wire        clk_i,
  input  wire        rst_ni,
  input  wire        start_i,
  input  wire [31:0] a_i,
  input  wire [31:0] b_i,
  output wire        busy_o,
  output reg         done_o,
  output wire [31:0] p_o
);

  reg [31:0]   a_q;
  reg [BW-1:0] b_q;
  reg [31:0]   acc_q;
  reg          run_q;

  // Producto parcial: a * b[RADIX-1:0]
  reg [31:0] pp;
  integer i;
  always @* begin
    pp = 32'b0;
    for (i = 0; i < RADIX; i = i + 1)
      if (b_q[i]) pp = pp + (a_q << i);
  end

  wire [BW-1:0] b_next = b_q >> RADIX;

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      a_q    <= 32'b0;
      b_q    <= {BW{1'b0}};
      acc_q  <= 32'b0;
      run_q  <= 1'b0;
      done_o <= 1'b0;
    end else if (start_i) begin
      a_q    <= a_i;
      b_q    <= b_i[BW-1:0];
      acc_q  <= 32'b0;
      run_q  <= 1'b1;
      done_o <= 1'b0;
    end else if (run_q) begin
      acc_q <= acc_q + pp;
      a_q   <= a_q << RADIX;
      b_q   <= b_next;
      if (b_next == {BW{1'b0}}) begin
        run_q  <= 1'b0;
        done_o <= 1'b1;
      end
    end else begin
      done_o <= 1'b0;
    end
  end

  assign busy_o = run_q;
  assign p_o    = acc_q;

endmodule
