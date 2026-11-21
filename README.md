# Proyecto 4 — Pochoco Trader

Agente de inversión que corre en el **Espino Core (RV32E)** del **Pochoco SoC**, sobre la
**Go Board (iCE40 HX1K)**. En cada tick recibe por SPI el precio de una acción desde la FPGA
maestra y responde con una decisión (mantener, comprar o vender y cuántas acciones).

Arquitectura de Computadores 2026, Universidad de los Andes.

Todo el trabajo está en la carpeta [`pochoco_soc/`](pochoco_soc). **Todos los comandos de este
README se ejecutan desde esa carpeta**, en una terminal con OSS CAD Suite cargado:

```bash
source /opt/oss-cad-suite/environment          # bash/zsh  (en fish: source /opt/oss-cad-suite/environment.fish)
cd pochoco_soc
```

---

## 1. Resumen

| | |
|---|---|
| **Estrategia** | Canal de Donchian 500/250 (seguimiento de tendencia por ruptura de canal) |
| **Regla** | Sin acciones: compra 63 si el precio supera el máximo de los 500 anteriores. Con acciones: vende 63 si cae bajo el mínimo de los 250 anteriores. Primeros 500 precios: mantener |
| **Configuración final** | `MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw` (unidad de ventana deslizante en hardware) |
| **Bitstream** | `bitstreams/trade_don_hw_m0_r1_d1.bin` |
| **Recursos** | 1118 / 1280 celdas lógicas (87 %), 13 / 16 BRAM, Fmax 44,3–47,0 MHz (5 semillas) |
| **Por tick** | Latencia precio → decisión ≤ 39 ciclos (RTL); procesador ocupado ≤ 45 ciclos; la unidad trabaja 502 ciclos en paralelo |
| **Resultados** | Patrimonio medio 11 033 en 9 series de práctica (comprar y mantener: 9 326); supera a comprar y mantener en 8/9 series |

La estrategia se eligió con validación cruzada sobre 9 series (sección 6). La estrategia
anterior (reversión a la media) y las variantes del multiplicador se conservan como
alternativas medidas; la reversión a la media es la que se probó con la FPGA maestra el 18/11.

---

## 2. Estructura

```
pochoco_soc/
├── Makefile                 todos los flujos (lista de objetivos al inicio del archivo)
├── assembler_v3.py          assembler RV32E propio (pseudoinstrucciones, .equ, mulc)
├── goboard.pcf              pines de la Go Board (SPI en PMOD: CS_n 65, MOSI 64, MISO 63, SCLK 62)
├── rtl/
│   ├── trader_top.v         top de la placa
│   ├── pochoco_soc.v        SoC: core, RAM, periféricos, SPI y aceleradores opcionales
│   ├── pochoco_donchian.v   unidad de ventana deslizante (DON_UNIT=1, 0x8004_0000)
│   ├── pochoco_mul.v        multiplicador secuencial
│   ├── pochoco_mul_mmio.v   multiplicador como periférico (MUL_MODE=2, 0x8002_0000)
│   ├── pll.v                PLL (descartado: la HX1K VQ100 no tiene PLL)
│   ├── espino_core/         core Espino (PC de 11 bits, instrucción custom-0 mulc)
│   └── descartado/          unidad Donchian con histogramas (no cabe en la FPGA)
├── sw/
│   ├── trade_don_hw.s       ★ programa final (usa la unidad Donchian)
│   ├── trade_don.s          Donchian solo software, con histogramas
│   ├── trade_don_naive.s    Donchian solo software, recorriendo el canal (línea base)
│   ├── trade.s, trade_mulc.s, trade_mmio.s   estrategia anterior (reversión a la media)
│   └── trade_min.s          prueba de conexión: muestra el precio y siempre mantiene
├── tb/
│   ├── tb_proyecto_4.sv     testbench del curso (emula a la FPGA maestra)
│   ├── tb_pochoco_donchian.sv, tb_pochoco_mul.sv   testbenches de los aceleradores
│   ├── practica.csv, practica_meta.csv, series/    series de práctica
│   └── descartado/          testbench de la unidad con histogramas
├── model/
│   ├── estrategia.py        versión de referencia del algoritmo y contabilidad
│   ├── verificar.py         compara decisiones del RTL con el modelo
│   ├── espino_iss.py        simulador del Espino con modelo de ciclos del RTL
│   ├── medir_tick.py        verifica y mide ciclos por tick en todas las series
│   ├── metricas.py          tablas y gráficos del informe
│   └── donchian_hw.py       modelo ciclo a ciclo de la unidad Donchian
├── tools/gen_trade.py       genera trade.s / trade_mulc.s / trade_mmio.s desde una plantilla
├── reports/                 reportes de yosys y nextpnr de cada versión
└── docs/metricas/           tablas LaTeX, CSV y roofline (pgfplots) para el informe
```

