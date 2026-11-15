#!/usr/bin/env python3
"""
ASSEMBLER V3 - Espino Core (RV32E) sobre Pochoco SoC
Proyecto 4: Pochoco Trader

Basado en assembler_v1.py (Proyecto 2). Traduce un archivo .s a un archivo
.hex con una palabra de 32 bits en hexadecimal por linea, compatible con el
$readmemh de pochoco_ram.

Uso:
    python3 assembler_v3.py entrada.s salida.hex [-l listado.lst]
                            [--words 512] [--no-shift-warn]

Novedades respecto a v1:
  - Nombres ABI de registros (zero, ra, sp, gp, tp, t0-t2, s0/fp, s1, a0-a5).
    Se rechazan x16-x31 porque el core es RV32E.
  - Pseudoinstrucciones: nop, li, la, mv, not, neg, seqz, snez, sltz, sgtz,
    j, jr, ret, call, jal <etiqueta>, jalr <rs1>,
    beqz, bnez, blez, bgez, bltz, bgtz, bgt, ble, bgtu, bleu.
  - Directivas: .equ / .set, .word, .space, .align
    (.section, .text, .data, .global y .globl se ignoran).
  - Expresiones en inmediatos: numeros, simbolos, + - * y parentesis,
    ademas de %hi(expr) y %lo(expr).
  - Instrucciones custom: tabla CUSTOM_INSTRUCTIONS y directiva .insn
    con la misma sintaxis de GNU as (.insn r / .insn i).
  - Errores con numero de linea y la linea original.
  - Advertencia al usar shifts (en el Espino original se ejecutan como ADD).
  - Listado opcional direccion -> palabra -> linea fuente (-l).
  - Revisa que el programa quepa en la RAM (por defecto 512 palabras).
"""

import sys
import re
import argparse

# ---------------------------------------------------------------------
# 1. Registros (RV32E: solo x0-x15)
# ---------------------------------------------------------------------

REGISTERS = {f"x{i}": i for i in range(16)}
REGISTERS.update({
    "zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4,
    "t0": 5, "t1": 6, "t2": 7,
    "s0": 8, "fp": 8, "s1": 9,
    "a0": 10, "a1": 11, "a2": 12, "a3": 13, "a4": 14, "a5": 15,
})

# ---------------------------------------------------------------------
# 2. Tabla de instrucciones base: (formato, opcode, funct3, funct7)
# ---------------------------------------------------------------------

OPCODE_LOAD    = 0x03
OPCODE_CUSTOM0 = 0x0B
OPCODE_OPIMM   = 0x13
OPCODE_AUIPC   = 0x17
OPCODE_STORE   = 0x23
OPCODE_OP      = 0x33
OPCODE_LUI     = 0x37
OPCODE_BRANCH  = 0x63
OPCODE_JALR    = 0x67
OPCODE_JAL     = 0x6f

