#!/usr/bin/env python3
"""
Modelo de referencia del algoritmo - Proyecto 4 (Pochoco Trader)

Estrategia: reversión a la media con banda de desviación estándar.
  Ventana de N = 64 precios. S = suma, Q = suma de cuadrados.
  d   = N*p - S            (N veces la distancia del precio a la media)
  var = N*Q - S^2          (N^2 veces la varianza de la ventana)
  - Sin acciones: compra 63 si d < 0 y d^2 > K2*var   (p bajo media - 2 sigma)
  - Con acciones: vende 63 si d > 0                     (p volvió sobre la media)
  - En otro caso: mantener.
  Mientras la ventana no está llena (primeros N-1 precios): mantener.

Todo es aritmética entera de 32 bits sin signo/con signo, igual que trade.s,
para que las decisiones sean idénticas bit a bit.

Uso:
  python3 estrategia.py practica.csv            # serie completa
  python3 estrategia.py practica.csv --ticks 2000
"""
import csv
import argparse

N = 64
K2 = 4                  # (2 sigma)^2
CAJA0 = 10000
COMISION = 5
BUY63 = 0x7F            # 01 111111
SELL63 = 0xBF           # 10 111111
HOLD = 0x00


def leer_serie(ruta):
    with open(ruta) as f:
        return [int(r["price"]) for r in csv.DictReader(f)]


class Estrategia:
    """Recibe un precio por tick y devuelve el byte de decisión."""

    def __init__(self):
        self.buf_p = [0] * N
        self.buf_q = [0] * N
        self.idx = 0
        self.count = 0
        self.S = 0
        self.Q = 0
        self.dentro = False

    def tick(self, p):
        p2 = p * p
        self.S += p - self.buf_p[self.idx]
        self.Q += p2 - self.buf_q[self.idx]
        self.buf_p[self.idx] = p
        self.buf_q[self.idx] = p2
        self.idx = (self.idx + 1) % N
        if self.count < N:
            self.count += 1
            if self.count < N:
                return HOLD
        d = N * p - self.S
        if self.dentro:
            if d > 0:
                self.dentro = False
                return SELL63
            return HOLD
        if d >= 0:
            return HOLD
        var = N * self.Q - self.S * self.S
        if d * d > K2 * var:
            self.dentro = True
            return BUY63
        return HOLD


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
        ("Estrategia (N=64, 2 sigma)", simular(precios, decisiones_estrategia)),
        ("No operar", simular(precios, referencia_no_operar)),
        ("Comprar y mantener", referencia_comprar_mantener(precios)),
    ]
    print(f"Serie: {a.serie}, {len(precios)} ticks")
    print(f"{'':28s}{'Patrimonio':>11s}{'Ordenes':>9s}{'Comisiones':>12s}{'Perd. max':>11s}")
    for nombre, r in filas:
        print(f"{nombre:28s}{r['patrimonio']:11d}{r['ordenes']:9d}"
              f"{r['comisiones']:12d}{r['perdida_max']:11d}")


if __name__ == "__main__":
    main()
