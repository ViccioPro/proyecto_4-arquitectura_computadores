"""
Modelo ciclo a ciclo de rtl/pochoco_donchian.v (recorrido secuencial del
buffer circular en BRAM con lectura síncrona). Lo usa espino_iss.py para
simular la unidad (DON_UNIT = 1) y sirvió para verificar la lógica de la
FSM antes del testbench en Verilog.
(La versión descartada con histogramas está en donchian_hw_hist.py.)
"""
LE, LX = 500, 250


class Unit:
    def __init__(s):
        s.ring = [0] * 512
        s.ring_rd = 0
        s.state = 0
        s.idx = 0; s.n = 0; s.a = 0; s.ci = 0; s.v = 0
        s.h = 0; s.l = 255

    def busy(s):
        return s.state != 0

    def clock(s, push=None):
        # memoria: lectura síncrona (valor anterior a la escritura del mismo flanco)
        nrd = s.ring[s.a]
        if push is not None and s.state == 0:
            s.ring[s.idx] = push & 255
        ns = {}
        if s.state == 0:
            if push is not None:
                ns.update(idx=(s.idx + 1) & 511, n=s.n if s.n == LE else s.n + 1,
                          a=s.idx, ci=0, v=0, h=0, l=255, state=1)
        else:
            pedir = s.ci != s.n
            if pedir:
                ns['a'] = (s.a - 1) & 511
                ns['ci'] = s.ci + 1
            ns['v'] = int(pedir)
            if s.v:
                if s.ring_rd > s.h: ns['h'] = s.ring_rd
                if s.ci <= LX and s.ring_rd < s.l: ns['l'] = s.ring_rd
            if not pedir and not s.v:
                ns['state'] = 0
        s.ring_rd = nrd
        for k, val in ns.items():
            setattr(s, k, val)