INSTR_TABLE = {
    "add":  ("R", OPCODE_OP, 0b000, 0b0000000),
    "sub":  ("R", OPCODE_OP, 0b000, 0b0100000),
    "sll":  ("R", OPCODE_OP, 0b001, 0b0000000),
    "slt":  ("R", OPCODE_OP, 0b010, 0b0000000),
    "sltu": ("R", OPCODE_OP, 0b011, 0b0000000),
    "xor":  ("R", OPCODE_OP, 0b100, 0b0000000),
    "srl":  ("R", OPCODE_OP, 0b101, 0b0000000),
    "sra":  ("R", OPCODE_OP, 0b101, 0b0100000),
    "or":   ("R", OPCODE_OP, 0b110, 0b0000000),
    "and":  ("R", OPCODE_OP, 0b111, 0b0000000),

    "addi":  ("I", OPCODE_OPIMM, 0b000, None),
    "slti":  ("I", OPCODE_OPIMM, 0b010, None),
    "sltiu": ("I", OPCODE_OPIMM, 0b011, None),
    "xori":  ("I", OPCODE_OPIMM, 0b100, None),
    "ori":   ("I", OPCODE_OPIMM, 0b110, None),
    "andi":  ("I", OPCODE_OPIMM, 0b111, None),
    "slli":  ("SHAMT", OPCODE_OPIMM, 0b001, 0b0000000),
    "srli":  ("SHAMT", OPCODE_OPIMM, 0b101, 0b0000000),
    "srai":  ("SHAMT", OPCODE_OPIMM, 0b101, 0b0100000),

    "lb":   ("ILOAD", OPCODE_LOAD, 0b000, None),
    "lh":   ("ILOAD", OPCODE_LOAD, 0b001, None),
    "lw":   ("ILOAD", OPCODE_LOAD, 0b010, None),
    "lbu":  ("ILOAD", OPCODE_LOAD, 0b100, None),
    "lhu":  ("ILOAD", OPCODE_LOAD, 0b101, None),
    "jalr": ("ILOAD", OPCODE_JALR, 0b000, None),

    "sb": ("S", OPCODE_STORE, 0b000, None),
    "sh": ("S", OPCODE_STORE, 0b001, None),
    "sw": ("S", OPCODE_STORE, 0b010, None),

    "beq":  ("B", OPCODE_BRANCH, 0b000, None),
    "bne":  ("B", OPCODE_BRANCH, 0b001, None),
    "blt":  ("B", OPCODE_BRANCH, 0b100, None),
    "bge":  ("B", OPCODE_BRANCH, 0b101, None),
    "bltu": ("B", OPCODE_BRANCH, 0b110, None),
    "bgeu": ("B", OPCODE_BRANCH, 0b111, None),

    "lui":   ("U", OPCODE_LUI, None, None),
    "auipc": ("U", OPCODE_AUIPC, None, None),

    "jal": ("J", OPCODE_JAL, None, None),
}

# Instrucciones propias (espacio custom-0, opcode 0x0B).
# Para agregar una, poner una entrada con el mismo formato de INSTR_TABLE.
# Formatos soportados: "R" (rd, rs1, rs2) e "I" (rd, rs1, imm).
# Ejemplo (descomentar cuando exista el hardware):
#   "mac": ("R", OPCODE_CUSTOM0, 0b000, 0b0000000),
CUSTOM_INSTRUCTIONS = {
}

INSTR_TABLE.update(CUSTOM_INSTRUCTIONS)

SHIFT_MNEMONICS = {"sll", "srl", "sra", "slli", "srli", "srai"}


class AsmError(Exception):
    pass


# ---------------------------------------------------------------------
# 3. Utilidades de bits
# ---------------------------------------------------------------------

def to_unsigned32(value):
    return value & 0xFFFFFFFF


def check_fits_signed(value, bits, what):
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if not (lo <= value <= hi):
        raise AsmError(f"inmediato {value} no cabe en {bits} bits con signo ({what})")


def check_fits_unsigned(value, bits, what):
    if not (0 <= value < (1 << bits)):
        raise AsmError(f"valor {value} no cabe en {bits} bits sin signo ({what})")


def hi20(value):
    """Parte alta para lui, corregida para que hi20<<12 + lo12 = value."""
    return ((to_unsigned32(value) + 0x800) >> 12) & 0xFFFFF


def lo12(value):
    """Parte baja con signo (12 bits) para addi / load / store."""
    return ((to_unsigned32(value) & 0xFFF) ^ 0x800) - 0x800


# ---------------------------------------------------------------------
# 4. Evaluador de expresiones (numeros, simbolos, + - *, (), %hi, %lo)
# ---------------------------------------------------------------------

TOKEN_RE = re.compile(r"\s*(%hi|%lo|0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d+|[A-Za-z_.][A-Za-z0-9_.]*|[-+*()])")


class Undefined(Exception):
    """Simbolo aun no definido (se usa durante la primera pasada)."""


