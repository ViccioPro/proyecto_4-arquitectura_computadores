// trader_top: top-level de la placa para el Proyecto 4 (Pochoco Trader)
module trader_top (
    input  wire       i_Clk,

    // UART
    input  wire       i_UART_RX,
    output wire       o_UART_TX,

    // LEDs y botones
    output wire [3:0] o_LED,
    input  wire [3:0] i_Switch,

    // Display 1
    output wire o_Segment1_A,
    output wire o_Segment1_B,
    output wire o_Segment1_C,
    output wire o_Segment1_D,
    output wire o_Segment1_E,
    output wire o_Segment1_F,
    output wire o_Segment1_G,

    // Display 2
    output wire o_Segment2_A,
    output wire o_Segment2_B,
    output wire o_Segment2_C,
    output wire o_Segment2_D,
    output wire o_Segment2_E,
    output wire o_Segment2_F,
    output wire o_Segment2_G,

    // SPI
    input  wire i_SPI_CS_n,
    input  wire i_SPI_MOSI,
    input  wire i_SPI_SCLK,
    output wire o_SPI_MISO
);

    // UART no se utiliza en este proyecto
    assign o_UART_TX = 1'b1;

    // --------------------------------------------------------
    // Reloj del sistema
    //   USE_PLL = 0 : reloj directo de la placa (25 MHz)
    //   USE_PLL = 1 : reloj generado por el PLL (rtl/pll.v,
    //                 creado con icepll; frecuencia indicada ahí)
    // El testbench del curso instancia pochoco_soc directamente,
    // por lo que este cambio no afecta a la simulación.
    // --------------------------------------------------------
    // La HX1K en encapsulado VQ100 (Go Board) no tiene PLL: nextpnr no
    // encuentra donde ubicarlo. Por eso el valor por defecto es 0.
    parameter USE_PLL = 0;

    wire clk_sys;

    generate
        if (USE_PLL) begin : g_pll
            wire pll_locked;   // no se usa: el reset de encendido de
                               // pochoco_soc (65535 ciclos) dura mucho
                               // más que el enganche del PLL
            pll u_pll (
                .clock_in  (i_Clk),
                .clock_out (clk_sys),
                .locked    (pll_locked)
            );
        end else begin : g_sin_pll
            assign clk_sys = i_Clk;
        end
    endgenerate

    pochoco_soc #(
        .MemFile("sw/trade.hex")
    ) u_pochoco (
        .i_Clk(clk_sys),

        .o_LED(o_LED),
        .i_Switch(i_Switch),

        .o_Segment1_A(o_Segment1_A),
        .o_Segment1_B(o_Segment1_B),
        .o_Segment1_C(o_Segment1_C),
        .o_Segment1_D(o_Segment1_D),
        .o_Segment1_E(o_Segment1_E),
        .o_Segment1_F(o_Segment1_F),
        .o_Segment1_G(o_Segment1_G),

        .o_Segment2_A(o_Segment2_A),
        .o_Segment2_B(o_Segment2_B),
        .o_Segment2_C(o_Segment2_C),
        .o_Segment2_D(o_Segment2_D),
        .o_Segment2_E(o_Segment2_E),
        .o_Segment2_F(o_Segment2_F),
        .o_Segment2_G(o_Segment2_G),

        .i_SPI_CS_n(i_SPI_CS_n),
        .i_SPI_MOSI(i_SPI_MOSI),
        .i_SPI_SCLK(i_SPI_SCLK),
        .o_SPI_MISO(o_SPI_MISO)
    );

endmodule
