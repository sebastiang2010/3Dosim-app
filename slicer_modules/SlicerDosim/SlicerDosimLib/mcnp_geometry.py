"""
Construccion de geometria voxelizada MCNP.

Genera celdas unitarias con LIKE n BUT para cada material,
un macrobody RPP global con lattice fill,
y la celda exterior de mundo.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

from .config import TissueConfig


logger = logging.getLogger(__name__)


class MCNPGeometryBuilder:
    """
    Construye la geometria MCNP usando repeated structures (LIKE n BUT).

    Estructura generada:
      - Celdas unitarias:  <id> <mat> <surfaces> u=<n> imp:e=1 imp:p=1
      - Celda global:      10 0 <surfaces> fill=<lattice>
      - Celda exterior:    99 0 <outside surfaces>
    """

    def __init__(self, config: Optional[TissueConfig] = None):
        self.config = config or TissueConfig()

    def build(
        self,
        dims: tuple[int, int, int],
        origin: tuple[float, float, float],
        spacing: tuple[float, float, float],
        materials_arr: np.ndarray,
    ) -> list[str]:
        """
        Construye las tarjetas de celda y superficie para MCNP.

        Args:
            dims: (nx, ny, nz) dimensiones del volumen
            origin: (ox, oy, oz) origen en mm
            spacing: (sx, sy, sz) espaciado de voxel en mm
            materials_arr: array 3D int32 con IDs de material por voxel

        Returns:
            list[str]: tarjetas MCNP (celdas + superficies)
        """
        nx, ny, nz = dims
        sx, sy, sz = spacing
        ox, oy, oz = origin

        cards = []
        cards.append("C")
        cards.append(f"C GEOMETRIA VOXELIZADA: {nx}x{ny}x{nz}")
        cards.append(f"C ORIGEN: {origin}  ESPACIADO: {spacing}")
        cards.append(f"C VOLUMEN TOTAL: {nx*sx:.1f} x {ny*sy:.1f} x {nz*sz:.1f} mm3")
        cards.append("C")

        # --- Celdas unitarias ---
        unique_materials = sorted(set(materials_arr.flatten()))
        # Material 0 = fuera del phantom (no deberia existir)
        unique_materials = [m for m in unique_materials if m > 0]

        for i, mat_id in enumerate(unique_materials):
            cell_id = i + 1
            mat_name = self._get_material_name(mat_id)
            surf_start = i * 6 + 1
            s1, s2, s3, s4, s5, s6 = (
                surf_start, surf_start + 1, surf_start + 2,
                surf_start + 3, surf_start + 4, surf_start + 5,
            )
            # LIKE n BUT tr=cl
            cards.append(
                f"{cell_id}  {mat_id}  -{s1} {s2} -{s3} {s4} -{s5} {s6}  "
                f"u={i+1}  imp:e=1  imp:p=1  $ {mat_name}"
            )

        # --- Superficies unitarias (RPP por voxel) ---
        for i in range(len(unique_materials)):
            surf_start = i * 6 + 1
            cards.append(f"  {surf_start}  PX  0")
            cards.append(f"  {surf_start+1}  PX  {sx}")
            cards.append(f"  {surf_start+2}  PY  0")
            cards.append(f"  {surf_start+3}  PY  {sy}")
            cards.append(f"  {surf_start+4}  PZ  0")
            cards.append(f"  {surf_start+5}  PZ  {sz}")

        # --- Macrobody global ---
        global_x = nx * sx
        global_y = ny * sy
        global_z = nz * sz

        surf_global_start = len(unique_materials) * 6 + 1
        g1, g2, g3, g4, g5, g6 = (
            surf_global_start, surf_global_start + 1,
            surf_global_start + 2, surf_global_start + 3,
            surf_global_start + 4, surf_global_start + 5,
        )

        # Celda global con lattice
        global_cell_id = len(unique_materials) + 1
        cards.append(
            f"{global_cell_id}  0  -{g1} {g2} -{g3} {g4} -{g5} {g6}  "
            f"$ phantom global"
        )

        # Lattice fill
        fill_pattern = self._build_lattice_fill(materials_arr, unique_materials)
        cards.append(f"     fill  {fill_pattern}")

        cards.append(f"  {g1}  PX  0")
        cards.append(f"  {g2}  PX  {global_x}")
        cards.append(f"  {g3}  PY  0")
        cards.append(f"  {g4}  PY  {global_y}")
        cards.append(f"  {g5}  PZ  0")
        cards.append(f"  {g6}  PZ  {global_z}")

        # --- Celda exterior ---
        last_surf = surf_global_start + 5
        outside_cell = global_cell_id + 1
        cards.append(
            f"{outside_cell}  0  {g1}:-{g2}:{g3}:-{g4}:{g5}:-{g6}  "
            f"$ outside world"
        )

        return cards

    def _build_lattice_fill(
        self, materials_arr: np.ndarray, unique_materials: list[int]
    ) -> str:
        """
        Genera el patron de fill para el lattice.

        Crea un mapping: material_id -> universo (1-indexed)
        Luego escribe el fill como:
          (nx ny nz
            m11 m12 ...  fila1
            m21 m22 ...  fila2
            ...)

        Cada 'm' es el indice del universo (1..n_materials).
        """
        mat_to_universe = {mat: i + 1 for i, mat in enumerate(unique_materials)}
        nx, ny, nz = materials_arr.shape

        # MCNP: los 3 primeros numeros son nx, ny, nz
        # Luego: el fill se escribe por filas en Y, planos en Z
        # Formato: fill  i:nx j:ny k:nz  ...datos...
        fill_parts = [f"({nx} {ny} {nz}"]

        for k in range(nz):
            for j in range(ny):
                row = []
                for i in range(nx):
                    mat_id = int(materials_arr[i, j, k])
                    universe = mat_to_universe.get(mat_id, 1)
                    row.append(str(universe))
                fill_parts.append("  " + " ".join(row))

        fill_parts.append(")")
        return "\n".join(fill_parts)

    def _get_material_name(self, mat_id: int) -> str:
        """Obtiene nombre del tejido para un material ID."""
        for t in self.config.get_all_tissues():
            mat = t.get("mcnp_material", {})
            if mat.get("id") == mat_id:
                return t["name"]
        return f"Material_{mat_id}"