def tokenize(expr):
    tokens = []
    pos = 0
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m:
            raise AsmError(f"expresion invalida '{expr}'")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


def eval_expr(expr, symbols):
    tokens = tokenize(expr)
    if not tokens:
        raise AsmError("falta un valor")
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def parse_sum():
        v = parse_prod()
        while peek() in ("+", "-"):
            op = take()
            r = parse_prod()
            v = v + r if op == "+" else v - r
        return v

    def parse_prod():
        v = parse_unary()
        while peek() == "*":
            take()
            v = v * parse_unary()
        return v

    def parse_unary():
        t = take()
        if t is None:
            raise AsmError(f"expresion incompleta '{expr}'")
        if t == "-":
            return -parse_unary()
        if t == "+":
            return parse_unary()
        if t == "(":
            v = parse_sum()
            if take() != ")":
                raise AsmError(f"falta ')' en '{expr}'")
            return v
        if t in ("%hi", "%lo"):
            if take() != "(":
                raise AsmError(f"se esperaba '(' despues de {t}")
            v = parse_sum()
            if take() != ")":
                raise AsmError(f"falta ')' en '{expr}'")
            return hi20(v) if t == "%hi" else lo12(v)
        if t[0].isdigit():
            return int(t.replace("_", ""), 0)
        if t in REGISTERS:
            raise AsmError(f"se esperaba un inmediato y se encontro el registro '{t}'")
        if t in symbols:
            return symbols[t]
        raise Undefined(t)

    v = parse_sum()
    if peek() is not None:
        raise AsmError(f"sobra '{peek()}' en la expresion '{expr}'")
    return v


# ---------------------------------------------------------------------
# 5. Parsing de operandos
# ---------------------------------------------------------------------

MEM_OPERAND_RE = re.compile(r"^(.*?)\(\s*([A-Za-z0-9]+)\s*\)\s*$")


def parse_register(tok):
    tok = tok.strip().lower()
    if tok in REGISTERS:
        return REGISTERS[tok]
    m = re.fullmatch(r"x(\d+)", tok)
    if m:
        raise AsmError(f"registro '{tok}' no existe en RV32E (solo x0-x15)")
    raise AsmError(f"registro invalido '{tok}'")


def parse_mem_operand(tok):
    """'imm(rs1)' -> (texto_imm, rs1). Acepta '(rs1)' y '%lo(X)(rs1)'."""
    m = MEM_OPERAND_RE.match(tok.strip())
    if not m:
        raise AsmError(f"se esperaba 'inmediato(registro)' en '{tok}'")
    imm_str = m.group(1).strip() or "0"
    return imm_str, parse_register(m.group(2))


def split_operands(text):
    """Separa por comas que no esten dentro de parentesis."""
    ops, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            ops.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        ops.append(cur.strip())
    return ops


def need(ops, n, mnemonic):
    if len(ops) != n:
        raise AsmError(f"'{mnemonic}' espera {n} operandos y recibio {len(ops)}")


# ---------------------------------------------------------------------
# 6. Codificadores por formato
# ---------------------------------------------------------------------

