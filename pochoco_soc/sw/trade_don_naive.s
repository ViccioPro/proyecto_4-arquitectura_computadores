# ============================================================
# trade_don_naive.s - Canal de Donchian 500/250, version INGENUA
# Proyecto 4 - Espino Core (RV32E)
#
# Misma estrategia y mismas decisiones que trade_don.s, pero calcula
# H y L recorriendo el buffer completo en cada tick:
#   sin acciones -> recorre 500 precios para H
#   con acciones -> recorre 250 precios para L
# Es la LINEA BASE del co-diseno: es simple y obviamente correcta,
# pero tarda ~7500 ciclos por tick, mas que el plazo de la ronda 3
# (2262 ciclos). Cumple las rondas 1 y 2.
#
# Registros: s0 SPI, t2 displays, tp indice (0..511), sp contador
# (satura en 500), a5 posicion, a3 precio, s1 = H o L calculado,
# a1 indice del recorrido, a2 contador del recorrido, t0 temporal.
# ============================================================

.equ SPI_BASE, 0x80010000
.equ PER_BASE, 0x80000000
.equ LE,       500
.equ LX,       250
.equ RMASK,    511
.equ OFF_LE,   12              # (tp - 500) mod 512
.equ OFF_LX,   262             # (tp - 250) mod 512
.equ BUY63,    0x7F
.equ SELL63,   0xBF

_start:
    li   s0, SPI_BASE
    li   t2, PER_BASE
    li   tp, 0
    li   sp, 0
    li   a5, 0

esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)
    sw   a3, 0(t2)

    li   t0, LE
    bltu sp, t0, mantener      # menos de 500 precios previos
    bnez a5, calc_L

# ---- H = maximo de los ultimos 500 precios ----
    li   s1, 0
    addi a1, tp, OFF_LE
    li   a2, LE
loop_H:
    andi a1, a1, RMASK
    lbu  t0, ring(a1)
    bgeu s1, t0, sig_H
    mv   s1, t0
sig_H:
    addi a1, a1, 1
    addi a2, a2, -1
    bnez a2, loop_H
    bgeu s1, a3, mantener      # p <= H
    li   a5, 1
    li   t0, BUY63
    sw   t0, 8(s0)
    j    guardar

# ---- L = minimo de los ultimos 250 precios ----
calc_L:
    li   s1, 256
    addi a1, tp, OFF_LX
    li   a2, LX
loop_L:
    andi a1, a1, RMASK
    lbu  t0, ring(a1)
    bgeu t0, s1, sig_L
    mv   s1, t0
sig_L:
    addi a1, a1, 1
    addi a2, a2, -1
    bnez a2, loop_L
    bgeu a3, s1, mantener      # p >= L
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)
    j    guardar

mantener:
    sw   zero, 8(s0)

guardar:
    sb   a3, ring(tp)
    addi tp, tp, 1
    andi tp, tp, RMASK
    li   t0, LE
    bgeu sp, t0, esperar
    addi sp, sp, 1
    j    esperar

ring:
    .space 512
