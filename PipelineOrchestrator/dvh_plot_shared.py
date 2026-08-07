"""
dvh_plot_shared.py — Único punto de verdad para las constantes de los gráficos DVH.

Todas las rutas de plotting del pipeline Mod3 leen los colores, la cantidad de
puntos por curva y los rangos de ejes desde este módulo, garantizando que el
chart de 3D Slicer, el PNG exportado, la página DVH del PDF legacy y las
figuras del reporte LaTeX se vean visualmente idénticos:

  - colores idénticos por estructura,
  - misma cantidad de puntos por curva,
  - misma escala Y (0–105 %) y X (0 .. Dmax*1.05).

Uso:
    from PipelineOrchestrator.dvh_plot_shared import (
        DVH_COLORS, DVH_N_POINTS, DVH_Y_MAX, DVH_X_MAX_FACTOR, get_dvh_color,
    )
"""

from __future__ import annotations

# ─── Colores por estructura (RGB 0–1) ─────────────────────────────────────────
# Set canónico: los usados históricamente en el chart de 3D Slicer y en el PNG.
# Tuplas RGB en rango 0–1 porque sirven tanto para `series.SetColor(*color)`
# (API Slicer) como para matplotlib (`color=...`).
DVH_COLORS = {
    "Hígado": (0.2, 0.4, 1.0),        # azul
    "Tumor": (1.0, 0.2, 0.2),         # rojo
    "Peritumoral": (0.8, 0.6, 0.0),   # amarillo/ámbar
}

# Fallback gris para estructuras sin color asignado
DVH_COLOR_FALLBACK = (0.5, 0.5, 0.5)

# ─── Puntos por curva ─────────────────────────────────────────────────────────
# 200 = idéntico al algoritmo MATLAB f_HDV.m usado por el chart de Slicer
# (1000 puntos saturaban el plot).
DVH_N_POINTS = 200

# ─── Rangos de ejes ───────────────────────────────────────────────────────────
DVH_Y_MAX = 105           # eje Y: volumen (%) — margen superior para el 100%
DVH_X_MAX_FACTOR = 1.05   # eje X: 0 .. Dmax * 1.05


def get_dvh_color(name: str) -> tuple[float, float, float]:
    """Retorna el color RGB (0–1) de la estructura, con fallback gris."""
    return DVH_COLORS.get(name, DVH_COLOR_FALLBACK)
