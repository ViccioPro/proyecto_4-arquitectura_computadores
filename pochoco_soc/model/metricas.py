#!/usr/bin/env python3
"""
Métricas para el informe - Proyecto 4 (Pochoco Trader)

Genera en docs/metricas/:
  estrategias.csv / .tex   algoritmo vs. referencias en todas las series
  por_tick.csv / .tex      IC, ciclos, CPI y tiempo por tick (promedio y peor caso)
  rondas.tex               peor caso vs. período de cada ronda
  amdahl.tex               fracción del kernel, speedup predicho vs. medido
  recursos.tex             LUTs, celdas, BRAM y Fmax (desde reports/)
  ops_roofline.tex         Ops/s, intensidad operacional
  roofline_donchian.tex    gráfico roofline (pgfplots) del kernel Donchian
  roofline_mul.tex         gráfico roofline (pgfplots) del kernel de multiplicación
  resumen.txt              todo lo anterior en texto

Las mediciones de ciclos usan el simulador del Espino (model/espino_iss.py),
que reproduce el RTL con un error de 1-3 % (ver bitácora). Las cifras de
recursos se leen de reports/, que genera "make pnr".

Uso (desde pochoco_soc/):   python3 model/metricas.py
                            python3 model/metricas.py --rapido   (menos ticks)
"""
import argparse
import csv
import glob
import os
import re
import statistics as st
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, AQUI)
sys.path.insert(0, RAIZ)

import espino_iss as E                                   # noqa: E402
import estrategia as M                                   # noqa: E402
import assembler_v3 as A                                 # noqa: E402

F_CLK = 25e6
CPI_MIN = 2.0                      # instrucción más rápida del Espino
PERIODO_R3 = 2500                  # ciclos entre precios en la ronda 3 (100 us)
RONDAS = [("Ronda 1", 10e-3), ("Ronda 2", 1e-3), ("Ronda 3", 0.1e-3)]
SPI_NS = 9500                      # duración de la transacción SPI (testbench)
CICLOS_UNIDAD = 502                # ciclos de la unidad Donchian por precio (ventana llena)
UNIDAD_OPS_CICLO = 2               # comparaciones por ciclo de la unidad (una para H y una para L)
UNIDAD_BYTES_CICLO = 1             # bytes por ciclo que lee la unidad de su BRAM (puerto de 8 bits)
LE, LX = M.LE, M.LX
OUT = os.path.join(RAIZ, "docs", "metricas")


# ------------------------------------------------------------------
# Programas y definición de su kernel (por texto del listado)
# ------------------------------------------------------------------
def k_rango(ini, fin):
    """pcs desde la primera línea cuyo fuente contiene 'ini' hasta 'fin' (excluida)."""
    return ("rango", ini, fin)


def k_regex(expr):
    return ("regex", expr)


def k_etiquetas(ini, fin):
    return ("etiquetas", ini, fin)


# Canal de Donchian sin compra inicial, con compra inicial y con compra inicial
# + meta de patrimonio (estrategia final)
META_FINAL = 13500


def DonSin():
    return M.EstrategiaDonchian(compra_inicial=False, meta=0)


def DonIni():
    return M.EstrategiaDonchian(compra_inicial=True, meta=0)


def DonMeta():
    return M.EstrategiaDonchian(compra_inicial=True, meta=META_FINAL)


