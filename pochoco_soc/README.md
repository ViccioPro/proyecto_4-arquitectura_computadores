# pochoco_soc — Proyecto 4: Pochoco Trader

Esta carpeta contiene el diseño completo del Proyecto 4 (RTL, programas en assembly, modelos en
Python, testbenches y reportes). **La documentación está en el [README principal](../README.md)**
del repositorio: síntesis y programación, ensamblado, testbenches, versión de referencia,
métricas y versiones de las herramientas.

Resumen rápido (todos los comandos se ejecutan desde esta carpeta, con OSS CAD Suite cargado):

| Comando | Qué hace |
|---|---|
| `make sim` | Simula el sistema completo con el testbench del curso y verifica decisión a decisión con el modelo |
| `make prog` | Sintetiza, hace place & route y programa la Go Board con la versión final |
| `make medir` | Verifica y mide ciclos por tick en las 9 series (simulador del Espino) |
| `make tbdon` / `make tbmul` | Testbenches de la unidad Donchian y del multiplicador |
| `make metricas` | Tablas y gráficos del informe (`docs/metricas/`) |
| `make evidencias` | Síntesis de las alternativas descartadas (`reports/evidencias/`) |

Sin parámetros, `make` usa la configuración final: programa `sw/trade.s` (canal de Donchian con
compra inicial y meta de patrimonio) con la unidad de ventana deslizante (`MUL_MODE=0`,
`DON_UNIT=1`).

Este proyecto no usa el toolchain `riscv64-unknown-elf` ni `make all` del repositorio base: los
programas se ensamblan con `assembler_v3.py` (incluido).
