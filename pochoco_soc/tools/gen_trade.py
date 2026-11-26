#!/usr/bin/env python3
"""
Genera sw/trade_reversion.s, sw/trade_mulc.s y sw/trade_mmio.s desde una sola plantilla.
Las tres variantes tienen exactamente la misma lógica; solo cambia cómo se
calcula un cuadrado (SQ):
  - trade_reversion.s : subrutina mul por software (sumas sucesivas, sin shifts)
  - trade_mulc.s : instrucción custom-0 mulc            (MUL_MODE = 1)
  - trade_mmio.s : periférico MMIO en 0x8002_0000      (MUL_MODE = 2)
Uso (desde pochoco_soc/):  python3 tools/gen_trade.py
"""
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
SW = os.path.join(AQUI, "..", "sw")

PLANTILLA = r'''# ============================================================
# {archivo} - Pochoco Trader ({titulo})
# Proyecto 4 - Espino Core (RV32E){extra_hw}
# GENERADO por tools/gen_trade.py: editar la plantilla, no este archivo.
#
# Estrategia: reversion a la media con bandas de desviacion estandar,
# stop-loss y bloqueo de recompra (pensada para mercados volatiles).
#   Ventana de N = 256 precios. S = suma, Q = suma de cuadrados.
#   d   = 256*p - S
#   var = 256*Q - S^2
#   Estado (a5): 0 = FUERA, 1 = DENTRO, 2 = BLOQUEADO
#   - FUERA:     compra 63 si d < 0 y d^2 > 2*var   (p < media - 1,41 sigma)
#   - DENTRO:    vende 63 si d > 0 y d^2 > var      (p > media + 1 sigma)
#                vende 63 si d < 0 y d^2 > 16*var   (stop-loss, -4 sigma)
#                  y pasa a BLOQUEADO
#   - BLOQUEADO: pasa a FUERA cuando d > 0
#   Con la ventana incompleta (primeros 255 precios): mantener.
# Debe dar exactamente las mismas decisiones que model/estrategia.py
#
# Ciclo principal: esperar precio -> actualizar ventana ->
#                  predecir (d, var) -> decidir -> escribir DECISION
#
# Uso de registros (no se usa pila; sp/gp/tp son registros comunes):
#   s0 = base del SPI (0x8001_0000)
#   s1 = S, suma de la ventana              (max 256*255 = 65280)
#   gp = Q, suma de cuadrados               (max 256*255^2 = 16646400)
#   tp = indice del buffer circular (0..255, un byte por precio)
#   sp = precios recibidos, satura en 256
#   a5 = estado (0 FUERA, 1 DENTRO, 2 BLOQUEADO)
#   a3 = precio actual p,  a4 = d,  a1 = |d|,  a2 = cuadrados
#   t0 = precio que sale / var;  t1 = temporal
{regs_extra}#
# Aritmetica de 32 bits sin signo: S^2 y 256*Q <= 4,26e9 caben en 32 bits.
# 16*var no cabe si var >= 2^28; en ese caso 16*var ya supera a cualquier
# d^2 posible, asi que el stop-loss no se evalua (condicion falsa).
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status (bit0 precio nuevo), +4 precio, +8 DECISION
.equ N,        256             # tamano de la ventana
.equ IDX_MASK, 255             # N - 1 (indice circular en bytes)
.equ BUY63,    0x7F            # 01 111111 -> comprar 63
.equ SELL63,   0xBF            # 10 111111 -> vender 63
.equ VAR_MAX,  0x10000000      # 2^28: limite para calcular 16*var
{equ_extra}
_start:
    li   s0, SPI_BASE
    li   s1, 0
    li   gp, 0
    li   tp, 0
    li   sp, 0
    li   a5, 0
{init_extra}
# ---------------- 1. Esperar precio ----------------
esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)             # p (leerlo borra el flag)
{display}
# ---------------- 2. Actualizar ventana ----------------
    lbu  t0, buf_p(tp)         # precio que sale de la ventana
    sb   a3, buf_p(tp)
    add  s1, s1, a3            # S += p - p_viejo
    sub  s1, s1, t0
{SQ:a3:p2}    add  gp, gp, a2            # Q += p^2
{SQ:t0:viejo2}    sub  gp, gp, a2            # Q -= p_viejo^2
    addi tp, tp, 1
    andi tp, tp, IDX_MASK

    li   t0, N                 # ventana llena?
    bgeu sp, t0, llena
    addi sp, sp, 1
    bltu sp, t0, mantener

# ---------------- 3. Predecir: d = 256*p - S ----------------
llena:
    add  a4, a3, a3            # 2p   (256p con 8 duplicaciones)
    add  a4, a4, a4            # 4p
    add  a4, a4, a4            # 8p
    add  a4, a4, a4            # 16p
    add  a4, a4, a4            # 32p
    add  a4, a4, a4            # 64p
    add  a4, a4, a4            # 128p
    add  a4, a4, a4            # 256p
    sub  a4, a4, s1            # d

# ---------------- 4. Decidir ----------------
    li   t1, 2
    bne  a5, t1, no_bloq
    blez a4, mantener          # BLOQUEADO y p <= media: sigue bloqueado
    li   a5, 0                 # p cruzo sobre la media: vuelve a FUERA
    j    mantener
no_bloq:
    beqz a4, mantener          # p = media: nada que hacer
    beqz a5, fuera

# ---- DENTRO ----
{VAR_D2:dentro}    bltz a4, ver_stop
    bgeu t0, a2, mantener      # d > 0: vender si d^2 > var
    li   a5, 0
    j    vender
ver_stop:
    li   t1, VAR_MAX
    bgeu t0, t1, mantener      # var >= 2^28: 16*var > d^2 maximo
    add  t0, t0, t0            # 2 var
    add  t0, t0, t0            # 4 var
    add  t0, t0, t0            # 8 var
    add  t0, t0, t0            # 16 var
    bgeu t0, a2, mantener      # d^2 <= 16 var: no hay stop-loss
    li   a5, 2                 # stop-loss: vender y bloquear
    j    vender

# ---- FUERA ----
fuera:
    bgez a4, mantener          # comprar solo si p < media
{VAR_D2:fuera}    add  t0, t0, t0            # 2 var
    bgeu t0, a2, mantener      # d^2 <= 2 var -> mantener
    li   a5, 1

# ---------------- 5. Escribir DECISION ----------------
comprar:
    li   t0, BUY63
    sw   t0, 8(s0)
    j    esperar

vender:
    li   t0, SELL63
    sw   t0, 8(s0)
    j    esperar

mantener:
    sw   zero, 8(s0)
    j    esperar
{subrutina}
# ---------------- Datos ----------------
buf_p:
    .space 256                 # ultimos 256 precios (un byte cada uno)
'''