PROGRAMAS = {
    # Canal de Donchian: tres implementaciones del mismo canal (sin compra
    # inicial) para comparar las alternativas de hardware, y la versión final
    "don_ingenua": dict(src="trade_don_naive.s", ref=DonSin, mul_mode=0, don=0,
                        titulo="Donchian ingenua (SW)",
                        kernel=[k_rango("li   s1, 0", "bgeu s1, a3, mantener"),
                                k_rango("li   s1, 256", "bgeu a3, s1, mantener")]),
    "don_hist": dict(src="trade_don.s", ref=DonSin, mul_mode=0, don=0,
                     titulo="Donchian histograma (SW)",
                     kernel=[k_etiquetas("actualizar", "guardar")]),
    "don_hw": dict(src="trade_don_hw.s", ref=DonSin, mul_mode=0, don=1,
                   titulo="Donchian unidad HW",
                   kernel=[k_regex(r"\(s1\)|bnez t0, esp_unidad")]),
    "don_ini": dict(src="trade_don_ini.s", ref=DonIni, mul_mode=0, don=1,
                    titulo="Donchian HW + compra inicial",
                    kernel=[k_regex(r"\(s1\)|bnez t0, esp_unidad")]),
    "don_meta": dict(src="trade.s", ref=DonMeta, mul_mode=0, don=1,
                     titulo="Donchian HW + compra ini. + meta (final)",
                     kernel=[k_regex(r"\(s1\)|bnez t0, esp_unidad")]),
    # Estrategia anterior (reversión a la media): variantes del multiplicador
    "rev_sw": dict(src="trade_reversion.s", ref=M.EstrategiaReversion, mul_mode=0, don=0,
                   titulo="Reversión mul SW",
                   kernel=[k_etiquetas("mul", "buf_p"), k_regex(r"call mul|mv   a0, |mv   a1, (a3|t0|s1)")]),
    "rev_mulc": dict(src="trade_mulc.s", ref=M.EstrategiaReversion, mul_mode=1, don=0,
                     titulo="Reversión mulc (custom-0)",
                     kernel=[k_regex(r"\bmulc\b")]),
    "rev_mmio": dict(src="trade_mmio.s", ref=M.EstrategiaReversion, mul_mode=2, don=0,
                     titulo="Reversión mul MMIO",
                     kernel=[k_regex(r"\(t2\)|bnez t1, esp_")]),
}

# Nombre del reporte de make pnr para cada programa (reports/<nombre>_*)
REPORTES = {
    "don_ingenua": "trade_don_naive_m0_r1", "don_hist": "trade_don_m0_r1",
    "don_hw": "trade_don_hw_m0_r1_d1", "don_ini": "trade_don_ini_m0_r1_d1",
    "don_meta": "trade_m0_r1_d1",
    "rev_sw": "trade_reversion_m0_r1",
    "rev_mulc": "trade_mulc_m1_r1", "rev_mmio": "trade_mmio_m2_r1",
}


def ensamblar(src):
    with open(os.path.join(RAIZ, "sw", src)) as f:
        lineas = f.readlines()
    out, simbolos, _ = A.assemble(lineas, shift_warn=False)
    hexf = os.path.join(OUT, "_tmp_" + src.replace(".s", ".hex"))
    with open(hexf, "w") as f:
        for _, w, _, _ in out:
            f.write(f"{w:08x}\n")
    fuente = {a: raw.strip() for a, _, _, raw in out}
    return hexf, simbolos, fuente


def pcs_kernel(defs, simbolos, fuente):
    pcs = set()
    orden = sorted(fuente)
    for d in defs:
        if d[0] == "etiquetas":
            a, b = simbolos[d[1]], simbolos[d[2]]
            pcs |= {pc for pc in orden if a <= pc < b}
        elif d[0] == "regex":
            r = re.compile(d[1])
            pcs |= {pc for pc in orden if r.search(fuente[pc].split("#")[0])}
        elif d[0] == "rango":
            ini = next(pc for pc in orden if d[1] in fuente[pc])
            fin = next(pc for pc in orden if pc > ini and d[2] in fuente[pc])
            pcs |= {pc for pc in orden if ini <= pc < fin}
    return pcs