---

## 3. Herramientas

Versiones usadas (salida de `make versiones`, guardada en `docs/versiones.txt`):

| Herramienta | Versión |
|---|---|
| OSS CAD Suite | 20260308 |
| Yosys | Yosys 0.63+87 (git sha1 2f1cdc2df, clang++ 18.1.8) |
| nextpnr-ice40 | nextpnr-0.9-99-g4ace8952 |
| Icarus Verilog | Icarus Verilog 14.0 (devel) (s20251012-123-g49126efa7) |
| IceStorm (icepack, iceprog) | incluido en OSS CAD Suite |
| Python | Python 3.11.6 (el de OSS CAD Suite) (solo biblioteca estándar) |
| Sistema | CachyOS (Arch Linux), Linux 6.18.60-2-cachyos-lts |

---

## 4. Ensamblar `trade.s`

```bash
python3 assembler_v3.py sw/trade_don_hw.s sw/trade.hex -l sw/trade_don_hw.lst
```

- `sw/trade.hex` es el archivo que leen `trader_top.v` (síntesis) y el testbench. El Makefile lo
  regenera automáticamente desde el programa elegido con `PROG=...`.
- `-l` genera un listado dirección → palabra → línea fuente.
- El assembler acepta nombres ABI de registros (solo `x0`–`x15`, RV32E), pseudoinstrucciones
  (`li`, `la`, `mv`, `j`, `call`, `ret`, `beqz`, `bnez`, `bgt`, `ble`, …), las directivas `.equ`,
  `.word`, `.space`, `.align`, y la instrucción `mulc rd, rs1, rs2` (custom-0). Avisa si se usa un
  shift, porque en el Espino original se ejecutan como ADD.

---

## 5. Sintetizar y programar la placa

```bash
make bin  MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw     # genera bitstreams/trade_don_hw_m0_r1_d1.bin
make prog MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw     # genera y programa la Go Board (USB)
```

`make bin` ensambla el programa, sintetiza con yosys, hace place & route con nextpnr a 25 MHz y
empaqueta con icepack. Los reportes quedan en `reports/<nombre>_*`. Para programar un bitstream ya
generado: `iceprog bitstreams/<nombre>.bin`.

| Variable | Valores | Significado |
|---|---|---|
| `MUL_MODE` | 0, 1, 2 | Multiplicador: 0 = ninguno, 1 = instrucción custom-0 `mulc`, 2 = periférico MMIO |
| `MUL_RADIX` | 1, 2, 4 | Bits por ciclo del multiplicador |
| `DON_UNIT` | 0, 1 | 1 = unidad de ventana deslizante (canal de Donchian) |
| `PROG` | nombre en `sw/` sin `.s` | Programa (por defecto, el que corresponde a `MUL_MODE`) |

Versiones disponibles:

| Versión | Comando |
|---|---|
| ★ Donchian con unidad HW (final) | `make bin MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw` |
| Donchian solo software (histograma) | `make bin MUL_MODE=0 PROG=trade_don` |
| Donchian solo software (ingenua) | `make bin MUL_MODE=0 PROG=trade_don_naive` |
| Reversión, multiplicación por software | `make bin MUL_MODE=0 PROG=trade` |
| Reversión, `mulc` (probada con la maestra) | `make bin MUL_MODE=1 PROG=trade_mulc` |
| Reversión, multiplicador MMIO | `make bin MUL_MODE=2 PROG=trade_mmio` |
| Prueba de conexión | `make bin MUL_MODE=0 PROG=trade_min` |

