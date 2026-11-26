#!/usr/bin/env bash
# ============================================================
# Proyecto 4 - Evidencia de las alternativas de hardware descartadas.
# Sintetiza (yosys) y hace place & route (nextpnr) de tres versiones que
# no quedaron en el diseño final, usando copias temporales modificadas
# del RTL actual (el RTL del repositorio no se toca):
#
#   1. pll           : trader_top con USE_PLL = 1 (rtl/pll.v). nextpnr
#                      debe fallar: la HX1K VQ100 no tiene PLL.
#   2. sin_reduccion : diseño base sin la reducción de área (contador de
#                      programa de 32 bits y contador de ciclos de 32 bits).
#   3. unidad_v1     : unidad Donchian con histogramas
#                      (rtl/descartado/pochoco_donchian_hist.v). nextpnr
#                      debe fallar: no cabe en las 1280 celdas.
#
# Los registros quedan en reports/evidencias/<nombre>_{yosys,stat,nextpnr}.
# Uso (desde pochoco_soc/): make evidencias   (o bash tools/evidencias.sh)
# ============================================================
set -u
cd "$(dirname "$0")/.."

OUT=reports/evidencias
mkdir -p "$OUT"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# El contenido del programa no cambia los recursos; se usa el final.
python3 assembler_v3.py sw/trade.s sw/trade.hex > /dev/null

COMUN="rtl/pll.v rtl/pochoco_mul_mmio.v rtl/pochoco_mul.v rtl/pochoco_periph.v rtl/pochoco_ram.v rtl/pochoco_spi_slave.v rtl/espino_core/*.v"

sintetizar() {   # $1 nombre, $2 defines, $3... archivos
    local n=$1 d=$2
    shift 2
    echo "== $n"
    if ! yosys -q -l "$OUT/${n}_yosys.log" -p "read_verilog $d $*; synth_ice40 -top trader_top -json $T/top.json; tee -o $OUT/${n}_stat.txt stat"; then
        echo "   yosys falló (ver $OUT/${n}_yosys.log)"
        return
    fi
    grep -E "SB_LUT4|SB_CARRY|SB_RAM40_4K" "$OUT/${n}_stat.txt" | sed 's/^/   /'
    if nextpnr-ice40 --hx1k --package vq100 --freq 25 --json "$T/top.json" --pcf goboard.pcf \
           --asc "$T/top.asc" -l "$OUT/${n}_nextpnr.log" > /dev/null 2>&1; then
        echo "   nextpnr: OK"
    else
        echo "   nextpnr: FALLÓ (esperado en pll y unidad_v1)"
    fi
    grep -E "ERROR|ICESTORM_LC:|ICESTORM_RAM:|Max frequency" "$OUT/${n}_nextpnr.log" | tail -4 | sed 's/^/   /'
}

# 1. PLL
sed 's/parameter USE_PLL = 0;/parameter USE_PLL = 1;/' rtl/trader_top.v > "$T/trader_top.v"
grep -q "parameter USE_PLL = 1;" "$T/trader_top.v" || { echo "no se pudo activar USE_PLL"; exit 1; }
sintetizar pll "-DMUL_MODE=0 -DMUL_RADIX=1 -DDON_UNIT=0" \
    $COMUN rtl/pochoco_donchian.v rtl/pochoco_soc.v "$T/trader_top.v"

# 2. Diseño base sin la reducción de área
sed -e 's/\.PcWidth  (\$clog2(NumWords) + 2)/.PcWidth  (32)/' \
    -e 's/parameter CycleCounter = 0/parameter CycleCounter = 1/' rtl/pochoco_soc.v > "$T/pochoco_soc.v"
grep -q "PcWidth  (32)" "$T/pochoco_soc.v" && grep -q "CycleCounter = 1" "$T/pochoco_soc.v" \
    || { echo "no se pudo desactivar la reducción de área"; exit 1; }
sintetizar sin_reduccion "-DMUL_MODE=0 -DMUL_RADIX=1 -DDON_UNIT=0" \
    $COMUN rtl/pochoco_donchian.v "$T/pochoco_soc.v" rtl/trader_top.v

# 3. Unidad Donchian v1 (histogramas)
sed 's/module pochoco_donchian_hist/module pochoco_donchian/' rtl/descartado/pochoco_donchian_hist.v > "$T/pochoco_donchian.v"
sintetizar unidad_v1 "-DMUL_MODE=0 -DMUL_RADIX=1 -DDON_UNIT=1" \
    $COMUN "$T/pochoco_donchian.v" rtl/pochoco_soc.v rtl/trader_top.v

echo "Registros en $OUT/"
