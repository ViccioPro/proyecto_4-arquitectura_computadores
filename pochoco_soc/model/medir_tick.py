#!/usr/bin/env python3
"""
Mide por tick, con el simulador del Espino:
  - latencia: ciclos desde que llega el precio hasta que se escribe DECISION
  - ocupado:  ciclos desde que llega el precio hasta que el programa vuelve
              a esperar el siguiente (incluye actualizar el estado). Es lo
              que debe caber en el período de cada ronda.
y verifica que las decisiones sean idénticas al modelo.
Uso: python3 medir_tick.py ../sw/trade_don.hex ../sw/trade_don.lst serie.csv [más series...]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espino_iss as E
from estrategia import leer_serie, decisiones_estrategia


def simbolo(lst, nombre):
    for l in open(lst):
        if l.startswith("# ") and "=" in l and l.split()[1] == nombre:
            return int(l.split()[3], 16)
    raise KeyError(nombre)


def medir(hexf, lst, precios, radix=1):
    esperar = simbolo(lst, "esperar")
    cpu = E.Espino(hexf, radix)
    while cpu.pc != esperar:
        cpu.step()
    out = []
    for p in precios:
        cpu.pending = (cpu.cycle, p)
        t0, i0 = cpu.cycle, cpu.instret
        n = len(cpu.decision_writes)
        cpu.step()
        while cpu.pc != esperar or len(cpu.decision_writes) == n:
            cpu.step()
            if cpu.cycle - t0 > 100000:
                raise RuntimeError("no volvió a esperar")
        c, val, _ = cpu.decision_writes[-1]
        out.append((val, c + 2 - t0, cpu.cycle - t0, cpu.instret - i0))
    return out


if __name__ == "__main__":
    hexf, lst = sys.argv[1], sys.argv[2]
    for serie in sys.argv[3:]:
        P = leer_serie(serie)
        ref = decisiones_estrategia(P)
        r = medir(hexf, lst, P)
        difs = sum(1 for a, b in zip(ref, r) if a != b[0])
        lat = [x[1] for x in r]; occ = [x[2] for x in r]; ic = [x[3] for x in r]
        print(f"{os.path.basename(serie):28s} difs {difs:3d} | latencia prom {sum(lat)/len(lat):6.1f} peor {max(lat):5d} | "
              f"ocupado prom {sum(occ)/len(occ):7.1f} peor {max(occ):5d} | IC prom {sum(ic)/len(ic):6.1f} peor {max(ic):5d}")
