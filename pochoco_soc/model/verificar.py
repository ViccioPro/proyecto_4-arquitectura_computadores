#!/usr/bin/env python3
"""
Compara las decisiones de la simulación RTL (decisiones.csv del testbench)
con el modelo de referencia (estrategia.py), tick por tick.

Detalle importante: el reset de encendido dura 65535 ciclos (~2,62 ms).
Los precios enviados durante el reset no llegan al procesador, así que el
modelo se alinea para empezar en el primer tick que el procesador ve.
Ese tick depende del período (ronda 3: tick 27; ronda 2: tick 3; ronda 1: tick 1).
En la placa real esto no ocurre: la FPGA ya está encendida al empezar la ronda.

Uso (desde pochoco_soc/):
  python3 model/verificar.py decisiones.csv --periodo-ns 100000
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from estrategia import Estrategia, Mercado, HOLD  # noqa: E402

T_RESET_NS = 20 + 40 * (65535 - 1)   # flanco en que por_cnt llega a 0xFFFF
T_INICIO_NS = 4000                   # espera inicial del testbench
T_PRIMER_SCLK_NS = 1500              # desde que baja CS hasta el primer flanco de SCLK


def primer_tick_visto(periodo_ns):
    n = 0
    while T_INICIO_NS + n * periodo_ns + T_PRIMER_SCLK_NS <= T_RESET_NS + 200:
        n += 1
    return n


def decisiones_esperadas(precios, inicio):
    """Decisión que el testbench debería leer en cada tick (columna 'decision')."""
    e = Estrategia()
    esperadas = [HOLD] * len(precios)
    for n in range(inicio, len(precios)):
        d = e.tick(precios[n])
        if n + 1 < len(precios):
            esperadas[n + 1] = d
    return esperadas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decisiones", help="decisiones.csv generado por tb_proyecto_4")
    ap.add_argument("--periodo-ns", type=int, default=100000)
    a = ap.parse_args()

    with open(a.decisiones) as f:
        filas = list(csv.DictReader(f))
    precios = [int(r["precio"]) for r in filas]
    rtl = [int(r["decision"], 16) for r in filas]

    inicio = primer_tick_visto(a.periodo_ns)
    esp = decisiones_esperadas(precios, inicio)

    m = Mercado()
    for n, p in enumerate(precios):
        m.ejecutar(esp[n], p)
    r = m.resumen()

    difs = [n for n in range(len(precios)) if rtl[n] != esp[n]]
    print(f"Ticks comparados: {len(precios)} (primer precio visto por el procesador: tick {inicio})")
    print(f"Patrimonio esperado: {r['patrimonio']}  | RTL: {filas[-1]['patrimonio']}")
    print(f"Ordenes esperadas:   {r['ordenes']}")
    print(f"Perdida max esperada: {r['perdida_max']}")
    if difs:
        print(f"DIFERENCIAS: {len(difs)}. Primeras:")
        for n in difs[:10]:
            print(f"  tick {n}: precio {precios[n]}  RTL {rtl[n]:02x}  modelo {esp[n]:02x}")
        sys.exit(1)
    print("OK: trade.s toma exactamente las mismas decisiones que el modelo")


if __name__ == "__main__":
    main()
