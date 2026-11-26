# ============================================================
# trade.s - Pochoco Trader: PROGRAMA FINAL
# Canal de Donchian 500/250 con compra inicial y meta de patrimonio,
# usando la unidad de ventana deslizante en hardware
# (pochoco_donchian, 0x8004_0000).
# Proyecto 4 - Espino Core (RV32E). Requiere DON_UNIT = 1:
#   make sim MUL_MODE=0 DON_UNIT=1 PROG=trade
#
# Estrategia (en orden de prioridad):
#   1. Meta: si el patrimonio W = caja + acciones * p llega a META
#      (1,35 x caja inicial), vende todo y no vuelve a operar.
#   2. Primer precio: compra 63 (compra inicial).
#   3. Precios 2 a 500: mantener (la ventana todavia no esta llena).
#   4. Sin acciones: compra 63 si p > H (maximo de los 500 anteriores).
#   5. Con acciones: vende 63 si p < L (minimo de los 250 anteriores).
#
# Contabilidad propia, con las mismas reglas que la maestra (caja
# inicial CAJA0, comision 5, compra limitada por la caja, venta solo si
# caja + q*p >= 5). La orden decidida en un tick se ejecuta al precio
# del tick siguiente, asi que se contabiliza al llegar ese precio.
#   - Compra: q = min(63, (caja - 5) / p) por division binaria con una
#     tabla de multiplos p, 2p, ..., 32p en RAM (6 pasos, sin bucles).
#   - Venta y patrimonio: q * p con la subrutina mul8 (8 sumas).
# Si se cambia la caja inicial, hay que cambiar CAJA0 y META.
#
# La unidad mantiene H y L; el procesador lee H o L, decide, escribe
# DECISION y le entrega el precio. La unidad actualiza H y L mientras
# el procesador espera el siguiente precio (en paralelo).
#
# Versiones anteriores: trade_don_ini.s (sin meta), trade_don_hw.s (sin
# compra inicial), trade_don.s / trade_don_naive.s (solo software) y
# trade_reversion.s (estrategia anterior, reversion a la media).
#
# Registros: s0 SPI, s1 unidad Donchian, t2 displays, sp contador
# (satura en 500), a5 posicion segun la estrategia (1 = dentro),
# a3 precio, a0 caja, a1 acciones, a2 orden pendiente (0 nada,
# 1 compra, 2 venta), a4 meta alcanzada (1 = no operar mas),
# gp cantidad / producto / patrimonio, t0 t1 tp temporales,
# ra retorno de mul8.
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status, +4 precio, +8 DECISION
.equ PER_BASE, 0x80000000      # +0 displays
.equ DON_BASE, 0x80040000      # +0 escribir precio / estado, +4 H, +8 L
.equ LE,       500
.equ BUY63,    0x7F
.equ SELL63,   0xBF
.equ CAJA0,    10000           # caja inicial (enunciado)
.equ COMISION, 5
.equ META,     13500           # = 1,35 * CAJA0 (patrimonio a asegurar)
.equ TABLA,    0x7E0           # 6 palabras al final de la RAM: p, 2p, ..., 32p

_start:
    li   s0, SPI_BASE
    li   s1, DON_BASE
    li   t2, PER_BASE
    li   sp, 0
    li   a5, 0
    li   a0, CAJA0
    li   a1, 0
    li   a2, 0
    li   a4, 0

esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)             # p
    sw   a3, 0(t2)             # mostrar el precio

# ---- 1. contabilizar la orden del tick anterior (se ejecuta a este precio)
    beqz a2, contab_fin
    li   t0, 1
    bne  a2, t0, ejec_venta

    # compra: q = min(63, (caja - 5) / p)
    addi t1, a0, -COMISION     # presupuesto
    bltz t1, ejec_fin          # caja < 5: la maestra no ejecuta nada
    mv   t0, a3                # tabla de multiplos p, 2p, 4p, 8p, 16p, 32p
    sw   t0, TABLA(zero)
    add  t0, t0, t0
    sw   t0, TABLA+4(zero)
    add  t0, t0, t0
    sw   t0, TABLA+8(zero)
    add  t0, t0, t0
    sw   t0, TABLA+12(zero)
    add  t0, t0, t0
    sw   t0, TABLA+16(zero)
    add  t0, t0, t0
    sw   t0, TABLA+20(zero)
    add  t0, t0, t0            # t0 = 64p
    li   gp, 63
    blt  t1, t0, ec_div        # alcanza para menos de 64 acciones
    sub  t1, t1, t0            # alcanza para 64 o mas: q = 63
    add  t1, t1, a3            # presupuesto - 63p
    j    ec_fin
ec_div:                        # division binaria: q < 64
    li   gp, 0
    lw   t0, TABLA+20(zero)    # 32p
    blt  t1, t0, ec_16
    sub  t1, t1, t0
    addi gp, gp, 32
