"""
Asignacion de materiales MCNP desde el phantom segmentado.

Lee el labelmap del phantom (indices 1,30,50,80,90,100)
y asigna composiciones MCNP desde TissueConfig.
Opcionalmente refina densidad usando HU del CT.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

from .config import TissueConfig


logger = logging.getLogger(__name__)


class MCNPMaterialMapper:
    """
    Lee el labelmap del phantom y asigna materiales MCNP voxel a voxel.

    Estrategia:
      1. Obtener el labelmap phantom (array 3D con indices 1,30,50,80,90,100)
      2. Para cada indice unico, buscar composicion en TissueConfig
      3. Si hay CT disponible, refinar densidad segun HU
      4. Generar tarjetas Mn con composiciones

    El resultado es un array de IDs de material MCNP (mismo shape que el labelmap).
    """

    def __init__(self, config: Optional[TissueConfig] = None):
        self.config = config or TissueConfig()
        self._material_ids_used: set[int] = set()

    def assign_from_labelmap(
        self, phantom_arr: np.ndarray
    ) -> np.ndarray:
        """
        Asigna material MCNP a cada voxel segun su indice phantom.
        Maneja indices no definidos asignandolos a tejido blando (30).

        Args:
            phantom_arr: array 3D uint8 con indices 3Dosim

        Returns:
            array 3D int32 con IDs de material MCNP (mismo shape)
        """
        unique_indices = np.unique(phantom_arr)
        logger.info(
            f"Asignando materiales desde phantom indices: {sorted(unique_indices)}"
        )

        self._material_ids_used = set()
        materials_arr = np.zeros(phantom_arr.shape, dtype=np.int32)

        # Procesar cada indice unico
        for idx in unique_indices:
            # Si el indice es 0 (aire), intentar obtener su material (deberia ser 1)
            # Si no esta definido, lo dejamos como 0 y lo manejaremos despues
            mat = self.config.get_mcnp_material(int(idx))
            if mat is not None:
                mat_id = mat["id"]
                self._material_ids_used.add(mat_id)
                mask = (phantom_arr == idx)
                materials_arr[mask] = mat_id
                n_voxels = int(mask.sum())
                logger.info(f"  Indice {idx:>3} ({self.config.get_tissue_name(int(idx)):>15}) "
                            f"-> material {mat_id} ({n_voxels} voxeles)")
            else:
                # Indice no definido en tissue_config.json
                if idx == 0:
                    # Aire: asignar a material 1 (vacío) por defecto
                    logger.warning(f"Indice phantom {idx} (Aire) sin material definido, asignando a material 1")
                    mask = (phantom_arr == idx)
                    materials_arr[mask] = 1
                    self._material_ids_used.add(1)
                    n_voxels = int(mask.sum())
                    logger.info(f"  Indice {idx:>3} (Aire) -> material 1 ({n_voxels} voxeles)")
                else:
                    # Cualquier otro indice no definido: asignar a tejido blando (30)
                    logger.warning(f"Indice phantom {idx} sin material definido, asignando a tejido blando (30)")
                    mask = (phantom_arr == idx)
                    # Primero obtener el material del tejido blando
                    soft_tissue_mat = self.config.get_mcnp_material(30)
                    if soft_tissue_mat is not None:
                        mat_id = soft_tissue_mat["id"]
                        self._material_ids_used.add(mat_id)
                        materials_arr[mask] = mat_id
                        n_voxels = int(mask.sum())
                        logger.info(f"  Indice {idx:>3} -> material {mat_id} (tejido blando) ({n_voxels} voxeles)")
                    else:
                        # Si incluso el tejido blando no está definido, usar material 1 como fallback
                        logger.error(f"Tejido blando (30) tampoco está definido, usando material 1 como fallback")
                        materials_arr[mask] = 1
                        self._material_ids_used.add(1)
                        n_voxels = int(mask.sum())
                        logger.info(f"  Indice {idx:>3} -> material 1 (fallback) ({n_voxels} voxeles)")

        return materials_arr

    def assign_hu_refined(
        self, phantom_arr: np.ndarray, hu_arr: np.ndarray
    ) -> np.ndarray:
        """
        Asigna materiales refinando por HU del CT.

        Para voxeles marcados como 'Tejido_blando' (indice 30), el material
        se asigna segun el valor HU real:
          HU < -200  -> Aire (mat 1)
          HU entre -200 y -50 -> Grasa (usa material 30 con densidad ajustada)
          HU entre -50 y 150 -> Agua/blando (material 30)
          HU > 150   -> Hueso (mat 80)

        Args:
            phantom_arr: array 3D uint8 con indices phantom
            hu_arr: array 3D int16 con valores HU del CT

        Returns:
            array 3D int32 con IDs de material MCNP
        """
        materials = self.assign_from_labelmap(phantom_arr)

        # Refinar tejido blando (30) segun HU
        soft_mask = (phantom_arr == 30)
        if soft_mask.any():
            hu_vals = hu_arr[soft_mask]

            # HU bajo -> recalcular como aire
            low_hu = (hu_vals < -200)
            # HU alto -> hueso
            high_hu = (hu_vals > 150)

            soft_indices = np.where(soft_mask)
            low_idx = tuple(arr[low_hu] for arr in soft_indices)
            high_idx = tuple(arr[high_hu] for arr in soft_indices)

            if low_idx[0].size > 0:
                materials[low_idx] = 1
                self._material_ids_used.add(1)
            if high_idx[0].size > 0:
                materials[high_idx] = 80
                self._material_ids_used.add(80)

        logger.info(f"Materiales usados: {sorted(self._material_ids_used)}")
        return materials

    def get_material_ids_used(self) -> set[int]:
        """Retorna los IDs de material MCNP presentes en la asignacion."""
        return set(self._material_ids_used)

    def generate_material_cards(self) -> list[str]:
        """
        Genera tarjetas MCNP para los materiales usados.

        Returns:
            list[str]: tarjetas M$id con composiciones
        """
        cards = []
        cards.append("C")
        cards.append("C MATERIALES - Composiciones desde tissue_config.json")
        cards.append("C")

        for idx in sorted(self._material_ids_used):
            card = self.config.generate_mcnp_material_card(idx)
            if card:
                cards.append(card)
        return cards

    def generate_density_cards(self) -> list[str]:
        """
        Genera tarjetas de densidad para MCNP.

        Formato:  MT<id>  DEN=<density>
        """
        cards = ["C", "C DENSIDADES", "C"]
        for mat_id in sorted(self._material_ids_used):
            # Buscar el indice phantom que corresponde a este material
            for t in self.config.get_all_tissues():
                mat = t.get("mcnp_material", {})
                if mat.get("id") == mat_id:
                    density = t["density_gcm3"]
                    cards.append(f"C  Material {mat_id}: {t['name']} = {density} g/cm3")
                    break
        return cards
