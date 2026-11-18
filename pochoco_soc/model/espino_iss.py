#!/usr/bin/env python3
"""
Simulador de instrucciones del Espino Core (RV32E) con modelo de ciclos.

Modelo de ciclos (obtenido del RTL de espino_core):
  - Toda instrucción: 2 ciclos (lectura síncrona del banco de registros en BRAM)
  - Load: +1 ciclo (espera del dato)
  - Branch tomado, jal, jalr: +1 ciclo (se descarta la instrucción ya buscada)
  - Shifts: se ejecutan como ADD (igual que la ALU original)

MMIO simulado:
  0x8001_0000 status {cs, precio_nuevo}   0x8001_0004 precio (lee y borra flag)
  0x8001_0008 DECISION (escritura)        0x8000_0000/04 displays/LEDs
  0x8000_0008 botones (0)                 0x8000_000C contador de ciclos
  0x8002_0000 multiplicador MMIO (MUL_MODE = 2): +0 A / estado, +4 B, +8 producto

Instrucción custom-0 "mulc" (MUL_MODE = 1): rd = rs1*rs2 mod 2^32.
  Ciclos: m + 3, con m = max(1, ceil(bits(rs2) / radix)).

Uso:
  python3 espino_iss.py ../sw/trade.hex practica.csv [--ticks 2000] [--csv salida.csv] [--radix 1]
Entrega, por tick: decisión, instrucciones (IC), ciclos y CPI desde que llega
el precio hasta que se escribe DECISION.
"""
import argparse
import csv
import sys

SPI_BASE = 0x80010000
PER_BASE = 0x80000000
RAM_WORDS = 512


