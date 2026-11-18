// Proyecto 4 - Testbench del multiplicador secuencial
// Prueba pochoco_mul (núcleo) y pochoco_mul_mmio (periférico) contra a*b.
// Revisa el resultado y la latencia (ceil(bits(b)/RADIX) ciclos, mínimo 1).
//
// Correr desde pochoco_soc/ (RADIX = 1; cambiar con -DMUL_RADIX=2 o 4):
//   iverilog -g2012 -DMUL_RADIX=1 -s tb_pochoco_mul -o /tmp/tb_mul rtl/pochoco_mul.v rtl/pochoco_mul_mmio.v tb/tb_pochoco_mul.sv
//   vvp -n /tmp/tb_mul

`timescale 1ns/1ps
`ifndef MUL_RADIX
`define MUL_RADIX 1
`endif

module tb_pochoco_mul;

  localparam int R = `MUL_RADIX;

  logic clk = 0;
  always #20 clk = ~clk;
  logic rst_n = 0;

  // ---------------- DUT 1: núcleo ----------------
  logic        start = 0;
  logic [31:0] a = 0, b = 0;
  wire         busy, done;
  wire  [31:0] p;

  pochoco_mul #(.RADIX(R)) dut (
    .clk_i(clk), .rst_ni(rst_n), .start_i(start), .a_i(a), .b_i(b),
    .busy_o(busy), .done_o(done), .p_o(p));

  // ---------------- DUT 2: periférico MMIO ----------------
  logic        sel = 0, req = 0, we = 0;
  logic [7:0]  addr = 0;
  logic [31:0] wdata = 0;
  wire  [31:0] rdata;

  pochoco_mul_mmio #(.RADIX(R)) dut_mmio (
    .clk_i(clk), .rst_ni(rst_n), .sel_i(sel), .req_i(req), .we_i(we),
    .addr_i(addr), .wdata_i(wdata), .rdata_o(rdata));

  // ---------------- utilidades ----------------
  int total = 0, aprobadas = 0;

  task automatic chequear(input bit cond, input string nombre);
    total++;
    if (cond) aprobadas++;
    else $display("FAIL %s", nombre);
  endtask

  function automatic int ciclos_esperados(input logic [31:0] bb);
    int bits = 0;
    for (int k = 0; k < 16; k++) if (bb[k]) bits = k + 1;
    if (bits == 0) return 1;
    return (bits + R - 1) / R;
  endfunction

  task automatic probar_nucleo(input logic [31:0] aa, input logic [31:0] bb);
    int n;
    logic [31:0] esperado;
    esperado = aa * bb[15:0];
    @(negedge clk); a = aa; b = bb; start = 1;
    @(negedge clk); start = 0;
    n = 0;
    while (!done && n <= 40) begin
      @(negedge clk);
      n++;
    end
    chequear(p == esperado,
             $sformatf("nucleo %0d * %0d = %0d (esperado %0d)", aa, bb, p, esperado));
    chequear(n == ciclos_esperados(bb),
             $sformatf("latencia %0d * %0d: %0d ciclos (esperado %0d)", aa, bb, n, ciclos_esperados(bb)));
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

  task automatic probar_mmio(input logic [31:0] aa, input logic [31:0] bb);
    logic [31:0] estado, prod, esperado;
    int vueltas;
    esperado = aa * bb[15:0];
    bus_escribir(8'h00, aa);
    bus_escribir(8'h04, bb);
    vueltas = 0;
    estado = 1;
    while (estado[0] && vueltas < 40) begin
      bus_leer(8'h00, estado);
      vueltas++;
    end
    bus_leer(8'h08, prod);
    chequear(prod == esperado,
             $sformatf("mmio %0d * %0d = %0d (esperado %0d)", aa, bb, prod, esperado));
  endtask

  // ---------------- pruebas ----------------
  // Casos borde: ceros, máximos de la estrategia (255, 16320), b de 16 bits
  // completos y desborde de 32 bits (0xFFFF_FFFF * 2).
  task automatic casos_borde(input bit mmio);
    if (mmio) begin
      probar_mmio(0, 0);      probar_mmio(1, 0);         probar_mmio(0, 1);
      probar_mmio(255, 255);  probar_mmio(16320, 16320); probar_mmio(12345, 1);
      probar_mmio(1, 65535);  probar_mmio(65535, 65535); probar_mmio(32'hFFFF_FFFF, 2);
      probar_mmio(7, 32768);
    end else begin
      probar_nucleo(0, 0);      probar_nucleo(1, 0);         probar_nucleo(0, 1);
      probar_nucleo(255, 255);  probar_nucleo(16320, 16320); probar_nucleo(12345, 1);
      probar_nucleo(1, 65535);  probar_nucleo(65535, 65535); probar_nucleo(32'hFFFF_FFFF, 2);
      probar_nucleo(7, 32768);
    end
  endtask

  initial begin
    #100 rst_n = 1;

    casos_borde(0);
    for (int k = 0; k < 300; k++) probar_nucleo($urandom, $urandom & 32'hFFFF);

    casos_borde(1);
    for (int k = 0; k < 100; k++) probar_mmio($urandom, $urandom & 32'hFFFF);

    $display("RADIX = %0d", R);
    $display("Pruebas aprobadas: %0d/%0d", aprobadas, total);
    $finish;
  end

endmodule
