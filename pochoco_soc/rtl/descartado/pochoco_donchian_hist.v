// DESCARTADO (21/11): version con histogramas en BRAM. Correcta (13301/13301
// pruebas, peor caso 258 ciclos) pero ocupa ~520 celdas: el diseno completo
// necesita 1478 de 1280 en la HX1K. Se reemplazo por el recorrido secuencial.
// Proyecto 4 - Pochoco Trader
// pochoco_donchian: unidad de ventana deslizante para el canal de Donchian.
// Periférico MMIO en 0x8004_0000 (se activa con DON_UNIT = 1).
//
// Mantiene, para los precios que el procesador le entrega:
//   H = máximo de los últimos LE (500) precios
//   L = mínimo de los últimos LX (250) precios
// usando un buffer circular y dos histogramas en BRAM (mismo método que
// sw/trade_don.s, pero en hardware y en paralelo con el procesador).
//
//   offset 0x0  escritura: precio nuevo (empieza la actualización)
//               lectura  : estado (bit 0 = 1 mientras actualiza)
//   offset 0x4  lectura  : H
//   offset 0x8  lectura  : L
//   offset 0xC  lectura  : precios recibidos (satura en LE)
//
// Duración de una actualización: 4 ciclos + búsqueda. La búsqueda solo
// ocurre cuando sale de la ventana el último precio igual a H (o a L);
// avanza 1 valor por ciclo y las dos búsquedas van en paralelo, así que
// el peor caso es 4 + 255 ciclos.
//
// Uso típico por tick (el procesador decide con H y L de los precios
// ANTERIORES y luego entrega el precio actual):
//   esp: lw t, 0(base) ; bnez t, esp      # esperar a la unidad
//        lw H, 4(base) / lw L, 8(base)    # decidir
//        sw p, 0(base)                    # entregar el precio