ec_16:
    lw   t0, TABLA+16(zero)    # 16p
    blt  t1, t0, ec_8
    sub  t1, t1, t0
    addi gp, gp, 16
ec_8:
    lw   t0, TABLA+12(zero)    # 8p
    blt  t1, t0, ec_4
    sub  t1, t1, t0
    addi gp, gp, 8
ec_4:
    lw   t0, TABLA+8(zero)     # 4p
    blt  t1, t0, ec_2
    sub  t1, t1, t0
    addi gp, gp, 4
ec_2:
    lw   t0, TABLA+4(zero)     # 2p
    blt  t1, t0, ec_1
    sub  t1, t1, t0
    addi gp, gp, 2
ec_1:
    lw   t0, TABLA(zero)       # p
    blt  t1, t0, ec_fin
    sub  t1, t1, t0
    addi gp, gp, 1
ec_fin:
    beqz gp, ejec_fin          # q = 0: la maestra no ejecuta nada
    mv   a0, t1                # caja = caja - 5 - q*p
    add  a1, a1, gp            # acciones += q
    j    ejec_fin

    # venta: q = min(63, acciones); solo si caja + q*p >= 5
ejec_venta:
    beqz a1, ejec_fin          # sin acciones: no se ejecuta nada
    mv   t0, a1
    li   t1, 63
    bgeu t1, t0, ev_q
    mv   t0, t1
ev_q:
    call mul8                  # gp = q * p (t0 no cambia)
    add  t1, a0, gp            # caja + q*p
    li   tp, COMISION
    blt  t1, tp, ejec_fin      # la maestra no ejecuta la venta
    addi a0, t1, -COMISION
    sub  a1, a1, t0
ejec_fin:
    li   a2, 0
contab_fin:

esp_unidad:
    lw   t0, 0(s1)             # 1 = la unidad sigue actualizando
    bnez t0, esp_unidad

# ---- 2. meta de patrimonio
    bnez a4, mantener          # meta ya alcanzada: no operar mas
    li   gp, 0
    beqz a1, sin_acc
    mv   t0, a1
    call mul8                  # gp = acciones * p
sin_acc:
    add  gp, gp, a0            # W = caja + acciones * p
    li   t0, META
    bltu gp, t0, estrategia    # W < meta: seguir con el canal
    li   a4, 1                 # meta alcanzada
    beqz a1, mantener          # sin acciones: solo dejar de operar
    j    vender

# ---- 3. canal de Donchian con compra inicial
estrategia:
    beqz sp, comprar           # primer precio: compra inicial
    li   t0, LE
    bltu sp, t0, mantener      # menos de 500 precios previos
    bnez a5, ver_venta
    lw   t0, 4(s1)             # H
    bgeu t0, a3, mantener      # p <= H: no hay ruptura
comprar:
    li   a5, 1
    li   t0, BUY63
    sw   t0, 8(s0)             # DECISION = comprar 63
    li   a2, 1
    j    entregar
ver_venta:
    lw   t0, 8(s1)             # L
    bgeu a3, t0, mantener      # p >= L
vender:
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)             # DECISION = vender 63
    li   a2, 2
    j    entregar
mantener:
    sw   zero, 8(s0)

entregar:
    sw   a3, 0(s1)             # la unidad actualiza H y L en paralelo
    li   t0, LE
    bgeu sp, t0, esperar       # contador de precios, satura en 500
    addi sp, sp, 1
    j    esperar

# ---- gp = t0 * a3, con t0 <= 255 (8 bits). Usa t1 y tp; t0 no cambia.
mul8:
    li   gp, 0
    mv   t1, a3
    andi tp, t0, 1
    beqz tp, m_b1
    add  gp, gp, t1
m_b1:
    add  t1, t1, t1
    andi tp, t0, 2
    beqz tp, m_b2
    add  gp, gp, t1
m_b2:
    add  t1, t1, t1
    andi tp, t0, 4
    beqz tp, m_b3
    add  gp, gp, t1
m_b3:
    add  t1, t1, t1
    andi tp, t0, 8
    beqz tp, m_b4
    add  gp, gp, t1
m_b4:
    add  t1, t1, t1
    andi tp, t0, 16
    beqz tp, m_b5
    add  gp, gp, t1
m_b5:
    add  t1, t1, t1
    andi tp, t0, 32
    beqz tp, m_b6
    add  gp, gp, t1
m_b6:
    add  t1, t1, t1
    andi tp, t0, 64
    beqz tp, m_b7
    add  gp, gp, t1
m_b7:
    add  t1, t1, t1
    andi tp, t0, 128
    beqz tp, m_fin
    add  gp, gp, t1
m_fin:
    ret