# ------------------------------------------------------------------
# Medición por tick con el simulador
# ------------------------------------------------------------------
def medir(prog, precios, periodo=PERIODO_R3):
    cfg = PROGRAMAS[prog]
    hexf, simbolos, fuente = ensamblar(cfg["src"])
    kpcs = pcs_kernel(cfg["kernel"], simbolos, fuente)
    esperar = simbolos["esperar"]
    cpu = E.Espino(hexf, 1)
    while cpu.pc != esperar:
        cpu.step()
    filas = []
    llegada = cpu.cycle
    for p in precios:
        cpu.cycle = max(cpu.cycle, llegada)
        llegada = cpu.cycle + periodo
        cpu.pending = (cpu.cycle, p)
        t0, i0 = cpu.cycle, cpu.instret
        n = len(cpu.decision_writes)
        kc = ki = kb = 0
        primero = True
        while primero or cpu.pc != esperar or len(cpu.decision_writes) == n:
            primero = False
            pc = cpu.pc
            ins = cpu.mem[(pc >> 2) % E.RAM_WORDS]
            c = cpu.cycle
            cpu.step()
            if pc in kpcs:
                kc += cpu.cycle - c
                ki += 1
                op = ins & 0x7F
                if op in (0x03, 0x23):
                    kb += 1 << (((ins >> 12) & 7) & 3)
        c_dec, val, _ = cpu.decision_writes[-1]
        filas.append(dict(decision=val, latencia=c_dec + 2 - t0, ocupado=cpu.cycle - t0,
                          ic=cpu.instret - i0, k_ciclos=kc, k_ic=ki, k_bytes=kb))
    os.remove(hexf)
    return filas


def series(rapido):
    rutas = [os.path.join(RAIZ, "tb", "practica.csv")] + sorted(glob.glob(os.path.join(RAIZ, "tb", "series", "*.csv")))
    datos = {os.path.basename(r).replace("practica_", "").replace(".csv", ""): M.leer_serie(r) for r in rutas}
    if rapido:
        datos = {k: v[:3000] for k, v in list(datos.items())[:3]}
    return datos


# ------------------------------------------------------------------
# Utilidades de salida
# ------------------------------------------------------------------
TEXTO = []


def log(s=""):
    print(s)
    TEXTO.append(s)


def tabla_tex(nombre, encabezado, filas, caption, alineacion=None):
    alineacion = alineacion or ("l" + "r" * (len(encabezado) - 1))
    esc = lambda x: str(x).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")
    with open(os.path.join(OUT, nombre), "w") as f:
        f.write("% Generado por model/metricas.py\n")
        f.write("% Requiere \\usepackage{booktabs} y \\usepackage{adjustbox}\n")
        f.write("\\begin{table}[htbp]\n\\centering\n\\small\n")
        f.write("\\begin{adjustbox}{max width=\\linewidth}\n")
        f.write(f"\\begin{{tabular}}{{{alineacion}}}\n\\toprule\n")
        f.write(" & ".join(esc(e) for e in encabezado) + " \\\\\n\\midrule\n")
        for fila in filas:
            f.write(" & ".join(esc(x) for x in fila) + " \\\\\n")
        f.write("\\bottomrule\n\\end{tabular}\n\\end{adjustbox}\n")
        f.write(f"\\caption{{{caption}}}\n\\end{{table}}\n")


def tabla_txt(encabezado, filas):
    anchos = [max(len(str(x)) for x in col) for col in zip(encabezado, *filas)]
    log("  " + "  ".join(str(e).rjust(a) for e, a in zip(encabezado, anchos)))
    for fila in filas:
        log("  " + "  ".join(str(x).rjust(a) for x, a in zip(fila, anchos)))