module pochoco_donchian_hist #(
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

  // ------------------------------------------------------------
  // Memorias (se infieren como SB_RAM40_4K: 3 bloques)
  // ------------------------------------------------------------
  reg [7:0]  ring [0:511];      // últimos 512 precios
  reg [15:0] cmax [0:255];      // histograma de la ventana de LE
  reg [7:0]  cmin [0:255];      // histograma de la ventana de LX

  integer i;
  initial begin
    for (i = 0; i < 512; i = i + 1) ring[i] = 8'd0;
    for (i = 0; i < 256; i = i + 1) begin
      cmax[i] = 16'd0;
      cmin[i] = 8'd0;
    end
  end

  // Puertos (direcciones y datos de escritura vienen de la FSM)
  reg  [8:0]  ring_raddr, ring_waddr;
  reg         ring_we;
  reg  [7:0]  ring_wdata, ring_rdata;

  reg  [7:0]  cmax_raddr, cmax_waddr;
  reg         cmax_we;
  reg  [15:0] cmax_wdata, cmax_rdata;

  reg  [7:0]  cmin_raddr, cmin_waddr;
  reg         cmin_we;
  reg  [7:0]  cmin_wdata, cmin_rdata;

  always @(posedge clk_i) begin
    if (ring_we) ring[ring_waddr] <= ring_wdata;
    ring_rdata <= ring[ring_raddr];
  end
  always @(posedge clk_i) begin
    if (cmax_we) cmax[cmax_waddr] <= cmax_wdata;
    cmax_rdata <= cmax[cmax_raddr];
  end
  always @(posedge clk_i) begin
    if (cmin_we) cmin[cmin_waddr] <= cmin_wdata;
    cmin_rdata <= cmin[cmin_raddr];
  end

  // ------------------------------------------------------------
  // Estado
  // ------------------------------------------------------------
  localparam [2:0] S_IDLE = 3'd0,
                   S_R1   = 3'd1,   // leer p[t-250]; leer cuentas de p
                   S_R2   = 3'd2,   // cuentas de p + 1; leer p[t-500]
                   S_R3   = 3'd3,   // guardar p; leer cuentas de los que salen
                   S_R4   = 3'd4,   // cuentas de los que salen - 1
                   S_SCAN = 3'd5;   // buscar nuevo H y/o L

  reg [2:0] state;
  reg [7:0] p_q;          // precio que entra
  reg [7:0] o_lx_q;       // precio que sale de la ventana de LX
  reg [7:0] o_le_q;       // precio que sale de la ventana de LE
  reg [7:0] h_q, l_q;     // H y L
  reg [8:0] idx_q;        // posición de escritura en el buffer
  reg [8:0] n_q;          // precios recibidos (satura en LE)
  reg       smax_q, smin_q;   // búsqueda en curso
  reg [7:0] pmax_q, pmin_q;   // dirección leída en el ciclo anterior

  wire rem_lx = (n_q >= LX);
  wire rem_le = (n_q >= LE);

  // Valores derivados en S_R4
  wire [15:0] cmax_dec = cmax_rdata - 16'd1;
  wire [7:0]  cmin_dec = cmin_rdata - 8'd1;
  wire need_smax = rem_le & (cmax_dec == 16'd0) & (o_le_q == h_q);
  wire need_smin = rem_lx & (cmin_dec == 8'd0)  & (o_lx_q == l_q);

  // ------------------------------------------------------------
  // Lógica combinacional de los puertos de memoria
  // ------------------------------------------------------------
  always @* begin
    ring_raddr = idx_q;  ring_waddr = idx_q;  ring_we = 1'b0;  ring_wdata = p_q;
    cmax_raddr = p_q;    cmax_waddr = p_q;    cmax_we = 1'b0;  cmax_wdata = 16'd0;
    cmin_raddr = p_q;    cmin_waddr = p_q;    cmin_we = 1'b0;  cmin_wdata = 8'd0;

    case (state)
      S_R1: begin
        ring_raddr = idx_q + 9'd262;          // (idx - 250) mod 512
        cmax_raddr = p_q;
        cmin_raddr = p_q;
      end
      S_R2: begin
        ring_raddr = idx_q + 9'd12;           // (idx - 500) mod 512
        cmax_we    = 1'b1;  cmax_waddr = p_q;  cmax_wdata = cmax_rdata + 16'd1;
        cmin_we    = 1'b1;  cmin_waddr = p_q;  cmin_wdata = cmin_rdata + 8'd1;
      end
      S_R3: begin
        ring_we    = 1'b1;  ring_waddr = idx_q;  ring_wdata = p_q;
        cmax_raddr = ring_rdata;              // p[t-500] (llega en este ciclo)
        cmin_raddr = o_lx_q;                  // p[t-250]
      end
      S_R4: begin
        cmax_we    = rem_le;  cmax_waddr = o_le_q;  cmax_wdata = cmax_dec;
        cmin_we    = rem_lx;  cmin_waddr = o_lx_q;  cmin_wdata = cmin_dec;
        cmax_raddr = h_q - 8'd1;              // primer paso de las búsquedas
        cmin_raddr = l_q + 8'd1;
      end
      S_SCAN: begin
        cmax_raddr = pmax_q - 8'd1;
        cmin_raddr = pmin_q + 8'd1;
      end
      default: ;
    endcase
  end

  // ------------------------------------------------------------
  // FSM
  // ------------------------------------------------------------
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state  <= S_IDLE;
      p_q    <= 8'd0;
      o_lx_q <= 8'd0;
      o_le_q <= 8'd0;
      h_q    <= 8'd0;       // cualquier precio lo supera
      l_q    <= 8'd255;
      idx_q  <= 9'd0;
      n_q    <= 9'd0;
      smax_q <= 1'b0;
      smin_q <= 1'b0;
      pmax_q <= 8'd0;
      pmin_q <= 8'd0;
    end else begin
      case (state)
        S_IDLE: begin
          if (push) begin
            p_q   <= wdata_i[7:0];
            state <= S_R1;
          end
        end
        S_R1: state <= S_R2;
        S_R2: begin
          o_lx_q <= ring_rdata;
          if (p_q > h_q) h_q <= p_q;
          if (p_q < l_q) l_q <= p_q;
          state  <= S_R3;
        end
        S_R3: begin
          o_le_q <= ring_rdata;
          state  <= S_R4;
        end
        S_R4: begin
          idx_q  <= idx_q + 9'd1;
          if (!rem_le) n_q <= n_q + 9'd1;
          smax_q <= need_smax;
          smin_q <= need_smin;
          pmax_q <= h_q - 8'd1;
          pmin_q <= l_q + 8'd1;
          state  <= (need_smax | need_smin) ? S_SCAN : S_IDLE;
        end
        S_SCAN: begin
          // cmax_rdata / cmin_rdata corresponden a pmax_q / pmin_q
          if (smax_q) begin
            if (cmax_rdata != 16'd0) begin
              h_q    <= pmax_q;
              smax_q <= 1'b0;
            end else begin
              pmax_q <= pmax_q - 8'd1;
            end
          end
          if (smin_q) begin
            if (cmin_rdata != 8'd0) begin
              l_q    <= pmin_q;
              smin_q <= 1'b0;
            end else begin
              pmin_q <= pmin_q + 8'd1;
            end
          end
          if ((!smax_q || cmax_rdata != 16'd0) && (!smin_q || cmin_rdata != 8'd0))
            state <= S_IDLE;
        end
        default: state <= S_IDLE;
      endcase
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
