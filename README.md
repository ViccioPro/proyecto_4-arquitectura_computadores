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
| **Estrategia** | Canal de Donchian 500/250 con compra inicial y meta de patrimonio 13 500 (seguimiento de tendencia por ruptura de canal) |
| **Regla** | Si el patrimonio (caja + acciones × p) llega a 13 500: vende todo y no vuelve a operar. Si no: primer precio, compra 63; sin acciones, compra 63 si el precio supera el máximo de los 500 anteriores; con acciones, vende 63 si cae bajo el mínimo de los 250 anteriores; precios 2 a 500, mantener |
| **Configuración final** | `MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta` (unidad de ventana deslizante en hardware) |
| **Bitstream** | `bitstreams/trade_don_meta_m0_r1_d1.bin` (no se sube al repositorio; se genera con `make bin`) |
| **Recursos** | 1139 / 1280 celdas lógicas (89 %), 13 / 16 BRAM, Fmax 43,1–45,8 MHz (5 semillas) |
| **Por tick** | Canal: ≤ 47 ciclos; con la contabilidad de la meta, procesador ocupado ≤ 957 ciclos (42 % de la ronda 3, en el tick que contabiliza una compra); la unidad trabaja 502 ciclos en paralelo |
| **Resultados** | Patrimonio medio 12 646 en 9 series de práctica (comprar y mantener: 9 326); peor serie 9 500; supera a comprar y mantener en 8/9 series |

