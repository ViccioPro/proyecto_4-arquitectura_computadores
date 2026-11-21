// Proyecto 4 - Testbench de la unidad de ventana deslizante (pochoco_donchian)
// Entrega precios por el bus y, después de cada uno, compara H y L con el
// cálculo directo (máximo de los últimos 500, mínimo de los últimos 250).
// También mide cuántos ciclos queda ocupada la unidad por precio
// (con la ventana llena debe ser 502: recorre 500 precios + 2 ciclos).
//
// Correr desde pochoco_soc/:
//   iverilog -g2012 -s tb_pochoco_donchian -o /tmp/tb_don rtl/pochoco_donchian.v tb/tb_pochoco_donchian.sv
//   vvp -n /tmp/tb_don

`timescale 1ns/1ps

module tb_pochoco_donchian;

  localparam int LE = 500, LX = 250, NMAX = 20000;

  logic clk = 0;
  always #20 clk = ~clk;
  logic rst_n = 0;

  logic        sel = 0, req = 0, we = 0;
  logic [7:0]  addr = 0;
  logic [31:0] wdata = 0;
  wire  [31:0] rdata;

  pochoco_donchian dut (
    .clk_i(clk), .rst_ni(rst_n), .sel_i(sel), .req_i(req), .we_i(we),
    .addr_i(addr), .wdata_i(wdata), .rdata_o(rdata));

  // Ciclos ocupada por precio (desde la FSM)
  int ocupado = 0, peor_ocupado = 0, suma_ocupado = 0;
  always @(posedge clk) if (dut.state != 0) ocupado++;

  int hist [NMAX];
  int n = 0;
  int total = 0, aprobadas = 0;

  task automatic chequear(input bit cond, input string nombre);
    total++;
    if (cond) aprobadas++;
    else if (total - aprobadas <= 10) $display("FAIL %s", nombre);
  endtask

  task automatic bus_escribir(input logic [7:0] ad, input logic [31:0] d);
    @(negedge clk); sel = 1; req = 1; we = 1; addr = ad; wdata = d;
    @(negedge clk); sel = 0; req = 0; we = 0;
  endtask

  task automatic bus_leer(input logic [7:0] ad, output logic [31:0] d);
    @(negedge clk); sel = 1; req = 1; we = 0; addr = ad;
    @(negedge clk); sel = 0; req = 0;
    d = rdata;
  endtask

  task automatic entregar(input int p);
    logic [31:0] st, h, l, cnt;
    int ref_h, ref_l, k;
    ocupado = 0;
    bus_escribir(8'h00, p);
    st = 1;
    while (st[0]) bus_leer(8'h00, st);
    if (ocupado > peor_ocupado) peor_ocupado = ocupado;
    suma_ocupado += ocupado;
    hist[n] = p;
    n++;
    ref_h = 0;
    ref_l = 255;
    for (k = n - 1; k >= 0 && k >= n - LE; k--) if (hist[k] > ref_h) ref_h = hist[k];
    for (k = n - 1; k >= 0 && k >= n - LX; k--) if (hist[k] < ref_l) ref_l = hist[k];
    bus_leer(8'h04, h);
    bus_leer(8'h08, l);
    bus_leer(8'h0C, cnt);
    chequear(h == ref_h && l == ref_l && cnt == ((n < LE) ? n : LE),
             $sformatf("precio %0d (p=%0d): H=%0d L=%0d n=%0d, esperado H=%0d L=%0d",
                       n - 1, p, h, l, cnt, ref_h, ref_l));
  endtask

  int p, k;

  initial begin
    #100 rst_n = 1;

    // 1) Paseo aleatorio (parecido a las series de práctica)
    p = 150;
    for (k = 0; k < 6000; k++) begin
      p = p + ($urandom % 3) - 1;
      if ($urandom % 200 == 0) p = p + ($urandom % 31) - 15;   // saltos
      if (p < 1) p = 1;
      if (p > 255) p = 255;
      entregar(p);
    end
    // 2) Alternado 1 / 255
    for (k = 0; k < 1000; k++) entregar((k % 2) ? 1 : 255);
    // 3) Escalones de 300 ticks (peor caso de búsqueda)
    for (k = 0; k < 3000; k++) entregar(((k / 300) % 2) ? 1 : 255);
    // 4) Aleatorio uniforme
    for (k = 0; k < 2000; k++) entregar(1 + ($urandom % 255));
    // 5) Constante y un pico aislado
    for (k = 0; k < 600; k++) entregar(150);
    entregar(255);
    for (k = 0; k < 700; k++) entregar(150);

    $display("Precios entregados: %0d", n);
    $display("Ciclos ocupada por precio: promedio %0d, peor %0d", suma_ocupado / n, peor_ocupado);
    $display("Pruebas aprobadas: %0d/%0d", aprobadas, total);
    $finish;
  end

endmodule