def csv_out(nombre, encabezado, filas):
    with open(os.path.join(OUT, nombre), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(encabezado)
        w.writerows(filas)


# ------------------------------------------------------------------
# 1. Estrategias vs. referencias
# ------------------------------------------------------------------
def seccion_estrategias(datos):
    log("=" * 70)
    log("1. ALGORITMO VS. REFERENCIAS (serie completa, reglas del testbench)")
    log("=" * 70)
    estr = [(f"Donchian + compra ini. + meta {META_FINAL}", DonMeta),
            ("Donchian + compra inicial", DonIni), ("Donchian 500/250", DonSin),
            ("Reversión N=256", M.EstrategiaReversion)]
    enc = ["Serie", "No operar", "Comprar y mantener"] + [n for n, _ in estr] + ["Órdenes Donchian", "Comisiones Donchian", "Pérd. máx. Donchian"]
    filas = []
    resumen = {n: [] for n, _ in estr}
    for k, P in datos.items():
        bh = M.referencia_comprar_mantener(P)
        fila = [k, 10000, bh["patrimonio"]]
        det = None
        for n, cls in estr:
            r = M.simular(P, lambda pr, c=cls: _decs(c, pr))
            fila.append(r["patrimonio"])
            resumen[n].append((r["patrimonio"], bh["patrimonio"]))
            if det is None:
                det = r
        fila += [det["ordenes"], det["comisiones"], det["perdida_max"]]
        filas.append(fila)
    tabla_txt(enc, filas)
    for n, v in resumen.items():
        w = [a for a, _ in v]
        gana = sum(1 for a, b in v if a > max(b, 10000))
        log(f"  {n}: media {st.mean(w):.0f}, peor {min(w)}, gana a ambas referencias en {gana}/{len(v)}")
    csv_out("estrategias.csv", enc, filas)
    tabla_tex("estrategias.tex", enc[:7], [f[:7] for f in filas],
              f"Patrimonio final por serie: estrategia final (Donchian 500/250 con compra inicial "
              f"y meta de patrimonio {META_FINAL}), Donchian con compra inicial, Donchian sin compra "
              "inicial, estrategia anterior (reversión a la media) y referencias. Capital inicial "
              "\\$10\\,000, comisión \\$5.")


def _decs(cls, precios):
    e = cls()
    return [e.tick(p) for p in precios]


# ------------------------------------------------------------------
# 2. Por tick: IC, ciclos, CPI, tiempo
# ------------------------------------------------------------------
def seccion_por_tick(datos, rapido):
    log("")
    log("=" * 70)
    log("2. MEDICIONES POR TICK (simulador del Espino, precios cada 2500 ciclos)")
    log("=" * 70)
    resultados = {}
    for prog, cfg in PROGRAMAS.items():
        filas = []
        difs = 0
        usadas = datos
        if prog == "don_ingenua":           # muy lenta de simular: 1500 ticks de una serie
            k0 = next(iter(datos))
            usadas = {k0: datos[k0][:1500]}
        calent = LE if prog.startswith("don") else M.N     # ticks de llenado de la ventana
        for k, P in usadas.items():
            r = medir(prog, P)
            ref = _decs(cfg["ref"], P)
            difs += sum(1 for a, b in zip(ref, r) if a != b["decision"])
            filas += r[calent:]          # estadísticas solo con la ventana llena
        resultados[prog] = dict(filas=filas, difs=difs, series=len(usadas))
        log(f"  {cfg['titulo']:28s} ticks {len(filas):6d}  diferencias con el modelo: {difs}")
    enc = ["Versión", "IC prom", "IC peor", "Ciclos prom", "Ciclos peor", "CPI",
           "Latencia peor", "Tiempo prom (us)", "Tiempo peor (us)"]
    filas = []
    for prog, r in resultados.items():
        F = r["filas"]
        ic = [f["ic"] for f in F]
        oc = [f["ocupado"] for f in F]
        lat = [f["latencia"] for f in F]
        filas.append([PROGRAMAS[prog]["titulo"], f"{st.mean(ic):.1f}", max(ic), f"{st.mean(oc):.1f}",
                      max(oc), f"{sum(oc)/sum(ic):.2f}", max(lat),
                      f"{st.mean(oc)/F_CLK*1e6:.2f}", f"{max(oc)/F_CLK*1e6:.2f}"])
    log("")
    log("  'Ciclos' = procesador ocupado por tick (desde que llega el precio hasta")
    log("  que vuelve a esperar el siguiente). 'Latencia' = hasta escribir DECISION.")
    tabla_txt(enc, filas)
    csv_out("por_tick.csv", enc, filas)
    tabla_tex("por_tick.tex", enc, filas,
              "Instrucciones (IC), ciclos, CPI y tiempo de ejecución por tick a 25\\,MHz, en promedio "
              "y en el peor caso. Valores del simulador del Espino sobre las series de práctica "
              "(error de 1 a 3\\,\\% frente al RTL; la latencia se contrasta con el RTL aparte).")
    return resultados


# ------------------------------------------------------------------
# 3. Rondas
# ------------------------------------------------------------------
def seccion_rondas(res):
    log("")
    log("=" * 70)
    log("3. PEOR CASO VS. PERÍODO DE CADA RONDA (ciclos disponibles = T - SPI)")
    log("=" * 70)
    enc = ["Versión"] + [f"{n} ({int((T*1e9-SPI_NS)/40)} ciclos)" for n, T in RONDAS]
    filas = []
    for prog, r in res.items():
        peor = max(f["ocupado"] for f in r["filas"])
        fila = [PROGRAMAS[prog]["titulo"]]
        for _, T in RONDAS:
            disp = (T * 1e9 - SPI_NS) / 40
            fila.append(f"{100*peor/disp:.1f}% {'OK' if peor < disp else 'NO'}")
        filas.append(fila)
    tabla_txt(enc, filas)
    tabla_tex("rondas.tex", enc, filas,
              "Peor caso de ciclos por tick como porcentaje de los ciclos disponibles en cada ronda.")


# ------------------------------------------------------------------
# 4. Amdahl
# ------------------------------------------------------------------
def seccion_amdahl(res):
    log("")
    log("=" * 70)
    log("4. LEY DE AMDAHL (promedios por tick)")
    log("=" * 70)
    log("  f = fracción de ciclos del kernel en la versión base; s_k = speedup del kernel;")
    log("  predicho = 1 / ((1 - f) + f / s_k); medido = ciclos base / ciclos variante.")
    log(f"  Con la unidad, el kernel de la variante son los ciclos del procesador más los {CICLOS_UNIDAD}")
    log("  de la unidad, como si se ejecutaran uno después del otro (Amdahl secuencial). El")
    log("  speedup medido es mayor porque la unidad trabaja en paralelo con el procesador.")
    pares = [("don_ingenua", "don_hist"), ("don_ingenua", "don_hw"), ("don_hist", "don_hw"),
             ("rev_sw", "rev_mulc"), ("rev_sw", "rev_mmio")]
    enc = ["Base", "Variante", "f (kernel)", "Kernel base", "Kernel var.", "s_k",
           "Predicho", "Medido", "Medido peor caso"]
    filas = []
    for b, v in pares:
        B, V = res[b]["filas"], res[v]["filas"]
        tb, tv = st.mean(f["ocupado"] for f in B), st.mean(f["ocupado"] for f in V)
        kb, kv = st.mean(f["k_ciclos"] for f in B), st.mean(f["k_ciclos"] for f in V)
        kv_txt = f"{kv:.1f}"
        if PROGRAMAS[v]["don"]:                  # la unidad trabaja CICLOS_UNIDAD ciclos por precio
            kv_txt = f"{kv:.1f} + {CICLOS_UNIDAD}"
            kv = kv + CICLOS_UNIDAD
        f_ = kb / tb
        sk = kb / kv if kv else float("inf")
        pred = 1 / ((1 - f_) + f_ / sk)
        med = tb / tv
        medp = max(f["ocupado"] for f in B) / max(f["ocupado"] for f in V)
        filas.append([PROGRAMAS[b]["titulo"], PROGRAMAS[v]["titulo"], f"{f_:.3f}", f"{kb:.1f}",
                      kv_txt, f"{sk:.1f}", f"{pred:.2f}x", f"{med:.2f}x", f"{medp:.2f}x"])
    tabla_txt(enc, filas)
    tabla_tex("amdahl.tex", enc, filas,
              "Ley de Amdahl: fracción del kernel en la versión base, speedup del kernel, speedup "
              "predicho y medido (ciclos de procesador por tick, promedio; última columna: peor caso). "
              f"Con la unidad, el kernel de la variante suma los ciclos del procesador y los {CICLOS_UNIDAD} "
              "de la unidad (predicción secuencial); el speedup medido la supera porque la unidad "
              "trabaja en paralelo con el procesador.")


# ------------------------------------------------------------------
# 5. Ops/s y roofline
# ------------------------------------------------------------------
def seccion_roofline(res):
    log("")
    log("=" * 70)
    log("5. OPS/S Y ROOFLINE")
    log("=" * 70)
    pi = F_CLK / CPI_MIN                 # techo de cómputo: 1 instrucción cada 2 ciclos
    beta = 4 * F_CLK / 3                 # techo de memoria: 1 palabra por load (3 ciclos)
    pi_u = UNIDAD_OPS_CICLO * F_CLK      # techo de cómputo de la unidad
    beta_u = UNIDAD_BYTES_CICLO * F_CLK  # techo de memoria de la unidad (su BRAM)
    log(f"  Espino: techo de cómputo {pi/1e6:.1f} Mops/s (1 instrucción cada 2 ciclos), techo de")
    log(f"  memoria {beta/1e6:.1f} MB/s (un lw de 4 bytes cada 3 ciclos), quiebre {pi/beta:.3f} ops/byte.")
    log(f"  Unidad Donchian: techo de cómputo {pi_u/1e6:.1f} Mops/s ({UNIDAD_OPS_CICLO} comparaciones por ciclo),")
    log(f"  techo de memoria {beta_u/1e6:.1f} MB/s (1 byte por ciclo de su BRAM), quiebre {pi_u/beta_u:.1f} ops/byte.")
    log("  Operación = operación realmente ejecutada: una instrucción del kernel en el procesador,")
    log("  o una comparación en la unidad. Bytes = bytes leídos o escritos por el kernel.")
    filas = []
    puntos = {"don": [], "mul": [], "unidad": []}

    def fila(titulo, hw, ops, nbytes, ciclos, techo_c, techo_m, grupo):
        t = ciclos / F_CLK
        perf = ops / t if t else float("inf")
        inten = ops / nbytes if nbytes else float("inf")
        techo = techo_c if inten == float("inf") else min(techo_c, techo_m * inten)
        if inten != float("inf"):
            puntos[grupo].append((titulo, inten, perf))
        filas.append([titulo, hw, f"{ops:.1f}", f"{nbytes:.1f}", f"{ciclos:.1f}",
                      "inf" if inten == float("inf") else f"{inten:.2f}", f"{perf/1e6:.2f}",
                      f"{100*perf/techo:.0f}%"])

    for prog, r in res.items():
        if prog in ("don_ini", "don_meta"):   # mismo kernel que don_hw (cambia solo la decisión)
            continue
        F = r["filas"]
        kc = st.mean(f["k_ciclos"] for f in F)
        kbytes = st.mean(f["k_bytes"] for f in F)
        kic = st.mean(f["k_ic"] for f in F)
        grupo = "don" if prog.startswith("don") else "mul"
        hw = "Espino"
        if prog == "rev_mulc":
            hw = "Espino + mulc"
        elif prog == "rev_mmio":
            hw = "Espino + mul MMIO"
        elif prog == "don_hw":
            hw = "Espino (bus)"
        titulo = PROGRAMAS[prog]["titulo"] + (" (procesador)" if prog == "don_hw" else "")
        fila(titulo, hw, kic, kbytes, kc, pi, beta, grupo)
        if prog == "don_hw":
            fila("Donchian unidad HW (unidad)", "Unidad Donchian", LE + LX, LE * UNIDAD_BYTES_CICLO,
                 CICLOS_UNIDAD, pi_u, beta_u, "unidad")
    enc = ["Versión", "Hardware", "Ops/tick", "Bytes/tick", "Ciclos", "Intensidad (ops/B)",
           "Mops/s", "% del techo"]
    tabla_txt(enc, filas)
    log("  (inf: el kernel no accede a memoria; no se puede ubicar en el roofline.)")
    tabla_tex("ops_roofline.tex", enc, filas,
              "Operaciones por segundo e intensidad operacional del kernel de cada versión (promedios "
              "por tick). Operación = operación realmente ejecutada (instrucción del kernel en el "
              "procesador, comparación en la unidad). \\% del techo: rendimiento sobre el techo del "
              "roofline del hardware que ejecuta el kernel. inf: sin accesos a memoria.",
              alineacion="llrrrrrr")
    _roofline_tex("roofline_donchian.tex", puntos["don"], pi, beta,
                  "Roofline del Espino: kernel del canal de Donchian", "Techo del Espino")
    _roofline_tex("roofline_mul.tex", puntos["mul"], pi, beta,
                  "Roofline del Espino: kernel de multiplicación (estrategia anterior)", "Techo del Espino")
    _roofline_tex("roofline_unidad.tex", puntos["unidad"], pi_u, beta_u,
                  "Roofline de la unidad Donchian (su propio techo)", "Techo de la unidad")


_MULTS = {}


def _mults_por_tick(prog, r):
    """Multiplicaciones por tick contadas en el modelo (no dependen de la implementación)."""
    return _MULTS.get(prog, 0)


def _contar_mults(datos):
    """Cuadrados por tick que calcula la estrategia de reversión (promedio)."""
    total = ticks = 0
    for P in datos.values():
        e = M.EstrategiaReversion()
        for p in P:
            antes = e.estado
            ok = e.count >= M.N - 1
            e.tick(p)
            ticks += 1
            total += 2                                   # p^2 y p_viejo^2
            if ok:
                d = M.N * p - e.S
                if not (antes == M.BLOQUEADO or d == 0 or (antes == M.FUERA and d > 0)):
                    total += 2                           # S^2 y d^2
    return total / ticks


def _roofline_tex(nombre, puntos, pi, beta, titulo, etiqueta):
    xs = [x for _, x, _ in puntos]
    ys = [y for _, _, y in puntos]
    xmin = min([0.01] + [x / 4 for x in xs])
    xmax = max([100] + [x * 4 for x in xs])
    ymin = 10 ** int(__import__("math").floor(__import__("math").log10(min(ys + [pi]) / 30)))
    ymax = 10 ** int(__import__("math").ceil(__import__("math").log10(pi * 3)))
    with open(os.path.join(OUT, nombre), "w") as f:
        f.write("% Generado por model/metricas.py - requiere \\usepackage{pgfplots}\n")
        f.write("\\begin{tikzpicture}\n\\begin{axis}[\n  xmode=log, ymode=log,\n")
        f.write("  xlabel={Intensidad operacional (ops/byte)}, ylabel={Rendimiento (ops/s)},\n")
        f.write(f"  title={{{titulo}}}, legend pos=south east, legend style={{font=\\tiny}},\n")
        f.write(f"  xmin={xmin:.4g}, xmax={xmax:.4g}, ymin={ymin:.4g}, ymax={ymax:.4g}, grid=both,\n  width=\\linewidth, height=6.5cm]\n")
        quiebre = pi / beta
        f.write(f"\\addplot[thick, black, domain={xmin:.4g}:{quiebre:.4g}, samples=2] {{{beta:.6g}*x}};\n")
        f.write(f"\\addplot[thick, black, domain={quiebre:.4g}:{xmax:.4g}, samples=2, forget plot] {{{pi:.6g}}};\n")
        f.write(f"\\addlegendentry{{{etiqueta}}}\n")
        marcas = ["*", "square*", "triangle*", "diamond*"]
        for i, (t, x, y) in enumerate(puntos):
            f.write(f"\\addplot[only marks, mark={marcas[i % 4]}, mark size=2.5pt] coordinates {{({x:.6g},{y:.6g})}};\n")
            f.write(f"\\addlegendentry{{{t}}}\n")
        f.write("\\end{axis}\n\\end{tikzpicture}\n")


# ------------------------------------------------------------------
# 6. Recursos
# ------------------------------------------------------------------
def seccion_recursos():
    log("")
    log("=" * 70)
    log("6. RECURSOS (desde reports/; generar con make pnr ...)")
    log("=" * 70)
    enc = ["Versión", "SB_LUT4", "SB_CARRY", "Flip-flops", "BRAM", "Celdas (LC)", "% LC", "Fmax (MHz)"]
    filas = []
    for prog, base in REPORTES.items():
        stat = os.path.join(RAIZ, "reports", base + "_stat.txt")
        pnr = os.path.join(RAIZ, "reports", base + "_nextpnr.log")
        if not (os.path.exists(stat) and os.path.exists(pnr)):
            cfg = PROGRAMAS[prog]
            log(f"  falta {base}: make pnr MUL_MODE={cfg['mul_mode']} DON_UNIT={cfg['don']} "
                f"PROG={cfg['src'][:-2]}")
            continue
        txt = open(stat).read()
        num = lambda celda: sum(int(m) for m in re.findall(r"(\d+)\s+" + celda + r"\b", txt))
        ffs = sum(int(m) for m in re.findall(r"(\d+)\s+SB_DFF\w*", txt))
        log_pnr = open(pnr).read()
        lc = re.findall(r"ICESTORM_LC:\s+(\d+)/\s*(\d+)", log_pnr)
        fm = re.findall(r"Max frequency for clock[^:]*:\s+([\d.]+) MHz", log_pnr)
        fmax = fm[-1] if fm else "-"
        fsem = os.path.join(RAIZ, "reports", base + "_fmax.txt")
        if os.path.exists(fsem):
            vals = [float(x) for x in re.findall(r"([\d.]+) MHz", open(fsem).read())]
            if vals:
                fmax = f"{min(vals):.1f}-{max(vals):.1f}"
        lc_u, lc_t = (int(lc[-1][0]), int(lc[-1][1])) if lc else (0, 1)
        filas.append([PROGRAMAS[prog]["titulo"], num("SB_LUT4"), num("SB_CARRY"), ffs,
                      num("SB_RAM40_4K"), lc_u, f"{100*lc_u/lc_t:.0f}%", fmax])
    # Alternativas descartadas (make evidencias -> reports/evidencias/)
    evid = [("sin_reduccion", "Diseño base sin reducción de área"),
            ("unidad_v1", "Unidad HW v1 (histogramas, descartada)"),
            ("pll", "Con PLL (descartado)")]
    hay = False
    for n, titulo in evid:
        stat = os.path.join(RAIZ, "reports", "evidencias", n + "_stat.txt")
        pnr = os.path.join(RAIZ, "reports", "evidencias", n + "_nextpnr.log")
        if not os.path.exists(stat):
            continue
        hay = True
        txt = open(stat).read()
        num = lambda celda: sum(int(m) for m in re.findall(r"(\d+)\s+" + celda + r"\b", txt))
        ffs = sum(int(m) for m in re.findall(r"(\d+)\s+SB_DFF\w*", txt))
        log_pnr = open(pnr).read() if os.path.exists(pnr) else ""
        lc = re.findall(r"ICESTORM_LC:\s+(\d+)/\s*(\d+)", log_pnr)
        fm = re.findall(r"Max frequency for clock[^:]*:\s+([\d.]+) MHz", log_pnr)
        falla = "ERROR" in log_pnr
        lc_txt, pct = "-", "-"
        if lc:
            lc_u, lc_t = int(lc[-1][0]), int(lc[-1][1])
            lc_txt, pct = lc_u, f"{100*lc_u/lc_t:.0f}%"
        if falla:
            pct = pct + " (falla nextpnr)" if pct != "-" else "falla nextpnr"
        filas.append([titulo, num("SB_LUT4"), num("SB_CARRY"), ffs, num("SB_RAM40_4K"), lc_txt, pct,
                      "-" if falla or not fm else fm[-1]])
    if not hay:
        log("  falta reports/evidencias/: make evidencias")
        filas.append(["Unidad HW v1 (histogramas, descartada)", 1208, 220, "-", 15, 1478, "115% (no cabe)", "-"])
    tabla_txt(enc, filas)
    tabla_tex("recursos.tex", enc, filas,
              "Recursos de la iCE40 HX1K por versión (yosys y nextpnr). Fmax como rango cuando se "
              "midió con varias semillas de place \\& route.")


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true", help="3 series de 3000 ticks (prueba)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    datos = series(a.rapido)
    _MULTS.update({p: _contar_mults(datos) for p in ("rev_sw", "rev_mulc", "rev_mmio")})
    seccion_estrategias(datos)
    res = seccion_por_tick(datos, a.rapido)
    seccion_rondas(res)
    seccion_amdahl(res)
    seccion_roofline(res)
    seccion_recursos()
    with open(os.path.join(OUT, "resumen.txt"), "w") as f:
        f.write("\n".join(TEXTO) + "\n")
    log("")
    log(f"Archivos generados en {os.path.relpath(OUT, RAIZ)}/")


if __name__ == "__main__":
    main()
