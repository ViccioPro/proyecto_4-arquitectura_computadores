# ============================================================
# trade_don_meta.s - Canal de Donchian 500/250 con COMPRA INICIAL y
# META DE PATRIMONIO ("asegurar la ganancia"), usando la unidad de
# ventana deslizante en hardware (pochoco_donchian, 0x8004_0000).
# Proyecto 4 - Espino Core (RV32E). Requiere DON_UNIT = 1.
#
# Igual que trade_don_ini.s, mas una contabilidad propia:
#   - El programa lleva su caja y sus acciones con las mismas reglas
#     que la maestra (caja inicial 10000, comision 5, compra limitada
#     por la caja). La orden decidida en un tick se ejecuta al precio
#     del tick siguiente, asi que se contabiliza al llegar ese precio.
#   - Patrimonio W = caja + acciones * p (p = precio actual).
#   - Si W >= META: vende todo (si tiene acciones) y no vuelve a operar
#     en el resto de la serie (queda "asegurado").
# No usa hardware nuevo: acciones (<= 63) * p se calcula con 6 sumas
# (subrutina mul63) y la compra cuenta cuantas acciones alcanza la caja
# restando p (como maximo 63 veces, solo en el tick en que se ejecuta).
#
# Para cambiar la meta: modificar META aqui y usar el mismo valor en
# la variable de entorno META del modelo (env META=... make ...).
#
# Registros: s0 SPI, s1 unidad Donchian, t2 displays, sp contador
# (satura en 500), a5 posicion segun la estrategia (1 = dentro),
# a3 precio, a0 caja, a1 acciones, a2 orden pendiente (0 nada,
# 1 compra, 2 venta), a4 asegurado (1 = no operar mas),
# gp producto / patrimonio, t0 t1 tp temporales, ra retorno.
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status, +4 precio, +8 DECISION
.equ PER_BASE, 0x80000000      # +0 displays
.equ DON_BASE, 0x80040000      # +0 escribir precio / estado, +4 H, +8 L
.equ LE,       500
.equ BUY63,    0x7F
.equ SELL63,   0xBF
.equ CAJA0,    10000
.equ COMISION, 5
.equ META,     13500           # patrimonio a asegurar

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
    addi t1, a0, -COMISION     # presupuesto (puede ser negativo)
    li   t0, 0                 # q
ec_loop:
    li   tp, 63
    beq  t0, tp, ec_fin
    blt  t1, a3, ec_fin        # ya no alcanza para otra accion
    sub  t1, t1, a3
    addi t0, t0, 1
    j    ec_loop
ec_fin:
    beqz t0, ejec_fin          # q = 0: la maestra no ejecuta nada
    mv   a0, t1                # caja = caja - 5 - q*p
    add  a1, a1, t0
    j    ejec_fin
ejec_venta:
    beqz a1, ejec_fin          # sin acciones: no se ejecuta nada
    call mul63                 # gp = acciones * p
    add  a0, a0, gp
    addi a0, a0, -COMISION
    li   a1, 0
ejec_fin:
    li   a2, 0
contab_fin:

esp_unidad:
    lw   t0, 0(s1)             # 1 = la unidad sigue actualizando
    bnez t0, esp_unidad

# ---- 2. meta de patrimonio
    bnez a4, mantener          # ya asegurado: no operar mas
    li   gp, 0
    beqz a1, sin_acc
    call mul63                 # gp = acciones * p
sin_acc:
    add  gp, gp, a0            # W = caja + acciones * p
    li   t0, META
    bltu gp, t0, estrategia
    li   a4, 1                 # meta alcanzada
    beqz a1, mantener          # sin acciones: solo dejar de operar
    j    vender

# ---- 3. canal de Donchian con compra inicial (igual que trade_don_ini.s)
estrategia:
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
    li   a2, 1
    j    entregar
ver_venta:
    lw   t0, 8(s1)             # L
    bgeu a3, t0, mantener      # p >= L
vender:
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)
    li   a2, 2
    j    entregar
mantener:
    sw   zero, 8(s0)

entregar:
    sw   a3, 0(s1)             # la unidad actualiza H y L en paralelo
    li   t0, LE
    bgeu sp, t0, esperar
    addi sp, sp, 1
    j    esperar

# ---- gp = a1 * a3, con a1 <= 63 (6 bits). Usa t1 y tp.
mul63:
    li   gp, 0
    mv   t1, a3
    andi tp, a1, 1
    beqz tp, m_b1
    add  gp, gp, t1
m_b1:
    add  t1, t1, t1
    andi tp, a1, 2
    beqz tp, m_b2
    add  gp, gp, t1
m_b2:
    add  t1, t1, t1
    andi tp, a1, 4
    beqz tp, m_b3
    add  gp, gp, t1
m_b3:
    add  t1, t1, t1
    andi tp, a1, 8
    beqz tp, m_b4
    add  gp, gp, t1
m_b4:
    add  t1, t1, t1
    andi tp, a1, 16
    beqz tp, m_b5
    add  gp, gp, t1
m_b5:
    add  t1, t1, t1
    andi tp, a1, 32
    beqz tp, m_fin
    add  gp, gp, t1
m_fin:
    ret
