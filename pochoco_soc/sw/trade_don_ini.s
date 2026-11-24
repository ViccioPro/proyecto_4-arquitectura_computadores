# ============================================================
# trade_don_ini.s - Canal de Donchian 500/250 con COMPRA INICIAL,
# usando la unidad de ventana deslizante en hardware
# (pochoco_donchian, 0x8004_0000).
# Proyecto 4 - Espino Core (RV32E). Requiere DON_UNIT = 1.
#
# "Time in the market": compra 63 con el primer precio recibido y
# despues sigue el canal de Donchian:
#   Primer precio: compra 63 (queda con acciones)
#   Precios 2 a 500: mantener (la ventana todavia no esta llena)
#   Sin acciones: compra 63 si p > H (maximo de los 500 anteriores)
#   Con acciones: vende 63 si p < L (minimo de los 250 anteriores)
# Unica diferencia con trade_don_hw.s: la instruccion "beqz sp, comprar".
# La unidad mantiene H y L; el procesador lee H o L, decide, escribe
# DECISION y le entrega el precio. La unidad actualiza H y L mientras
# el procesador espera el siguiente precio (en paralelo).
#
# Registros: s0 SPI, s1 unidad Donchian, t2 displays, sp contador
# (satura en 500), a5 posicion (1 = con acciones), a3 precio,
# t0 temporal.
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status, +4 precio, +8 DECISION
.equ PER_BASE, 0x80000000      # +0 displays
.equ DON_BASE, 0x80040000      # +0 escribir precio / estado, +4 H, +8 L
.equ LE,       500
.equ BUY63,    0x7F
.equ SELL63,   0xBF

_start:
    li   s0, SPI_BASE
    li   s1, DON_BASE
    li   t2, PER_BASE
    li   sp, 0
    li   a5, 0

esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)             # p
    sw   a3, 0(t2)             # mostrar el precio
esp_unidad:
    lw   t0, 0(s1)             # 1 = la unidad sigue actualizando
    bnez t0, esp_unidad

    beqz sp, comprar           # primer precio: comprar de inmediato
    li   t0, LE
    bltu sp, t0, mantener      # menos de 500 precios previos
    bnez a5, ver_venta
    lw   t0, 4(s1)             # H
    bgeu t0, a3, mantener      # p <= H
comprar:
    li   a5, 1
    li   t0, BUY63
    sw   t0, 8(s0)
    j    entregar
ver_venta:
    lw   t0, 8(s1)             # L
    bgeu a3, t0, mantener      # p >= L
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)
    j    entregar
mantener:
    sw   zero, 8(s0)

entregar:
    sw   a3, 0(s1)             # la unidad actualiza H y L en paralelo
    li   t0, LE
    bgeu sp, t0, esperar
    addi sp, sp, 1
    j    esperar
