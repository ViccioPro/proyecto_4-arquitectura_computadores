// Proyecto 4 - Pochoco Trader
// pochoco_donchian: unidad de ventana deslizante para el canal de Donchian.
// Periférico MMIO en 0x8004_0000 (se activa con DON_UNIT = 1).
//
// Mantiene, para los precios que el procesador le entrega:
//   H = máximo de los últimos LE (500) precios
//   L = mínimo de los últimos LX (250) precios
//
// Método: buffer circular de 512 precios en una BRAM. Al recibir un
// precio, la unidad lo guarda y recorre los últimos min(n, LE) precios,
// del más nuevo al más antiguo, a 1 precio por ciclo, calculando H con
// todos y L con los primeros LX. Tarda n + 2 ciclos (502 con la ventana
// llena), siempre lo mismo, y trabaja en paralelo con el procesador, que
// mientras tanto espera el siguiente precio (2500 ciclos en la ronda 3).
//
// (Una versión anterior con histogramas tardaba como máximo 258 ciclos,
//  pero ocupaba ~520 celdas y el diseño no cabía en la HX1K: ver
//  rtl/descartado/pochoco_donchian_hist.v.)
//
//   offset 0x0  escritura: precio nuevo (empieza la actualización)
//               lectura  : estado (bit 0 = 1 mientras actualiza)
//   offset 0x4  lectura  : H
//   offset 0x8  lectura  : L
//   offset 0xC  lectura  : precios recibidos (satura en LE)
//
// Un precio escrito mientras la unidad está ocupada (estado = 1) se IGNORA:
// no se guarda ni cambia H, L o n. El programa debe esperar a que el estado
// vuelva a 0 antes de entregar el siguiente precio (sw/trade.s lo hace, y
// tb/tb_pochoco_donchian.sv lo comprueba).
//
// Uso típico por tick (el procesador decide con H y L de los precios
// ANTERIORES y luego entrega el precio actual):
//   esp: lw t, 0(base) ; bnez t, esp      # esperar a la unidad
//        lw H, 4(base) / lw L, 8(base)    # decidir
//        sw p, 0(base)                    # entregar el precio

module pochoco_donchian #(
  parameter integer LE = 500,   // ventana del máximo
  parameter integer LX = 250    // ventana del mínimo
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
  wire       push   = access & we_i & (off == 6'd0);

  localparam S_IDLE = 1'b0, S_SCAN = 1'b1;

  reg       state;
  reg [8:0] idx_q;   // próxima posición de escritura
  reg [8:0] n_q;     // precios recibidos (satura en LE)
  reg [8:0] a_q;     // dirección que se lee en este ciclo
  reg [8:0] ci_q;    // precios ya pedidos a la BRAM en este recorrido
  reg       v_q;     // ring_rdata trae un precio válido
  reg [7:0] h_q, l_q;

  // ------------------------------------------------------------
  // Buffer circular (se infiere como 1 SB_RAM40_4K de 512 x 8)
  // ------------------------------------------------------------
  reg [7:0] ring [0:511];
  reg [7:0] ring_rdata;
  wire      ring_we = push & (state == S_IDLE);

  integer i;
  initial for (i = 0; i < 512; i = i + 1) ring[i] = 8'd0;

  always @(posedge clk_i) begin
    if (ring_we) ring[idx_q] <= wdata_i[7:0];
    ring_rdata <= ring[a_q];
  end

  // ------------------------------------------------------------
  // FSM
  // ------------------------------------------------------------
  wire pedir = (ci_q != n_q);          // quedan precios por pedir

  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state <= S_IDLE;
      idx_q <= 9'd0;
      n_q   <= 9'd0;
      a_q   <= 9'd0;
      ci_q  <= 9'd0;
      v_q   <= 1'b0;
      h_q   <= 8'd0;
      l_q   <= 8'd255;
    end else if (state == S_IDLE) begin
      if (push) begin
        idx_q <= idx_q + 9'd1;
        if (n_q != LE) n_q <= n_q + 9'd1;
        a_q   <= idx_q;                  // empezar por el precio recién guardado
        ci_q  <= 9'd0;
        v_q   <= 1'b0;
        h_q   <= 8'd0;
        l_q   <= 8'd255;
        state <= S_SCAN;
      end
    end else begin
      // pedir el siguiente precio (del más nuevo al más antiguo)
      if (pedir) begin
        a_q  <= a_q - 9'd1;
        ci_q <= ci_q + 9'd1;
      end
      v_q <= pedir;
      // acumular el precio que llega (su posición en el recorrido es ci_q - 1)
      if (v_q) begin
        if (ring_rdata > h_q) h_q <= ring_rdata;
        if ((ci_q <= LX) && (ring_rdata < l_q)) l_q <= ring_rdata;
      end
      if (!pedir && !v_q) state <= S_IDLE;
    end
  end

  wire busy = (state != S_IDLE);

  // ------------------------------------------------------------
  // Lectura por el bus
  // ------------------------------------------------------------
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) rdata_o <= 32'b0;
    else if (access & ~we_i) begin
      case (off)
        6'd0:    rdata_o <= {31'b0, busy};
        6'd1:    rdata_o <= {24'b0, h_q};
        6'd2:    rdata_o <= {24'b0, l_q};
        6'd3:    rdata_o <= {23'b0, n_q};
        default: rdata_o <= 32'b0;
      endcase
    end
  end

endmodule