Fmax con 5 semillas de place & route: `make fmax MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw`.

---

## 6. Testbenches y versión de referencia

### Testbench del curso (sistema completo)

```bash
make sim MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw
```

Ensambla, compila con iverilog y corre `tb/tb_proyecto_4.sv` (emula a la FPGA maestra: ronda 3,
2000 ticks), y luego ejecuta `model/verificar.py`, que compara **tick por tick** las decisiones
del RTL (`decisiones.csv`) con la versión de referencia. Debe terminar con `4/4` y
`OK: trade.s toma exactamente las mismas decisiones que el modelo`.

La serie se elige en la línea `SERIE` de `tb/tb_proyecto_4.sv`. Nota: el reset de encendido dura
65 535 ciclos (2,6 ms) y los precios enviados durante ese tiempo no llegan al procesador;
`verificar.py` lo considera (en la ronda 3 el primer precio visto es el tick 27). En la placa no
ocurre, porque la FPGA ya está encendida al empezar la ronda.

### Testbenches de los aceleradores

```bash
make tbdon              # unidad Donchian: 13 301 precios, compara H y L con el cálculo directo
make tbmul MUL_RADIX=1  # multiplicador: núcleo y periférico MMIO, resultado y latencia
```

La unidad descartada se puede probar con:
`iverilog -g2012 -s tb_pochoco_donchian_hist -o /tmp/tb_h rtl/descartado/pochoco_donchian_hist.v tb/descartado/tb_pochoco_donchian_hist.sv && vvp -n /tmp/tb_h`.

### Versión de referencia del algoritmo

```bash
make modelo                                            # estrategia vs. referencias en practica.csv
python3 model/estrategia.py tb/series/practica_tesla_2022.csv
make medir MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw     # verifica y mide ciclos en las 9 series
make metricas                                          # tablas y gráficos del informe
```

- `model/estrategia.py` implementa la estrategia y la contabilidad con las mismas reglas que el
  testbench (caja inicial 10 000, comisión 5, compra limitada por la caja, venta limitada por las
  acciones). Usa aritmética entera, igual que el assembly.
- `model/espino_iss.py` es un simulador del Espino con el modelo de ciclos del RTL (2 ciclos por
  instrucción, +1 en loads y saltos tomados) y los periféricos (SPI, multiplicador, unidad
  Donchian). Coincide con el RTL con un error de 1–3 %.

---

## 7. Co-diseño hardware/software (resumen)

Mediciones con el simulador del Espino en las 9 series (peor caso por tick; detalle en `docs/metricas/`):

| Versión | Celdas | BRAM | Fmax (MHz) | Ciclos por tick (peor) | Ronda 3 (2262 ciclos) |
|---|---|---|---|---|---|
| Donchian ingenua (SW) | 947 | 12 | 47,2 | 7561 | ✗ (334 %) |
| Donchian histograma (SW) | 947 | 12 | 45,9–47,6 | 650 | ✓ (29 %) |
| ★ Donchian unidad HW | 1118 | 13 | 44,3–47,0 | 45 | ✓ (2 %) |
| Unidad HW v1, histogramas | 1478 | 15 | — | — | no cabe en la HX1K |
| Reversión, mul SW | 947 | 12 | 45,9–47,6 | 746 | ✓ (33 %) |
| Reversión, `mulc` | 1096 | 12 | 44,1–46,0 | 173 | ✓ (8 %) |
| Reversión, mul MMIO | 1181 | 12 | 43,4–47,4 | 221 | ✓ (10 %) |

Otras decisiones de diseño:
- **Reducción de área:** PC de 32 a 11 bits y contador de ciclos opcional (−255 celdas).
- **PLL:** descartado, porque nextpnr no encuentra el bloque PLL en la HX1K VQ100.
- **Multinúcleo y pipelining:** descartados por área (el diseño base ocupaba el 92 %).
