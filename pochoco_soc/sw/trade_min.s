# ============================================================
# trade.s - version minima (prueba de comunicacion SPI)
# Proyecto 4: Pochoco Trader - Espino Core (RV32E)
#
# Espera cada precio, lo muestra en los displays y responde
# siempre "mantener" (0x00). Sirve para validar el flujo
# completo (assembler -> testbench -> placa) antes de tener
# el algoritmo. Equivale a la referencia "no operar".
# ============================================================

.equ SPI_BASE, 0x80010000      # +0 status, +4 precio, +8 DECISION
.equ PER_BASE, 0x80000000      # +0 displays, +4 LEDs, +C ciclos

_start:
    li   s0, SPI_BASE
    li   s1, PER_BASE

esperar_precio:
    lw   t0, 0(s0)             # status: bit0 = precio nuevo
    andi t0, t0, 1
    beqz t0, esperar_precio

    lw   a0, 4(s0)             # leer precio (borra el flag)
    sw   zero, 8(s0)           # DECISION = 00 (mantener)
    sw   a0, 0(s1)             # mostrar precio en hexadecimal
    j    esperar_precio
