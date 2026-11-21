// Copyright 2026 Universidad de los Andes.
// Licensed under the Solderpad Hardware License, Version 0.51 (the "License");
// you may not use this file except in compliance with the License.
// SPDX-License-Identifier: SHL-0.51
//
// Course: Arquitectura de Computadores (2026)
// 
// Authors:
// - Nicolás Villegas <navillegas@miuandes.cl>

// [Proyecto 4] Variante del multiplicador, elegida al compilar:
//   MUL_MODE 0 = solo software, 1 = instrucción custom-0 (mulc),
//   2 = periférico MMIO en 0x8002_0000.   MUL_RADIX = bits por ciclo.
// Ejemplo: iverilog -DMUL_MODE=1 ...   /   yosys: read_verilog -DMUL_MODE=1 ...
`ifndef MUL_MODE
`define MUL_MODE 0
`endif
`ifndef MUL_RADIX
`define MUL_RADIX 1
`endif
// [Proyecto 4] DON_UNIT = 1 agrega la unidad de ventana deslizante
// (canal de Donchian) en 0x8004_0000. Ej.: iverilog -DDON_UNIT=1 ...
`ifndef DON_UNIT
`define DON_UNIT 0
`endif

module pochoco_soc #(
  parameter NumWords   = 512,
  parameter MemFile    = "../sw/blink.hex",
  // [Proyecto 4] 1 = contador de ciclos en 0x8000_000C (para medir en la placa)
  //              0 = sin contador (ahorra celdas lógicas; lee 0)
  parameter CycleCounter = 0,
  parameter MulMode      = `MUL_MODE,
  parameter MulRadix     = `MUL_RADIX,
  parameter DonUnit      = `DON_UNIT
) (
  input  wire       i_Clk,

  output wire [3:0] o_LED,
  input  wire [3:0] i_Switch,

  output wire       o_Segment1_A, o_Segment1_B, o_Segment1_C, o_Segment1_D,
  output wire       o_Segment1_E, o_Segment1_F, o_Segment1_G,
  output wire       o_Segment2_A, o_Segment2_B, o_Segment2_C, o_Segment2_D,
  output wire       o_Segment2_E, o_Segment2_F, o_Segment2_G,

  input  wire       i_SPI_SCLK,
  input  wire       i_SPI_MOSI,
  input  wire       i_SPI_CS_n,
  output wire       o_SPI_MISO
);

  wire clk;
  assign clk = i_Clk;

  // Power-on reset
  // Acá fue clave cambiar la cantidad de ciclos
  // ya que antes se demoraba tan poco que me 
  // generaba problemas al prender la FPGA,
  // a veces funcionaba bien (una de cada 20 veces aprox)
  reg  [15:0] por_cnt = 16'b0;
  wire        rst_ni;
  always @(posedge clk) begin
    if (por_cnt != 16'hFFFF) por_cnt <= por_cnt + 16'd1;
  end
  assign rst_ni = (por_cnt == 16'hFFFF);
  // Lo importante es que al darle más tiempo en el reset
  // se pudo estabilizar y ahora se puede iniciar el juego
  // conectando y desconectando la FPGA de su fuente 

  
  // Core-memory wiring
  wire        instr_req;
  wire [31:0] instr_addr, instr_rdata;

  wire        data_req, data_we;
  wire [3:0]  data_be;
  wire [31:0] data_addr, data_wdata, data_rdata;

  // [Proyecto 4] PC de $clog2(NumWords)+2 bits (11 bits para 2 KB de RAM)
  espino_core #(
    .BootAddr (32'h0000_0000),
    .PcWidth  ($clog2(NumWords) + 2),
    .MulEnable(MulMode == 1),
    .MulRadix (MulRadix)
  ) u_core (
    .clk_i         (clk),
    .rst_ni        (rst_ni),
    .instr_req_o   (instr_req),
    .instr_addr_o  (instr_addr),
    .instr_rdata_i (instr_rdata),
    .data_req_o    (data_req),
    .data_we_o     (data_we),
    .data_be_o     (data_be),
    .data_addr_o   (data_addr),
    .data_wdata_o  (data_wdata),
    .data_rdata_i  (data_rdata)
  );

  wire is_mmio, spi_sel, per_sel, mul_sel, don_sel;
  assign is_mmio = data_addr[31];
  // [Proyecto 4] 0x8002_xxxx = multiplicador MMIO (solo con MulMode = 2)
  assign mul_sel = (MulMode == 2) ? (is_mmio & data_addr[17]) : 1'b0;
  // [Proyecto 4] 0x8004_xxxx = unidad Donchian (solo con DonUnit = 1)
  assign don_sel = (DonUnit != 0) ? (is_mmio & data_addr[18]) : 1'b0;
  assign per_sel = is_mmio & ~data_addr[16] & ~mul_sel & ~don_sel;
  assign spi_sel = is_mmio &  data_addr[16];

  wire ram_b_req, per_req, spi_req, mul_req, don_req;
  assign ram_b_req = data_req & ~is_mmio;
  assign per_req   = data_req &  per_sel;
  assign spi_req   = data_req &  spi_sel;
  assign mul_req   = data_req &  mul_sel;
  assign don_req   = data_req &  don_sel;

  wire [31:0] ram_b_rdata, per_rdata, spi_rdata, mul_rdata, don_rdata;

  reg rd_is_per, rd_is_spi, rd_is_mul, rd_is_don;
  always @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      rd_is_per <= 1'b0;
      rd_is_spi <= 1'b0;
      rd_is_mul <= 1'b0;
      rd_is_don <= 1'b0;
    end else if (data_req & ~data_we) begin
      rd_is_per <= per_sel;
      rd_is_spi <= spi_sel;
      rd_is_mul <= mul_sel;
      rd_is_don <= don_sel;
    end
  end
  assign data_rdata = rd_is_per ? per_rdata :
                      rd_is_spi ? spi_rdata :
                      rd_is_mul ? mul_rdata :
                      rd_is_don ? don_rdata : ram_b_rdata;

  pochoco_ram #(.NumWords(NumWords), .MemFile(MemFile)) u_ram (
    .clk_i     (clk),
    .a_req_i   (instr_req),
    .a_addr_i  (instr_addr),
    .a_rdata_o (instr_rdata),
    .b_req_i   (ram_b_req),
    .b_we_i    (data_we),
    .b_be_i    (data_be),
    .b_addr_i  (data_addr),
    .b_wdata_i (data_wdata),
    .b_rdata_o (ram_b_rdata)
  );

  // Peripherals
  wire [6:0] seg1, seg2;

  pochoco_periph #(.CYCLE_COUNTER(CycleCounter)) u_periph (
    .clk_i     (clk),
    .rst_ni    (rst_ni),
    .sel_i     (per_sel),
    .req_i     (per_req),
    .we_i      (data_we),
    .addr_i    (data_addr[7:0]),
    .wdata_i   (data_wdata),
    .rdata_o   (per_rdata),
    .leds_o    (o_LED),
    .btn_i     (i_Switch),
    .seg1_o    (seg1),
    .seg2_o    (seg2)
  );

  // SPI Slave
  pochoco_spi_slave u_spi (
    .clk_i      (clk),
    .rst_ni     (rst_ni),
    .sel_i      (spi_sel),
    .req_i      (spi_req),
    .we_i       (data_we),
    .addr_i     (data_addr[7:0]),
    .wdata_i    (data_wdata),
    .rdata_o    (spi_rdata),
    .spi_sclk_i (i_SPI_SCLK),
    .spi_mosi_i (i_SPI_MOSI),
    .spi_cs_n_i (i_SPI_CS_n),
    .spi_miso_o (o_SPI_MISO)
  );

  // [Proyecto 4] Multiplicador MMIO
  generate
    if (MulMode == 2) begin : g_mul_mmio
      pochoco_mul_mmio #(.RADIX(MulRadix)) u_mul (
        .clk_i   (clk),
        .rst_ni  (rst_ni),
        .sel_i   (mul_sel),
        .req_i   (mul_req),
        .we_i    (data_we),
        .addr_i  (data_addr[7:0]),
        .wdata_i (data_wdata),
        .rdata_o (mul_rdata)
      );
    end else begin : g_sin_mul_mmio
      assign mul_rdata = 32'b0;
    end
  endgenerate

  // [Proyecto 4] Unidad de ventana deslizante (canal de Donchian)
  generate
    if (DonUnit != 0) begin : g_donchian
      pochoco_donchian u_don (
        .clk_i   (clk),
        .rst_ni  (rst_ni),
        .sel_i   (don_sel),
        .req_i   (don_req),
        .we_i    (data_we),
        .addr_i  (data_addr[7:0]),
        .wdata_i (data_wdata),
        .rdata_o (don_rdata)
      );
    end else begin : g_sin_donchian
      assign don_rdata = 32'b0;
    end
  endgenerate

  // 7-seg is active-low on the board
  assign {o_Segment1_G, o_Segment1_F, o_Segment1_E, o_Segment1_D,
          o_Segment1_C, o_Segment1_B, o_Segment1_A} = ~seg1;
  assign {o_Segment2_G, o_Segment2_F, o_Segment2_E, o_Segment2_D,
          o_Segment2_C, o_Segment2_B, o_Segment2_A} = ~seg2;

endmodule