def encode_r(opcode, funct3, funct7, rd, rs1, rs2):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_i(opcode, funct3, rd, rs1, imm):
    check_fits_signed(imm, 12, "tipo I")
    return ((to_unsigned32(imm) & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_shamt(opcode, funct3, funct7, rd, rs1, shamt):
    if not (0 <= shamt <= 31):
        raise AsmError(f"shift amount {shamt} fuera de rango (0-31)")
    return (funct7 << 25) | (shamt << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_s(opcode, funct3, rs1, rs2, imm):
    check_fits_signed(imm, 12, "tipo S")
    imm_u = to_unsigned32(imm) & 0xFFF
    return (((imm_u >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | ((imm_u & 0x1F) << 7) | opcode


def encode_b(opcode, funct3, rs1, rs2, imm):
    if imm % 2 != 0:
        raise AsmError(f"desplazamiento de branch {imm} debe ser par")
    check_fits_signed(imm, 13, "tipo B")
    u = to_unsigned32(imm)
    return (((u >> 12) & 1) << 31) | (((u >> 5) & 0x3F) << 25) | (rs2 << 20) | \
           (rs1 << 15) | (funct3 << 12) | (((u >> 1) & 0xF) << 8) | \
           (((u >> 11) & 1) << 7) | opcode


def encode_u(opcode, rd, imm):
    if not (-(1 << 19) <= imm < (1 << 20)):
        raise AsmError(f"inmediato {imm} no cabe en 20 bits (tipo U)")
    return ((to_unsigned32(imm) & 0xFFFFF) << 12) | (rd << 7) | opcode


def encode_j(opcode, rd, imm):
    if imm % 2 != 0:
        raise AsmError(f"desplazamiento de jal {imm} debe ser par")
    check_fits_signed(imm, 21, "tipo J")
    u = to_unsigned32(imm)
    return (((u >> 20) & 1) << 31) | (((u >> 1) & 0x3FF) << 21) | \
           (((u >> 11) & 1) << 20) | (((u >> 12) & 0xFF) << 12) | (rd << 7) | opcode


# ---------------------------------------------------------------------
# 7. Pseudoinstrucciones -> lista de instrucciones base
#    Cada instruccion base es (mnemonico, [operandos como texto])
# ---------------------------------------------------------------------

BRANCH_ZERO = {  # pseudo rs, label -> base
    "beqz": ("beq", False), "bnez": ("bne", False),
    "bgez": ("bge", False), "bltz": ("blt", False),
    "blez": ("bge", True),  "bgtz": ("blt", True),
}
BRANCH_SWAP = {"bgt": "blt", "ble": "bge", "bgtu": "bltu", "bleu": "bgeu"}


def expand(mn, ops, symbols):
    """Devuelve la lista de instrucciones base. Puede lanzar Undefined
    (solo importa en la primera pasada para 'li')."""
    if mn == "nop":
        need(ops, 0, mn)
        return [("addi", ["x0", "x0", "0"])]
    if mn == "li":
        need(ops, 2, mn)
        try:
            v = eval_expr(ops[1], symbols)
        except Undefined as u:
            raise AsmError(f"'li' necesita un valor conocido; '{u}' no esta definido antes "
                           f"(defina la constante con .equ antes de usarla, o use 'la' para etiquetas)")
        if not (-(1 << 31) <= v < (1 << 32)):
            raise AsmError(f"valor {v} no cabe en 32 bits")
        v = to_unsigned32(v)
        vs = v - (1 << 32) if v & 0x80000000 else v
        if -2048 <= vs <= 2047:
            return [("addi", [ops[0], "x0", str(vs)])]
        h, l = hi20(v), lo12(v)
        if l == 0:
            return [("lui", [ops[0], str(h)])]
        return [("lui", [ops[0], str(h)]), ("addi", [ops[0], ops[0], str(l)])]
    if mn == "la":
        # La RAM es de 2 KB desde 0x0, asi que toda direccion cabe en addi.
        need(ops, 2, mn)
        return [("addi", [ops[0], "x0", ops[1]])]
    if mn == "mv":
        need(ops, 2, mn)
        return [("addi", [ops[0], ops[1], "0"])]
    if mn == "not":
        need(ops, 2, mn)
        return [("xori", [ops[0], ops[1], "-1"])]
    if mn == "neg":
        need(ops, 2, mn)
        return [("sub", [ops[0], "x0", ops[1]])]
    if mn == "seqz":
        need(ops, 2, mn)
        return [("sltiu", [ops[0], ops[1], "1"])]
    if mn == "snez":
        need(ops, 2, mn)
        return [("sltu", [ops[0], "x0", ops[1]])]
    if mn == "sltz":
        need(ops, 2, mn)
        return [("slt", [ops[0], ops[1], "x0"])]
    if mn == "sgtz":
        need(ops, 2, mn)
        return [("slt", [ops[0], "x0", ops[1]])]
    if mn == "j":
        need(ops, 1, mn)
        return [("jal", ["x0", ops[0]])]
    if mn == "call":
        need(ops, 1, mn)
        return [("jal", ["ra", ops[0]])]
    if mn == "jal" and len(ops) == 1:
        return [("jal", ["ra", ops[0]])]
    if mn == "jr":
        need(ops, 1, mn)
        return [("jalr", ["x0", f"0({ops[0]})"])]
    if mn == "ret":
        need(ops, 0, mn)
        return [("jalr", ["x0", "0(ra)"])]
    if mn == "jalr":
        if len(ops) == 1:                         # jalr rs1
            return [("jalr", ["ra", f"0({ops[0]})"])]
        if len(ops) == 3:                         # jalr rd, rs1, imm
            return [("jalr", [ops[0], f"{ops[2]}({ops[1]})"])]
        return [("jalr", ops)]
    if mn in BRANCH_ZERO:
        need(ops, 2, mn)
        base, swap = BRANCH_ZERO[mn]
        a, b = (("x0", ops[0]) if swap else (ops[0], "x0"))
        return [(base, [a, b, ops[1]])]
    if mn in BRANCH_SWAP:
        need(ops, 3, mn)
        return [(BRANCH_SWAP[mn], [ops[1], ops[0], ops[2]])]
    return [(mn, ops)]


# ---------------------------------------------------------------------
# 8. Codificacion de una instruccion base
# ---------------------------------------------------------------------

def uses_symbol(text):
    return any(t[0].isalpha() or t[0] in "_." for t in tokenize(text)
               if t not in ("%hi", "%lo"))


def imm_value(text, symbols, addr=None, relative=False):
    """Evalua un inmediato. Si relative=True y el texto es una expresion con
    simbolos (etiqueta), se calcula como desplazamiento desde addr."""
    try:
        v = eval_expr(text, symbols)
    except Undefined as u:
        raise AsmError(f"simbolo no definido '{u}'")
    if relative and uses_symbol(text):
        return v - addr
    return v


def encode(mn, ops, symbols, addr):
    if mn == ".insn":
        return encode_insn(ops, symbols)
    if mn not in INSTR_TABLE:
        raise AsmError(f"instruccion desconocida '{mn}'")
    fmt, opcode, f3, f7 = INSTR_TABLE[mn]

    if fmt == "R":
        need(ops, 3, mn)
        return encode_r(opcode, f3, f7, *(parse_register(o) for o in ops))
    if fmt == "I":
        need(ops, 3, mn)
        return encode_i(opcode, f3, parse_register(ops[0]), parse_register(ops[1]),
                        imm_value(ops[2], symbols))
    if fmt == "SHAMT":
        need(ops, 3, mn)
        return encode_shamt(opcode, f3, f7, parse_register(ops[0]), parse_register(ops[1]),
                            imm_value(ops[2], symbols))
    if fmt == "ILOAD":
        need(ops, 2, mn)
        imm_str, rs1 = parse_mem_operand(ops[1])
        return encode_i(opcode, f3, parse_register(ops[0]), rs1, imm_value(imm_str, symbols))
    if fmt == "S":
        need(ops, 2, mn)
        imm_str, rs1 = parse_mem_operand(ops[1])
        return encode_s(opcode, f3, rs1, parse_register(ops[0]), imm_value(imm_str, symbols))
    if fmt == "B":
        need(ops, 3, mn)
        return encode_b(opcode, f3, parse_register(ops[0]), parse_register(ops[1]),
                        imm_value(ops[2], symbols, addr, relative=True))
    if fmt == "U":
        need(ops, 2, mn)
        return encode_u(opcode, parse_register(ops[0]), imm_value(ops[1], symbols))
    if fmt == "J":
        need(ops, 2, mn)
        return encode_j(opcode, parse_register(ops[0]),
                        imm_value(ops[1], symbols, addr, relative=True))
    raise AsmError(f"formato no implementado: {fmt}")


def encode_insn(ops, symbols):
    """.insn r opcode, funct3, funct7, rd, rs1, rs2
       .insn i opcode, funct3, rd, rs1, imm        (sintaxis de GNU as)"""
    if not ops:
        raise AsmError(".insn sin argumentos")
    first = ops[0].split(None, 1)
    kind = first[0].lower()
    args = ([first[1]] if len(first) > 1 else []) + ops[1:]
    num = lambda t: imm_value(t, symbols)
    if kind == "r":
        if len(args) != 6:
            raise AsmError(".insn r espera: opcode, funct3, funct7, rd, rs1, rs2")
        opc, f3, f7 = num(args[0]), num(args[1]), num(args[2])
        check_fits_unsigned(opc, 7, "opcode"); check_fits_unsigned(f3, 3, "funct3")
        check_fits_unsigned(f7, 7, "funct7")
        return encode_r(opc, f3, f7, *(parse_register(a) for a in args[3:]))
    if kind == "i":
        if len(args) != 5:
            raise AsmError(".insn i espera: opcode, funct3, rd, rs1, imm")
        opc, f3 = num(args[0]), num(args[1])
        check_fits_unsigned(opc, 7, "opcode"); check_fits_unsigned(f3, 3, "funct3")
        return encode_i(opc, f3, parse_register(args[2]), parse_register(args[3]), num(args[4]))
    raise AsmError(f".insn '{kind}' no soportado (solo r e i)")


# ---------------------------------------------------------------------
# 9. Lectura de lineas
# ---------------------------------------------------------------------

LABEL_RE = re.compile(r"^\s*([A-Za-z_.][A-Za-z0-9_.]*)\s*:(.*)$")
IGNORED_DIRECTIVES = {".section", ".text", ".data", ".global", ".globl", ".option", ".file"}


def strip_comment(line):
    for marker in ("#", "//"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    return line.strip()


def split_line(raw):
    """Devuelve (lista_de_etiquetas, resto)."""
    line = strip_comment(raw)
    labels = []
    while True:
        m = LABEL_RE.match(line)
        if not m:
            break
        labels.append(m.group(1))
        line = m.group(2).strip()
    return labels, line


def split_statement(text):
    parts = text.split(None, 1)
    mn = parts[0].lower()
    ops = split_operands(parts[1]) if len(parts) > 1 else []
    return mn, ops


# ---------------------------------------------------------------------
# 10. Ensamblado en dos pasadas
# ---------------------------------------------------------------------

def assemble(lines, shift_warn=True):
    symbols = {}
    items = []          # (addr, tipo, datos, n_linea, texto)
    warnings = []
    addr = 0

    def define(name, value, lineno):
        if name in REGISTERS:
            raise AsmError(f"'{name}' es un nombre de registro")
        if name in symbols:
            raise AsmError(f"simbolo duplicado '{name}'")
        symbols[name] = value

    # ---- Pasada 1: direcciones de etiquetas y tamanos ----
    for n, raw in enumerate(lines, start=1):
        try:
            labels, rest = split_line(raw)
            for lb in labels:
                define(lb, addr, n)
            if not rest:
                continue
            mn, ops = split_statement(rest)

            if mn in IGNORED_DIRECTIVES:
                continue
            if mn in (".equ", ".set"):
                need(ops, 2, mn)
                try:
                    define(ops[0], eval_expr(ops[1], symbols), n)
                except Undefined as u:
                    raise AsmError(f".equ usa '{u}', que no esta definido antes")
                continue
            if mn == ".word":
                if not ops:
                    raise AsmError(".word sin valores")
                for o in ops:
                    items.append((addr, "word", o, n, raw.rstrip()))
                    addr += 4
                continue
            if mn == ".space":
                need(ops, 1, mn)
                size = eval_expr(ops[0], symbols)
                if size < 0 or size % 4 != 0:
                    raise AsmError(".space debe ser un multiplo de 4 bytes")
                for _ in range(size // 4):
                    items.append((addr, "word", "0", n, raw.rstrip()))
                    addr += 4
                continue
            if mn in (".align", ".p2align"):
                need(ops, 1, mn)
                align = 1 << eval_expr(ops[0], symbols)
                while addr % align:
                    items.append((addr, "word", "0", n, raw.rstrip()))
                    addr += 4
                continue
            if mn.startswith(".") and mn != ".insn":
                raise AsmError(f"directiva no soportada '{mn}'")

            for bmn, bops in expand(mn, ops, symbols):
                if shift_warn and bmn in SHIFT_MNEMONICS:
                    warnings.append(f"linea {n}: '{bmn}' se ejecuta como ADD en el Espino "
                                    f"original (shifts deshabilitados en la ALU)")
                items.append((addr, "instr", (bmn, bops), n, raw.rstrip()))
                addr += 4
        except AsmError as e:
            raise AsmError(f"linea {n}: {e}\n    {raw.rstrip()}") from None

    # ---- Pasada 2: codificacion ----
    out = []
    for a, kind, data, n, raw in items:
        try:
            if kind == "word":
                v = imm_value(data, symbols)
                if not (-(1 << 31) <= v < (1 << 32)):
                    raise AsmError(f"valor {v} no cabe en 32 bits")
                word = to_unsigned32(v)
            else:
                word = encode(data[0], data[1], symbols, a)
            out.append((a, word, n, raw))
        except AsmError as e:
            raise AsmError(f"linea {n}: {e}\n    {raw}") from None
    return out, symbols, warnings


# ---------------------------------------------------------------------
# 11. Programa principal
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Assembler RV32E para el Espino Core (v3)")
    ap.add_argument("entrada", help="archivo .s")
    ap.add_argument("salida", help="archivo .hex")
    ap.add_argument("-l", "--listado", help="genera un listado direccion/palabra/fuente")
    ap.add_argument("--words", type=int, default=512,
                    help="palabras de RAM disponibles (NumWords de pochoco_soc, por defecto 512)")
    ap.add_argument("--no-shift-warn", action="store_true",
                    help="no advertir por shifts (usar cuando la ALU tenga shifter)")
    args = ap.parse_args()

    with open(args.entrada) as f:
        lines = f.readlines()
    try:
        out, symbols, warnings = assemble(lines, shift_warn=not args.no_shift_warn)
    except AsmError as e:
        print(f"ERROR en {args.entrada}, {e}", file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"ADVERTENCIA: {w}", file=sys.stderr)

    n_words = len(out)
    if n_words > args.words:
        print(f"ERROR: el programa ocupa {n_words} palabras y la RAM tiene {args.words}",
              file=sys.stderr)
        sys.exit(1)

    with open(args.salida, "w") as f:
        for _, w, _, _ in out:
            f.write(f"{w:08x}\n")

    if args.listado:
        with open(args.listado, "w") as f:
            f.write("# direccion  palabra   linea  fuente\n")
            for a, w, n, raw in out:
                f.write(f"0x{a:08x}  {w:08x}  {n:5d}  {raw.strip()}\n")
            f.write("\n# Simbolos\n")
            for name, v in sorted(symbols.items(), key=lambda kv: kv[1]):
                f.write(f"# {name:24s} = 0x{to_unsigned32(v):08x} ({v})\n")

    print(f"{args.entrada} -> {args.salida}: {n_words} palabras "
          f"({n_words * 4} bytes) de {args.words} disponibles", file=sys.stderr)


if __name__ == "__main__":
    main()
