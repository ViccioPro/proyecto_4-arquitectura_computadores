#!/usr/bin/env python3
"""
Modelo de referencia del algoritmo - Proyecto 4 (Pochoco Trader)

ESTRATEGIA FINAL (sw/trade.s): canal de Donchian 500/250 con compra
inicial y meta de patrimonio (EstrategiaDonchian, valores por defecto).
Con los precios ANTERIORES al actual, H = máximo de los últimos 500 y
L = mínimo de los últimos 250. En orden de prioridad:
  1. Meta: lleva su propia contabilidad (Mercado, mismas reglas que la
     maestra); si el patrimonio caja + acciones*p llega a META
     (1,35 x caja inicial = 13500), vende todo y no vuelve a operar.
  2. Primer precio: compra 63 (compra inicial).
  3. Precios 2 a 500: mantener (la ventana no está llena).
  4. Sin acciones: compra 63 si p > H.  Con acciones: vende 63 si p < L.
Elegida con validación cruzada en 9 series (el canal y la meta).

Versiones anteriores, que se verifican con variables de entorno:
  sw/trade_don_ini.s                    env META=0
  sw/trade_don_hw.s, trade_don.s,
  trade_don_naive.s                     env META=0 COMPRA_INICIAL=0
  sw/trade_reversion.s, trade_mulc.s,
  trade_mmio.s                          EstrategiaReversion (metricas.py)

EstrategiaReversion es la estrategia anterior (probada con la FPGA maestra
el 18/11): reversión a la media con ventana de N = 256 precios, bandas de
1,41 sigma (entrada) y 1 sigma (salida), stop-loss a -4 sigma y bloqueo de
recompra. Usa aritmética entera de 32 bits sin signo, igual que
sw/trade_reversion.s, para que las decisiones sean idénticas bit a bit.

Uso:
  python3 estrategia.py practica.csv            # serie completa
  python3 estrategia.py practica.csv --ticks 2000
"""
import csv
import argparse
import os

