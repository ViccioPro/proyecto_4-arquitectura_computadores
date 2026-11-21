# ============================================================
# trade_don.s - Pochoco Trader: canal de Donchian 500/250
# Proyecto 4 - Espino Core (RV32E). No usa multiplicaciones:
# funciona con cualquier MUL_MODE.
#
# Estrategia (seguimiento de tendencia por ruptura de canal):
#   H = maximo de los ultimos 500 precios (sin contar el actual)
#   L = minimo de los ultimos 250 precios (sin contar el actual)
#   - Sin acciones: compra 63 si p > H
#   - Con acciones: vende 63 si p < L
#   - En otro caso, y durante los primeros 500 precios: mantener
# Debe dar exactamente las mismas decisiones que model/estrategia.py
#
# Metodo: histogramas de precios en la ventana.
#   cnt_max[v] = cuantas veces aparece v en los ultimos 500 precios
#   cnt_min[v] = cuantas veces aparece v en los ultimos 250 precios
#   H y L se actualizan incrementalmente; solo cuando sale de la
#   ventana el ultimo precio igual a H (o a L) se busca el siguiente
#   valor presente recorriendo el histograma. Como el precio cambia
#   poco de un tick a otro, la busqueda es corta (peor caso en las
#   series de practica: 55 pasos).
#
# Ciclo principal: esperar precio -> decidir con H y L ->
#                  escribir DECISION -> actualizar histogramas
# (la decision se escribe ANTES de actualizar, para minimizar la
#  latencia precio -> decision)
#
# Uso de registros (no se usa pila; sp/gp/tp son registros comunes):
#   s0 = base del SPI (0x8001_0000)    t2 = base de los displays
#   s1 = H (maximo de la ventana de 500)
#   gp = L (minimo de la ventana de 250)
#   tp = indice del buffer circular de precios (0..511)
#   sp = precios recibidos, satura en 500
#   a5 = 1 si se tienen acciones, 0 si no
#   a3 = precio actual p
#   t0, a0, a1 = temporales
#
# Memoria (despues del codigo):
#   ring:    512 bytes, ultimos precios (buffer circular)
#   cnt_max: 256 medias palabras (cuentas hasta 500)
#   cnt_min: 256 bytes (cuentas hasta 250)
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status (bit0 precio nuevo), +4 precio, +8 DECISION
.equ PER_BASE, 0x80000000      # +0 displays (precio en hexadecimal)
.equ LE,       500             # ventana del maximo (entrada)
.equ LX,       250             # ventana del minimo (salida)
.equ RMASK,    511             # buffer circular de 512 precios
.equ OFF_LE,   12              # (tp - 500) mod 512 = (tp + 12) mod 512
.equ OFF_LX,   262             # (tp - 250) mod 512 = (tp + 262) mod 512
.equ BUY63,    0x7F            # 01 111111 -> comprar 63
.equ SELL63,   0xBF            # 10 111111 -> vender 63

_start:
    li   s0, SPI_BASE
    li   t2, PER_BASE
    li   s1, 0                 # H: cualquier precio lo supera
    li   gp, 256               # L: mayor que cualquier precio
    li   tp, 0
    li   sp, 0
    li   a5, 0

# ---------------- 1. Esperar precio ----------------
esperar:
    lw   t0, 0(s0)
    andi t0, t0, 1
    beqz t0, esperar
    lw   a3, 4(s0)             # p (leerlo borra el flag)
    sw   a3, 0(t2)             # mostrar el precio en los displays

# ---------------- 2. Decidir con H y L ----------------
    li   t0, LE
    bltu sp, t0, mantener      # menos de 500 precios previos
    bnez a5, ver_venta
    bgeu s1, a3, mantener      # p <= H: no hay ruptura al alza
    li   a5, 1
    li   t0, BUY63
    sw   t0, 8(s0)
    j    actualizar
ver_venta:
    bgeu a3, gp, mantener      # p >= L: no hay ruptura a la baja
    li   a5, 0
    li   t0, SELL63
    sw   t0, 8(s0)
    j    actualizar
mantener:
    sw   zero, 8(s0)

# ---------------- 3. Actualizar ventanas ----------------
actualizar:
    # agregar p a la ventana del maximo
    add  a0, a3, a3            # 2p: indice en medias palabras
    lhu  t0, cnt_max(a0)
    addi t0, t0, 1
    sh   t0, cnt_max(a0)
    bgeu s1, a3, max_ok
    mv   s1, a3                # nuevo maximo
max_ok:
    # agregar p a la ventana del minimo
    lbu  t0, cnt_min(a3)
    addi t0, t0, 1
    sb   t0, cnt_min(a3)
    bgeu a3, gp, min_ok
    mv   gp, a3                # nuevo minimo
min_ok:
    # quitar p[t-250] de la ventana del minimo (si ya hay 250 previos)
    li   t0, LX
    bltu sp, t0, guardar
    addi a1, tp, OFF_LX
    andi a1, a1, RMASK
    lbu  a1, ring(a1)          # precio que sale
    lbu  t0, cnt_min(a1)
    addi t0, t0, -1
    sb   t0, cnt_min(a1)
    bnez t0, quitar_max        # quedan copias de ese precio
    bne  a1, gp, quitar_max    # no era el minimo
min_buscar:                    # buscar el siguiente valor presente
    addi gp, gp, 1
    lbu  t0, cnt_min(gp)
    beqz t0, min_buscar
quitar_max:
    # quitar p[t-500] de la ventana del maximo (si ya hay 500 previos)
    li   t0, LE
    bltu sp, t0, guardar
    addi a1, tp, OFF_LE
    andi a1, a1, RMASK
    lbu  a1, ring(a1)          # precio que sale
    add  a0, a1, a1
    lhu  t0, cnt_max(a0)
    addi t0, t0, -1
    sh   t0, cnt_max(a0)
    bnez t0, guardar
    bne  a1, s1, guardar       # no era el maximo
max_buscar:
    addi s1, s1, -1
    add  a0, s1, s1
    lhu  t0, cnt_max(a0)
    beqz t0, max_buscar
guardar:
    sb   a3, ring(tp)          # guardar p en el buffer circular
    addi tp, tp, 1
    andi tp, tp, RMASK
    li   t0, LE
    bgeu sp, t0, esperar       # contador saturado
    addi sp, sp, 1
    j    esperar

# ---------------- Datos ----------------
ring:
    .space 512                 # ultimos 512 precios (un byte cada uno)
cnt_max:
    .space 512                 # 256 cuentas de 16 bits
cnt_min:
    .space 256                 # 256 cuentas de 8 bits
