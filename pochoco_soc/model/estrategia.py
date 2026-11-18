#!/usr/bin/env python3
"""
Modelo de referencia del algoritmo - Proyecto 4 (Pochoco Trader)

Estrategia: reversión a la media con bandas de desviación estándar,
stop-loss y bloqueo de recompra (pensada para mercados volátiles).
  Ventana de N = 256 precios. S = suma, Q = suma de cuadrados.
  d   = N*p - S            (N veces la distancia del precio a la media)
  var = N*Q - S^2          (N^2 veces la varianza de la ventana)
  Estados: FUERA (sin acciones), DENTRO (con acciones), BLOQUEADO (sin
  acciones, después de un stop-loss).
  - FUERA:     compra 63 si d < 0 y d^2 > 2*var    (p < media - 1,41 sigma)
  - DENTRO:    vende 63 si d > 0 y d^2 > var       (p > media + 1 sigma)
               vende 63 si d < 0 y d^2 > 16*var    (stop-loss: p < media - 4 sigma)
                 y pasa a BLOQUEADO
  - BLOQUEADO: vuelve a FUERA cuando d > 0 (el precio cruzó sobre la media)
  Mientras la ventana no está llena (primeros N-1 precios): mantener.

Aritmética entera de 32 bits sin signo, igual que trade.s, para que las
decisiones sean idénticas bit a bit. Valores máximos: S <= 65280,
S^2 y N*Q <= 4,26e9 (caben en 32 bits). En assembly, si var >= 2^28 el
stop-loss no se evalúa (16*var no cabe en 32 bits, y además ya es mayor
que cualquier d^2 posible, así que la condición sería falsa igual).

Uso:
  python3 estrategia.py practica.csv            # serie completa
  python3 estrategia.py practica.csv --ticks 2000
"""
import csv
import argparse

N = 256
K2_ENTRADA = 2          # (1,41 sigma)^2
K2_SALIDA = 1           # (1 sigma)^2
K2_STOP = 16            # (4 sigma)^2
CAJA0 = 10000
COMISION = 5
BUY63 = 0x7F            # 01 111111
SELL63 = 0xBF           # 10 111111
HOLD = 0x00


def leer_serie(ruta):
    with open(ruta) as f:
        return [int(r["price"]) for r in csv.DictReader(f)]


FUERA, DENTRO, BLOQUEADO = 0, 1, 2


class Estrategia:
    """Recibe un precio por tick y devuelve el byte de decisión."""

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
        ("Estrategia (N=256, bandas+stop)", simular(precios, decisiones_estrategia)),
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