VAR_D2 = '''    # var = 256*Q - S^2  (en t0),  d^2 (en a2)
{SQ:s1:S2_{t}}    add  t0, gp, gp            # 2Q   (256Q con 8 duplicaciones)
    add  t0, t0, t0            # 4Q
    add  t0, t0, t0            # 8Q
    add  t0, t0, t0            # 16Q
    add  t0, t0, t0            # 32Q
    add  t0, t0, t0            # 64Q
    add  t0, t0, t0            # 128Q
    add  t0, t0, t0            # 256Q
    sub  t0, t0, a2            # var
    bgez a4, {t}_dpos
    neg  a1, a4                # |d|
    j    {t}_dabs
{t}_dpos:
    mv   a1, a4
{t}_dabs:
{SQ:a1:d2_{t}}'''

SUB_SW = '''
# ------------------------------------------------------------
# mul: a2 = a0 * a1 (sin signo, resultado < 2^32, a1 < 2^16)
#   Multiplicacion por sumas sucesivas, sin shifts: recorre los bits
#   de a1 con una mascara que se duplica y duplica a0 en cada paso.
#   Termina cuando la mascara supera a a1.
#   Modifica: a0, a2, t1, t2.  No modifica: a1, t0.
# ------------------------------------------------------------
mul:
    li   a2, 0
    li   t2, 1                 # mascara
mul_bit:
    and  t1, a1, t2
    beqz t1, mul_sig
    add  a2, a2, a0
mul_sig:
    add  a0, a0, a0
    add  t2, t2, t2
    bgeu a1, t2, mul_bit       # sigue mientras mascara <= a1
    ret
'''