El canal se eligió con validación cruzada sobre 9 series (sección 6). La meta de patrimonio se
eligió con el mismo método: la validación cruzada eligió 13 500 en 8 de 9 casos (media fuera de
muestra 12 077, contra 11 525 sin meta). El programa lleva su propia contabilidad con las reglas de
la maestra (caja inicial 10 000, comisión 5), sin información externa a la serie. La compra inicial
("time in the market") sube el patrimonio medio de las series de práctica de 11 033 a 11 525, pero
la peor serie baja de 9 011 a 8 344, y en tramos que empiezan en otros puntos de las series no hay
diferencia en promedio (detalle en el informe). La versión sin compra inicial (`trade_don_hw.s`)
se conserva para comparar las alternativas de hardware. La estrategia anterior (reversión a la
media) y las variantes del multiplicador se conservan como alternativas medidas; la reversión a la
media es la que se probó con la FPGA maestra el 18/11.

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
│   ├── trade_don_meta.s     ★ programa final (unidad Donchian + compra inicial + meta 13 500)
│   ├── trade_don_ini.s      Donchian con la unidad + compra inicial, sin meta
│   ├── trade_don_hw.s       Donchian con la unidad, sin compra inicial
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
python3 assembler_v3.py sw/trade_don_meta.s sw/trade.hex -l sw/trade_don_meta.lst
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
make bin  MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta   # genera bitstreams/trade_don_meta_m0_r1_d1.bin
make prog MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta   # genera y programa la Go Board (USB)
```

`make bin` ensambla el programa, sintetiza con yosys, hace place & route con nextpnr a 25 MHz y
empaqueta con icepack. Los reportes quedan en `reports/<nombre>_*`. Para programar un bitstream ya
generado: `iceprog bitstreams/<nombre>.bin`.

**Reinicio entre series:** el SoC solo tiene reset de encendido. Antes de cada serie hay que
desconectar y volver a conectar el USB de la Go Board, **antes de que la maestra empiece a enviar
precios**: la placa carga el programa desde su memoria flash y parte desde cero (caja, contador,
posición y meta). Si no se reinicia, el programa arrastra el estado de la serie anterior; si se
reconecta con la serie ya empezada, pierde los primeros precios y la compra inicial.

| Variable | Valores | Significado |
|---|---|---|
| `MUL_MODE` | 0, 1, 2 | Multiplicador: 0 = ninguno, 1 = instrucción custom-0 `mulc`, 2 = periférico MMIO |
| `MUL_RADIX` | 1, 2, 4 | Bits por ciclo del multiplicador |
| `DON_UNIT` | 0, 1 | 1 = unidad de ventana deslizante (canal de Donchian) |
| `PROG` | nombre en `sw/` sin `.s` | Programa (por defecto, el que corresponde a `MUL_MODE`) |

Versiones disponibles:

| Versión | Comando |
|---|---|
| ★ Donchian con unidad HW, compra inicial y meta (final) | `make bin MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta` |
| Donchian con unidad HW y compra inicial, sin meta | `make bin MUL_MODE=0 DON_UNIT=1 PROG=trade_don_ini` |
| Donchian con unidad HW, sin compra inicial | `make bin MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw` |
| Donchian solo software (histograma) | `make bin MUL_MODE=0 PROG=trade_don` |
| Donchian solo software (ingenua) | `make bin MUL_MODE=0 PROG=trade_don_naive` |
| Reversión, multiplicación por software | `make bin MUL_MODE=0 PROG=trade` |
| Reversión, `mulc` (probada con la maestra) | `make bin MUL_MODE=1 PROG=trade_mulc` |
| Reversión, multiplicador MMIO | `make bin MUL_MODE=2 PROG=trade_mmio` |
| Prueba de conexión | `make bin MUL_MODE=0 PROG=trade_min` |

Fmax con 5 semillas de place & route: `make fmax MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta`.

---

## 6. Testbenches y versión de referencia

### Testbench del curso (sistema completo)

```bash
make sim MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta
```

Ensambla, compila con iverilog y corre `tb/tb_proyecto_4.sv` (emula a la FPGA maestra: ronda 3,
2000 ticks), y luego ejecuta `model/verificar.py`, que compara **tick por tick** las decisiones
del RTL (`decisiones.csv`) con la versión de referencia. Debe terminar con `4/4` y
`OK: trade.s toma exactamente las mismas decisiones que el modelo`. Con `practica_meta.csv` (la
serie configurada, 2000 ticks), la versión final termina con 11 244 (en esos ticks no alcanza la
meta). Para ver la venta por meta en RTL: `SERIE = "tb/series/practica_netflix_2022.csv"` y
`NTICKS = 3000` → 13 523, con la venta por meta en el tick 2176.

El modelo aplica por defecto la compra inicial y la meta de 13 500 (la versión final). Para
verificar las otras versiones se cambian con variables de entorno:

| Programa | Prefijo del comando |
|---|---|
| `trade_don_meta` (final) | — |
| `trade_don_ini` | `env META=0` |
| `trade_don_hw`, `trade_don`, `trade_don_naive` | `env META=0 COMPRA_INICIAL=0` |

Por ejemplo: `env META=0 COMPRA_INICIAL=0 make sim MUL_MODE=0 DON_UNIT=1 PROG=trade_don_hw`. La
meta del programa está en la línea `.equ META` de `sw/trade_don_meta.s`; si se cambia, hay que usar
el mismo valor en `env META=...`.

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
make medir MUL_MODE=0 DON_UNIT=1 PROG=trade_don_meta   # verifica y mide ciclos en las 9 series
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
| Donchian ingenua (SW) | 948 | 12 | 43,5–46,5 | 7561 | ✗ (334 %) |
| Donchian histograma (SW) | 948 | 12 | 43,5–46,5 | 650 | ✓ (29 %) |
| Donchian unidad HW | 1139 | 13 | 43,1–45,8 | 45 | ✓ (2 %) |
| Donchian unidad HW + compra inicial | 1139 | 13 | 43,1–45,8 | 47 | ✓ (2 %) |
| ★ Donchian unidad HW + compra inicial + meta (final) | 1139 | 13 | 43,1–45,8 | 957 | ✓ (42 %) |
| Unidad HW v1, histogramas | 1478 | 15 | — | — | no cabe en la HX1K |
| Reversión, mul SW | 948 | 12 | 43,5–46,5 | 746 | ✓ (33 %) |
| Reversión, `mulc` | 1095 | 12 | 43,2–45,2 | 173 | ✓ (8 %) |
| Reversión, mul MMIO | 1211 | 12 | 39,9–43,9 | 221 | ✓ (10 %) |

Las versiones solo software comparten el mismo hardware (diseño base), y las dos versiones con la
unidad (sin compra inicial, con compra inicial y con meta) también; por eso tienen los mismos
recursos.

Otras decisiones de diseño:
- **Reducción de área:** PC de 32 a 11 bits y contador de ciclos opcional (−255 celdas).
- **PLL:** descartado, porque nextpnr no encuentra el bloque PLL en la HX1K VQ100.
- **Multinúcleo y pipelining:** descartados por área (el diseño base ocupaba el 92 %).
