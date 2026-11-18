# ============================================================
# Proyecto 4 - Pochoco Trader (Go Board, iCE40 HX1K)
#
# Uso (desde pochoco_soc/):
#   make sim    MUL_MODE=1    simula tb_proyecto_4 y verifica las decisiones
#   make bin    MUL_MODE=1    genera el bitstream en bitstreams/
#   make prog   MUL_MODE=1    genera el bitstream y programa la Go Board
#   make iss    MUL_MODE=1    estimación rápida de IC/ciclos/CPI (simulador Python)
#   make tbmul  MUL_RADIX=1   testbench del multiplicador
#   make modelo               modelo de referencia vs. no operar / comprar y mantener
#   make clean                borra archivos generados
#
# Variantes (MUL_MODE):
#   0 = solo software        (sw/trade.s)
#   1 = instrucción custom-0 (sw/trade_mulc.s)   <- variante final, por defecto
#   2 = periférico MMIO      (sw/trade_mmio.s)
# MUL_RADIX = bits por ciclo del multiplicador (1, 2 o 4).
# PROG = programa a usar; por defecto el de la variante.
#   Ej.: make prog MUL_MODE=0 PROG=trade_min   (prueba de conexión)
#
# Los reportes de yosys y nextpnr quedan en reports/.
# ============================================================

MUL_MODE  ?= 1
MUL_RADIX ?= 1

PROG_0 := trade
PROG_1 := trade_mulc
PROG_2 := trade_mmio
PROG   ?= $(PROG_$(MUL_MODE))

TOP  := trader_top
PCF  := goboard.pcf
ASM  := assembler_v3.py
HEX  := sw/trade.hex
SRC  := $(wildcard rtl/*.v rtl/espino_core/*.v)
DEFS := -DMUL_MODE=$(MUL_MODE) -DMUL_RADIX=$(MUL_RADIX)
NAME := $(PROG)_m$(MUL_MODE)_r$(MUL_RADIX)

.PHONY: all hex synth pnr bin prog sim iss tbmul modelo clean

all: bin

# ---- Paso 0: ensamblar el programa como sw/trade.hex ----
# (sw/trade.hex es el archivo que leen trader_top y el testbench)
hex:
	python3 $(ASM) sw/$(PROG).s $(HEX) -l sw/$(PROG).lst

# ---- Paso 1: síntesis (yosys) ----
synth: hex
	mkdir -p reports
	yosys -q -l reports/$(NAME)_yosys.log -p "read_verilog $(DEFS) $(SRC); synth_ice40 -top $(TOP) -json $(TOP).json; tee -o reports/$(NAME)_stat.txt stat"
	@grep -E "SB_" reports/$(NAME)_stat.txt

# ---- Paso 2: place & route (nextpnr) ----
pnr: synth
	@echo "nextpnr: place & route (registro completo en reports/$(NAME)_nextpnr.log)"
	@nextpnr-ice40 --hx1k --package vq100 --freq 25 --json $(TOP).json --pcf $(PCF) --asc $(TOP).asc -l reports/$(NAME)_nextpnr.log > /dev/null 2>&1 || (grep -E "ERROR" reports/$(NAME)_nextpnr.log; false)
	@grep -E "ICESTORM_LC|ICESTORM_RAM" reports/$(NAME)_nextpnr.log | tail -2
	@grep -E "Max frequency" reports/$(NAME)_nextpnr.log | tail -1

# ---- Paso 3: bitstream (icepack) ----
bin: pnr
	mkdir -p bitstreams
	icepack $(TOP).asc bitstreams/$(NAME).bin
	@echo "Bitstream: bitstreams/$(NAME).bin"

# ---- Paso 4: programar la placa (iceprog) ----
prog: bin
	iceprog bitstreams/$(NAME).bin

# ---- Simulación del sistema completo + verificación ----
sim: hex
	iverilog -g2012 $(DEFS) -s tb_proyecto_4 -o /tmp/tb_p4 $$(yosys-config --datdir)/ice40/cells_sim.v $(SRC) tb/tb_proyecto_4.sv
	vvp -n /tmp/tb_p4
	python3 model/verificar.py decisiones.csv --periodo-ns 100000

# ---- Estimación rápida con el simulador del Espino ----
iss: hex
	python3 model/espino_iss.py $(HEX) tb/practica.csv --radix $(MUL_RADIX)

# ---- Testbench del multiplicador ----
tbmul:
	iverilog -g2012 -DMUL_RADIX=$(MUL_RADIX) -s tb_pochoco_mul -o /tmp/tb_mul rtl/pochoco_mul.v rtl/pochoco_mul_mmio.v tb/tb_pochoco_mul.sv
	vvp -n /tmp/tb_mul

# ---- Modelo de referencia ----
modelo:
	python3 model/estrategia.py tb/practica.csv

clean:
	rm -f $(TOP).json $(TOP).asc $(TOP).bin decisiones.csv
