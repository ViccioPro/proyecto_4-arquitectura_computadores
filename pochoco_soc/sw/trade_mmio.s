# ============================================================
# trade_mmio.s - Pochoco Trader (variante periferico MMIO)
# Proyecto 4 - Espino Core (RV32E) + multiplicador MMIO en 0x8002_0000
# Requiere el hardware con MUL_MODE = 2.
# Mismo algoritmo y mismas decisiones que trade.s; solo cambian las
# tres multiplicaciones (periferico en vez de la subrutina mul).
#
# Estrategia: reversion a la media con banda de 2 sigma.
#   Ventana de N = 64 precios. S = suma, Q = suma de cuadrados.
#   d   = 64*p - S
#   var = 64*Q - S^2
#   - Sin acciones: compra 63 si d < 0 y d^2 > 4*var
#   - Con acciones: vende 63 si d > 0
#   - En otro caso (o con la ventana incompleta): mantener
# Debe dar exactamente las mismas decisiones que model/estrategia.py
#
# Ciclo principal: esperar precio -> actualizar ventana ->
#                  predecir (d, var) -> decidir -> escribir DECISION
#
# Uso de registros (no se usa pila; sp/gp/tp son registros comunes):
#   s0 = base del SPI (0x8001_0000)
#   s1 = S, suma de la ventana            (max 64*255 = 16320)
#   gp = Q, suma de cuadrados             (max 64*255^2 = 4161600)
#   tp = indice del buffer circular, en bytes (0, 4, ..., 252)
#   sp = precios recibidos, satura en 64
#   a5 = 1 si se tienen acciones, 0 si no
#   a3 = precio actual p,  a4 = d
#   t2 = base del multiplicador MMIO (fijo)
#   a0, a2 = |d| y productos;  t0, t1 = temporales
#
# Memoria: dos buffers de 64 palabras al final del programa
#   buf_p: ultimos 64 precios, buf_q: sus cuadrados.
#   Se inicializan en cero desde el .hex (.space).
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status (bit0 precio nuevo), +4 precio, +8 DECISION
.equ N,        64
.equ IDX_MASK, 255             # N*4 - 1 (indice circular en bytes)
.equ BUY63,    0x7F            # 01 111111 -> comprar 63
.equ SELL63,   0xBF            # 10 111111 -> vender 63
.equ MUL_BASE, 0x80020000      # multiplicador MMIO: +0 A / estado, +4 B, +8 producto

_start:
    li   s0, SPI_BASE
    li   s1, 0
    li   gp, 0
    li   tp, 0
    li   sp, 0
    li   a5, 0
    li   t2, MUL_BASE          # t2 queda fijo con la base del multiplicador

# ---------------- 1. Esperar precio ----------------
esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)             # p (leerlo borra el flag)

# ---------------- 2. Actualizar ventana ----------------
    sw   a3, 0(t2)            # A
    sw   a3, 4(t2)            # B (empieza)
esp_p2:
    lw   t1, 0(t2)             # estado: 1 = multiplicando
    bnez t1, esp_p2
    lw   a2, 8(t2)             # a2 = p^2
    lw   t0, buf_p(tp)         # precio que sale de la ventana
    lw   t1, buf_q(tp)         # su cuadrado
    sw   a3, buf_p(tp)
    sw   a2, buf_q(tp)
    add  s1, s1, a3            # S += p - p_viejo
    sub  s1, s1, t0
    add  gp, gp, a2            # Q += p^2 - p_viejo^2
    sub  gp, gp, t1
    addi tp, tp, 4
    andi tp, tp, IDX_MASK

    li   t0, N                 # ventana llena?
    bgeu sp, t0, llena
    addi sp, sp, 1
    bltu sp, t0, mantener

# ---------------- 3. Predecir: d = 64*p - S ----------------
llena:
    add  a4, a3, a3            # 2p   (64p con 6 duplicaciones)
    add  a4, a4, a4            # 4p
    add  a4, a4, a4            # 8p
    add  a4, a4, a4            # 16p
    add  a4, a4, a4            # 32p
    add  a4, a4, a4            # 64p
    sub  a4, a4, s1            # d

# ---------------- 4. Decidir ----------------
    beqz a5, ver_compra
    bgtz a4, vender            # con acciones: vender si p > media
    j    mantener

ver_compra:
    bgez a4, mantener          # comprar solo si p < media
    sw   s1, 0(t2)            # A
    sw   s1, 4(t2)            # B (empieza)
esp_s2:
    lw   t1, 0(t2)             # estado: 1 = multiplicando
    bnez t1, esp_s2
    lw   a2, 8(t2)             # a2 = S^2
    add  t0, gp, gp            # 2Q   (64Q con 6 duplicaciones)
    add  t0, t0, t0            # 4Q
    add  t0, t0, t0            # 8Q
    add  t0, t0, t0            # 16Q
    add  t0, t0, t0            # 32Q
    add  t0, t0, t0            # 64Q
    sub  t0, t0, a2            # var = 64Q - S^2
    add  t0, t0, t0            # 2 var
    add  t0, t0, t0            # 4 var
    neg  a0, a4                # |d| (aqui d < 0)
    sw   a0, 0(t2)            # A
    sw   a0, 4(t2)            # B (empieza)
esp_d2:
    lw   t1, 0(t2)             # estado: 1 = multiplicando
    bnez t1, esp_d2
    lw   a2, 8(t2)             # a2 = d^2
    bgeu t0, a2, mantener      # d^2 <= 4 var -> mantener

# ---------------- 5. Escribir DECISION ----------------
comprar:
    li   a5, 1
    li   t0, BUY63
    sw   t0, 8(s0)
    j    esperar

vender:
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)
    j    esperar

mantener:
    sw   zero, 8(s0)
    j    esperar

# ---------------- Datos ----------------
buf_p:
    .space 256                 # 64 precios
buf_q:
    .space 256                 # 64 cuadrados