def sq(variante, reg, etiqueta):
    if variante == "sw":
        mv1 = f"    mv   a1, {reg}\n" if reg != "a1" else ""
        return (f"    mv   a0, {reg}\n{mv1}"
                f"    call mul                   # a2 = {reg}^2\n")
    if variante == "mulc":
        return f"    mulc a2, {reg}, {reg}            # a2 = {reg}^2\n"
    return (f"    sw   {reg}, 0(t2)            # A\n"
            f"    sw   {reg}, 4(t2)            # B (empieza)\n"
            f"esp_{etiqueta}:\n"
            f"    lw   t1, 0(t2)             # estado: 1 = multiplicando\n"
            f"    bnez t1, esp_{etiqueta}\n"
            f"    lw   a2, 8(t2)             # a2 = {reg}^2\n")


def expandir(texto, variante):
    out = []
    for linea in texto.split("\n"):
        if "{VAR_D2:" in linea:
            t = linea.split("{VAR_D2:")[1].split("}")[0]
            resto = linea.split("}", 1)[1]
            bloque = VAR_D2.replace("{t}", t)
            out.append(expandir(bloque, variante) + ("\n" + resto if resto.strip() else ""))
        elif "{SQ:" in linea:
            reg, etq = linea.split("{SQ:")[1].split("}")[0].split(":")
            resto = linea.split("}", 1)[1]
            out.append(sq(variante, reg, etq).rstrip("\n") + ("\n" + resto if resto.strip() else ""))
        else:
            out.append(linea)
    return "\n".join(out)


VARIANTES = {
    "sw": dict(archivo="trade_reversion.s", titulo="version solo software", extra_hw=", sin mul/div/shifts",
               regs_extra="#   a0, t2 = usados por la subrutina mul;  ra = direccion de retorno\n",
               equ_extra="", init_extra="", display="", subrutina=SUB_SW),
    "mulc": dict(archivo="trade_mulc.s", titulo="variante instruccion custom-0",
                 extra_hw=" + instruccion mulc (custom-0)\n# Requiere el hardware con MUL_MODE = 1.",
                 regs_extra="#   t2 = base de los displays (fijo)\n",
                 equ_extra=".equ PER_BASE, 0x80000000      # +0 displays (precio en hexadecimal)\n",
                 init_extra="    li   t2, PER_BASE          # t2 queda fijo con la base de los displays\n",
                 display="    sw   a3, 0(t2)             # mostrar el precio en los displays (depuracion en placa)\n",
                 subrutina=""),
    "mmio": dict(archivo="trade_mmio.s", titulo="variante periferico MMIO",
                 extra_hw=" + multiplicador MMIO en 0x8002_0000\n# Requiere el hardware con MUL_MODE = 2.",
                 regs_extra="#   t2 = base del multiplicador MMIO (fijo)\n",
                 equ_extra=".equ MUL_BASE, 0x80020000      # multiplicador MMIO: +0 A / estado, +4 B, +8 producto\n",
                 init_extra="    li   t2, MUL_BASE          # t2 queda fijo con la base del multiplicador\n",
                 display="", subrutina=""),
}


def main():
    for var, campos in VARIANTES.items():
        texto = PLANTILLA
        for k, v in campos.items():
            texto = texto.replace("{" + k + "}", v)
        texto = expandir(texto, var)
        with open(os.path.join(SW, campos["archivo"]), "w") as f:
            f.write(texto)
        print("generado sw/" + campos["archivo"])


if __name__ == "__main__":
    main()