def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Espino:
    def __init__(self, hex_path, radix=1):
        self.radix = radix
        self.mul_a = 0
        self.mul_p = 0
        self.mul_inicio = -1      # ciclo en que el multiplicador MMIO empieza
        self.mul_m = 0
        self.mem = [0] * RAM_WORDS
        with open(hex_path) as f:
            for i, line in enumerate(l for l in f if l.strip()):
                self.mem[i] = int(line, 16)
        self.r = [0] * 16
        self.pc = 0
        self.cycle = 0
        self.instret = 0
        # SPI
        self.price = 0
        self.new_price = 0
        self.pending = None          # (ciclo de llegada, precio)
        self.decision_writes = []    # (ciclo, valor, instret)
        self.display = 0

    def mul_ciclos(self, b):
        """Iteraciones del multiplicador secuencial (terminación temprana)."""
        bits = (b & 0xFFFF).bit_length()
        return max(1, -(-bits // self.radix))

    # ---------------- memoria ----------------
    def _arrive(self):
        if self.pending and self.cycle >= self.pending[0]:
            self.price = self.pending[1]
            self.new_price = 1
            self.pending = None

    def load_word(self, addr):
        self._arrive()
        if addr & 0x80000000 and addr & 0x20000:          # multiplicador MMIO
            off = addr & 0xFF
            if off == 0x00:
                t = self.cycle + 1                         # ciclo en que se muestrea
                return int(self.mul_inicio <= t < self.mul_inicio + self.mul_m)
            if off == 0x08:
                return self.mul_p
            return 0
        if addr & 0x80000000:
            if addr & 0x10000:
                off = addr & 0xFF
                if off == 0x00:
                    return self.new_price
                if off == 0x04:
                    self.new_price = 0
                    return self.price
                return 0
            off = addr & 0xFF
            if off == 0x08:
                return 0
            if off == 0x0C:
                return self.cycle & 0xFFFFFFFF
            return 0
        return self.mem[(addr >> 2) % RAM_WORDS]

    def store(self, addr, val, be_mask):
        if addr & 0x80000000 and addr & 0x20000:          # multiplicador MMIO
            off = addr & 0xFF
            if off == 0x00:
                self.mul_a = val
            elif off == 0x04:
                self.mul_p = (self.mul_a * (val & 0xFFFF)) & 0xFFFFFFFF
                self.mul_inicio = self.cycle + 2
                self.mul_m = self.mul_ciclos(val)
            return
        if addr & 0x80000000:
            if addr & 0x10000:
                if (addr & 0xFF) == 0x08:
                    self.decision_writes.append((self.cycle, val & 0xFF, self.instret))
            elif (addr & 0xFF) == 0x00:
                self.display = val & 0xFF
            return
        w = (addr >> 2) % RAM_WORDS
        old = self.mem[w]
        self.mem[w] = (old & ~be_mask | (val & be_mask)) & 0xFFFFFFFF

    # ---------------- ejecución ----------------
    def step(self):
        ins = self.mem[(self.pc >> 2) % RAM_WORDS]
        op = ins & 0x7F
        rd = (ins >> 7) & 0x1F
        f3 = (ins >> 12) & 7
        rs1 = (ins >> 15) & 0x1F
        rs2 = (ins >> 20) & 0x1F
        f7 = ins >> 25
        a = self.r[rs1 & 15]
        b = self.r[rs2 & 15]
        i_imm = sx(ins >> 20, 12)
        s_imm = sx(((ins >> 25) << 5) | ((ins >> 7) & 0x1F), 12)
        b_imm = sx((((ins >> 31) & 1) << 12) | (((ins >> 7) & 1) << 11) |
                   (((ins >> 25) & 0x3F) << 5) | (((ins >> 8) & 0xF) << 1), 13)
        j_imm = sx((((ins >> 31) & 1) << 20) | (((ins >> 12) & 0xFF) << 12) |
                   (((ins >> 20) & 1) << 11) | (((ins >> 21) & 0x3FF) << 1), 21)
        cycles = 2
        next_pc = self.pc + 4
        res = None

        def alu(fn, x, y, sub):
            xs, ys = sx(x, 32), sx(y, 32)
            if fn == 0:
                return (x - y) if sub else (x + y)
            if fn in (1, 5):                 # shifts deshabilitados -> ADD
                return x + y
            if fn == 2:
                return int(xs < ys)
            if fn == 3:
                return int(x < y)
            if fn == 4:
                return x ^ y
            if fn == 6:
                return x | y
            return x & y

        if op == 0x37:                       # LUI
            res = ins & 0xFFFFF000
        elif op == 0x17:                     # AUIPC
            res = self.pc + (ins & 0xFFFFF000)
        elif op == 0x13:                     # OP-IMM
            res = alu(f3, a, i_imm & 0xFFFFFFFF, False)
        elif op == 0x33:                     # OP
            res = alu(f3, a, b, f7 == 0x20)
        elif op == 0x03:                     # LOAD
            addr = (a + i_imm) & 0xFFFFFFFF
            word = self.load_word(addr & ~3)
            sh = (addr & 3) * 8
            if f3 == 0:
                res = sx(word >> sh, 8)
            elif f3 == 1:
                res = sx(word >> (sh & 16), 16)
            elif f3 == 2:
                res = word
            elif f3 == 4:
                res = (word >> sh) & 0xFF
            elif f3 == 5:
                res = (word >> (sh & 16)) & 0xFFFF
            cycles += 1
        elif op == 0x23:                     # STORE
            addr = (a + s_imm) & 0xFFFFFFFF
            if f3 == 0:
                sh = (addr & 3) * 8
                self.store(addr & ~3, (b & 0xFF) << sh, 0xFF << sh)
            elif f3 == 1:
                sh = (addr & 2) * 8
                self.store(addr & ~3, (b & 0xFFFF) << sh, 0xFFFF << sh)
            else:
                self.store(addr & ~3, b, 0xFFFFFFFF)
        elif op == 0x63:                     # BRANCH
            xs, ys = sx(a, 32), sx(b, 32)
            taken = {0: a == b, 1: a != b, 4: xs < ys, 5: xs >= ys,
                     6: a < b, 7: a >= b}[f3]
            if taken:
                next_pc = self.pc + b_imm
                cycles += 1
        elif op == 0x6F:                     # JAL
            res = self.pc + 4
            next_pc = self.pc + j_imm
            cycles += 1
        elif op == 0x0B and f3 == 0 and f7 == 0:   # custom-0: mulc
            res = (a * (b & 0xFFFF)) & 0xFFFFFFFF
            cycles += self.mul_ciclos(b) + 1
        elif op == 0x67:                     # JALR
            res = self.pc + 4
            next_pc = (a + i_imm) & ~1
            cycles += 1
        else:
            raise RuntimeError(f"instruccion no soportada 0x{ins:08x} en pc=0x{self.pc:x}")

        if res is not None and rd != 0:
            self.r[rd & 15] = res & 0xFFFFFFFF
        self.pc = next_pc & 0xFFFFFFFF
        self.cycle += cycles
        self.instret += 1


def correr(hex_path, precios, max_ciclos_por_tick=200000, radix=1):
    """Entrega una lista de (decision, IC, ciclos) por precio."""
    cpu = Espino(hex_path, radix)
    # dejar que el programa inicialice y llegue al bucle de espera
    for _ in range(1000):
        cpu.step()
    out = []
    for p in precios:
        cpu.pending = (cpu.cycle, p)
        t0, i0 = cpu.cycle, cpu.instret
        n_w = len(cpu.decision_writes)
        while len(cpu.decision_writes) == n_w:
            cpu.step()
            if cpu.cycle - t0 > max_ciclos_por_tick:
                raise RuntimeError("el programa no escribio DECISION")
        c, val, ir = cpu.decision_writes[-1]
        out.append((val, ir + 1 - i0, c + 2 - t0))
        # volver al bucle de espera (hasta que lea el status con flag en 0)
        for _ in range(50):
            cpu.step()
    return out


def main():
    sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
    from estrategia import leer_serie
    ap = argparse.ArgumentParser()
    ap.add_argument("hex")
    ap.add_argument("serie")
    ap.add_argument("--ticks", type=int, default=None)
    ap.add_argument("--csv", help="guarda decision/IC/ciclos por tick")
    ap.add_argument("--radix", type=int, default=1,
                    help="bits por ciclo del multiplicador (MUL_RADIX)")
    a = ap.parse_args()
    precios = leer_serie(a.serie)[:a.ticks]
    res = correr(a.hex, precios, radix=a.radix)
    if a.csv:
        with open(a.csv, "w") as f:
            f.write("tick,precio,decision,ic,ciclos\n")
            for n, (p, (d, ic, c)) in enumerate(zip(precios, res)):
                f.write(f"{n},{p},{d:02x},{ic},{c}\n")
    ics = [r[1] for r in res]
    cs = [r[2] for r in res]
    print(f"ticks: {len(res)}")
    print(f"IC     promedio {sum(ics)/len(ics):7.1f}   peor {max(ics)}")
    print(f"ciclos promedio {sum(cs)/len(cs):7.1f}   peor {max(cs)}")
    print(f"CPI    promedio {sum(cs)/sum(ics):7.3f}")


if __name__ == "__main__":
    main()