N = 256
K2_ENTRADA = 2          # (1,41 sigma)^2
K2_SALIDA = 1           # (1 sigma)^2
K2_STOP = 16            # (4 sigma)^2
CAJA0 = 10000
COMISION = 5
# Compra inicial (1 = sw/trade_don_ini.s, 0 = sw/trade_don_hw.s / trade_don.s)
COMPRA_INICIAL = os.environ.get("COMPRA_INICIAL", "1") != "0"
# Meta de patrimonio (sw/trade_don_meta.s, versión final): si el patrimonio llega
# a META, vende todo y no vuelve a operar. Para verificar trade_don_ini.s se usa
# META=0; para trade_don_hw.s / trade_don.s, META=0 y COMPRA_INICIAL=0.
META = int(os.environ.get("META", str(CAJA0 * 135 // 100)))   # 1,35 x caja inicial = 13500
BUY63 = 0x7F            # 01 111111
SELL63 = 0xBF           # 10 111111
HOLD = 0x00


def leer_serie(ruta):
    with open(ruta) as f:
        return [int(r["price"]) for r in csv.DictReader(f)]


LE = 500                # ventana del máximo (entrada)
LX = 250                # ventana del mínimo (salida)

FUERA, DENTRO, BLOQUEADO = 0, 1, 2


class EstrategiaReversion:
    """[Anterior, probada con la maestra el 18/11] Reversión a la media N=256."""

    def __init__(self):
        self.buf = [0] * N
        self.idx = 0
        self.count = 0
        self.S = 0
        self.Q = 0
        self.estado = FUERA

    def tick(self, p):
        viejo = self.buf[self.idx]
        self.buf[self.idx] = p
        self.S += p - viejo
        self.Q += p * p - viejo * viejo
        self.idx = (self.idx + 1) % N
        if self.count < N:
            self.count += 1
            if self.count < N:
                return HOLD
        d = N * p - self.S
        if self.estado == BLOQUEADO:
            if d > 0:
                self.estado = FUERA
            return HOLD
        if d == 0:
            return HOLD
        var = N * self.Q - self.S * self.S
        if self.estado == DENTRO:
            if d > 0:
                if d * d > K2_SALIDA * var:
                    self.estado = FUERA
                    return SELL63
                return HOLD
            if d * d > K2_STOP * var:
                self.estado = BLOQUEADO
                return SELL63
            return HOLD
        if d < 0 and d * d > K2_ENTRADA * var:
            self.estado = DENTRO
            return BUY63
        return HOLD


class EstrategiaDonchian:
    """Canal de Donchian (ruptura de canal, seguimiento de tendencia).

    Con los precios ANTERIORES al actual:
      H = máximo de los últimos LE = 500 precios
      L = mínimo de los últimos LX = 250 precios
    - Sin posición: compra 63 si p > H   (rompe el máximo de 500 ticks)
    - Con posición: vende 63 si p < L    (rompe el mínimo de 250 ticks)
    - En otro caso: mantener. Primeros 500 precios: mantener.
    - Con compra inicial: el primer precio compra 63 (queda con posición).
    - Con meta (meta > 0): lleva su propia contabilidad, igual a la de la
      maestra; si el patrimonio caja + acciones*p llega a la meta, vende todo
      y no vuelve a operar en el resto de la serie.
    """

    def __init__(self, compra_inicial=None, meta=None):
        self.hist = []
        self.dentro = False
        self.primero = True
        self.compra_inicial = COMPRA_INICIAL if compra_inicial is None else compra_inicial
        self.meta = META if meta is None else meta
        self.cuenta = Mercado()      # contabilidad propia (la orden se ejecuta al precio siguiente)
        self.pendiente = HOLD
        self.asegurado = False

    def tick(self, p):
        dec = HOLD
        if self.meta:
            self.cuenta.ejecutar(self.pendiente, p)
        if self.asegurado:
            pass
        elif self.meta and self.cuenta.w >= self.meta:
            self.asegurado = True
            if self.cuenta.acciones > 0:
                self.dentro = False
                dec = SELL63
        elif self.primero and self.compra_inicial:
            self.dentro = True
            dec = BUY63
        elif len(self.hist) >= LE:
            if not self.dentro and p > max(self.hist[-LE:]):
                self.dentro = True
                dec = BUY63
            elif self.dentro and p < min(self.hist[-LX:]):
                self.dentro = False
                dec = SELL63
        self.primero = False
        self.pendiente = dec
        self.hist.append(p)
        if len(self.hist) > LE:
            del self.hist[0]
        return dec


# Estrategia vigente (la usan verificar.py y espino_iss.py)
Estrategia = EstrategiaDonchian


class Mercado:
    """Contabilidad con las mismas reglas que tb_proyecto_4.sv."""

    def __init__(self):
        self.caja = CAJA0
        self.acciones = 0
        self.w = CAJA0
        self.peak = CAJA0
        self.max_dd = 0
        self.ordenes = 0

    def ejecutar(self, decision, p):
        q = decision & 0x3F
        accion = decision >> 6
        if accion == 1:
            q = min(q, (self.caja - COMISION) // p)
            if q > 0:
                self.caja -= q * p + COMISION
                self.acciones += q
                self.ordenes += 1
        elif accion == 2:
            q = min(q, self.acciones)
            if q > 0 and self.caja + q * p >= COMISION:
                self.caja += q * p - COMISION
                self.acciones -= q
                self.ordenes += 1
        self.w = self.caja + self.acciones * p
        self.peak = max(self.peak, self.w)
        self.max_dd = max(self.max_dd, self.peak - self.w)

    def resumen(self):
        return {"patrimonio": self.w, "ordenes": self.ordenes,
                "comisiones": self.ordenes * COMISION, "perdida_max": self.max_dd}


def simular(precios, decisiones_de):
    """decisiones_de(precios) -> lista de decisiones calculadas con cada precio.
    La decisión calculada con p[n-1] se ejecuta al precio p[n]."""
    m = Mercado()
    decs = decisiones_de(precios)
    previa = HOLD
    for n, p in enumerate(precios):
        m.ejecutar(previa, p)
        previa = decs[n]
    return m.resumen()


def decisiones_estrategia(precios):
    e = Estrategia()
    return [e.tick(p) for p in precios]


def referencia_no_operar(precios):
    return [HOLD] * len(precios)


def referencia_comprar_mantener(precios):
    # Igual que el testbench: compra todo lo posible con el primer precio
    q = (CAJA0 - COMISION) // precios[0]
    w = CAJA0 - COMISION - q * precios[0] + q * precios[-1]
    peak, dd, caja = CAJA0, 0, CAJA0 - COMISION - q * precios[0]
    for p in precios:
        wi = caja + q * p
        peak = max(peak, wi)
        dd = max(dd, peak - wi)
    return {"patrimonio": w, "ordenes": 1, "comisiones": COMISION, "perdida_max": dd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serie")
    ap.add_argument("--ticks", type=int, default=None)
    a = ap.parse_args()
    precios = leer_serie(a.serie)[:a.ticks]
    filas = [
        (f"Donchian 500/250{' + compra ini.' if COMPRA_INICIAL else ''}{f' + meta {META}' if META else ''}", simular(precios, decisiones_estrategia)),
        ("No operar", simular(precios, referencia_no_operar)),
        ("Comprar y mantener", referencia_comprar_mantener(precios)),
    ]
    print(f"Serie: {a.serie}, {len(precios)} ticks")
    print(f"{'':32s}{'Patrimonio':>11s}{'Ordenes':>9s}{'Comisiones':>12s}{'Perd. max':>11s}")
    for nombre, r in filas:
        print(f"{nombre:32s}{r['patrimonio']:11d}{r['ordenes']:9d}"
              f"{r['comisiones']:12d}{r['perdida_max']:11d}")


if __name__ == "__main__":
    main()
