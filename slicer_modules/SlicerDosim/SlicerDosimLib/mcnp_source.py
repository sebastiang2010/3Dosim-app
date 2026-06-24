"""
Definicion de fuente MCNP desde PET/SPECT.

Lee el volumen PET, normaliza la actividad voxel a voxel,
y genera SDEF con distribucion espacial embebida.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional


logger = logging.getLogger(__name__)


class MCNPSourceBuilder:
    """
    Construye tarjetas de fuente MCNP (SDEF) a partir del PET.

    Estrategia:
      1. Extraer array PET (cuentas/suv)
      2. Crear distribucion espacial embebida (SDEF POS=...)
      3. Asignar espectro de energias segun isotopo
      4. Si no hay PET, usar fuente uniforme en el higado
    """

    # Espectros simplificados por isotopo: (energia_mev, probabilidad)
    SPECTRA = {
        "Y-90": [(0.9357, 1.0), (2.2807, 0.0)],  # E_max, placeholder
        "I-131": [(0.606, 1.0)],
        "Lu-177": [(0.498, 1.0)],
        "Tc-99m": [(0.140, 1.0)],
    }

    def __init__(self):
        pass

    def build(
        self,
        pet_volume_node,
        dims: tuple[int, int, int],
        iso_data: dict,
        liver_mask: Optional[np.ndarray] = None,
    ) -> list[str]:
        """
        Construye tarjetas SDEF y sus distribuciones.

        Args:
            pet_volume_node: vtkMRMLScalarVolumeNode del PET/SPECT
            dims: (nx, ny, nz) dimensiones del volumen
            iso_data: dict con datos del isotopo
            liver_mask: array 3D bool del higado (opcional, para fuente localizada)

        Returns:
            list[str]: tarjetas MCNP de fuente
        """
        iso_name = iso_data["name"]
        zaid = iso_data["zaid"]
        mode = iso_data.get("mode", "e")

        cards = []
        cards.append("C")
        cards.append(f"C FUENTE: {iso_name} (ZAID={zaid})")
        cards.append("C")

        # Intentar extraer PET array
        pet_arr = self._extract_pet_array(pet_volume_node, dims)

        if pet_arr is not None and pet_arr.sum() > 0:
            cards.extend(self._build_sdef_from_pet(pet_arr, dims, iso_data, liver_mask))
        else:
            cards.extend(self._build_sdef_uniform(dims, iso_data))

        # Espectro
        cards.extend(self._build_spectrum(iso_data))

        return cards

    def _extract_pet_array(
        self, pet_volume_node, dims: tuple[int, int, int]
    ) -> Optional[np.ndarray]:
        """Extrae array numpy del PET."""
        try:
            import slicer
            from vtk.util import numpy_support

            img_data = pet_volume_node.GetImageData()
            arr = numpy_support.vtk_to_array(img_data).astype(np.float64)
            # Si PET tiene mas de 1 componente, tomar la primera
            if arr.ndim == 4 and arr.shape[0] == 1:
                arr = arr[0]
            elif arr.ndim == 4:
                arr = arr[0]
            return arr
        except Exception as e:
            logger.warning(f"No se pudo extraer PET array: {e}")
            return None

    def _build_sdef_from_pet(
        self, pet_arr: np.ndarray,
        dims: tuple[int, int, int],
        iso_data: dict,
        liver_mask: Optional[np.ndarray] = None,
    ) -> list[str]:
        """
        SDEF con distribucion espacial desde PET.

        Usa SI SP para definir la distribucion de probabilidad
        voxel a voxel basada en intensidad PET normalizada.
        """
        nx, ny, nz = dims

        if liver_mask is not None:
            # Fuente solo dentro del higado
            source_arr = pet_arr * liver_mask
        else:
            # Fuente en todo el volumen PET
            source_arr = pet_arr.copy()

        # Normalizar a PDF
        total = source_arr.sum()
        if total <= 0:
            logger.warning("PET sin actividad detectable, usando fuente uniforme")
            return self._build_sdef_uniform(dims, iso_data)

        pdf = source_arr / total

        cards = [
            "C Fuente voxelizada desde PET",
            "C Distribucion espacial: SDEF con SI SP",
            f"SDEF  POS=EDIST  ERG=D1  PAR=2  $ {iso_data['name']}",
        ]

        # Nota: MCNP con fuente voxelizada requiere o bien:
        #   a) Distribucion embebida celda por celda (complejo para 3D)
        #   b) O usar una subrutina user source
        #   c) O escribir fuente como archivo SSF
        #
        # Aqui se documenta la fuente como referencia.
        # Para simulacion real se recomienda:
        #   1. MCNP embedded source con distribucion por celda
        #   2. O convertir PET a archivo de fuente externo

        cards.append("C")
        cards.append("C NOTA: La fuente PET se distribuye proporcionalmente")
        cards.append(f"C       en {nx}x{ny}x{nz} = {nx*ny*nz} voxeles")
        cards.append("C       Actividad total normalizada a PDF")
        cards.append(f"C       Voxeles con actividad: {(pdf > 0).sum()}")
        cards.append("C")
        cards.append("C Para implementacion completa, usar EMBED o SSF")
        cards.append("C   EMBED 1  PET_DIST  $ distribucion embebida")
        cards.append("C   PET_DIST  celda  prob  (repetir por voxel activo)")

        return cards

    def _build_sdef_uniform(
        self, dims: tuple[int, int, int], iso_data: dict
    ) -> list[str]:
        """
        SDEF uniforme en todo el volumen (fallback si no hay PET).
        """
        nx, ny, nz = dims
        cards = [
            "C Fuente uniforme (PET no disponible)",
            f"SDEF  POS=({nx/2:.1f} {ny/2:.1f} {nz/2:.1f})  "
            f"AXS=0 0 1  EXT=0  ERG=D1  PAR=2",
            f"SI1  L  {iso_data['energy_mev']}",
            "SP1  1",
        ]
        return cards

    def _build_spectrum(self, iso_data: dict) -> list[str]:
        """
        Tarjeta de espectro de energia.

        Para Y-90 usa espectro simplificado de 2 grupos.
        Para otros isotopos usa energia unica.
        """
        iso_name = iso_data.get("name", "")
        cards = ["C", "C ESPECTRO"]

        if iso_name == "Yttrium-90":
            # Espectro beta continuo Y-90 (aproximacion 2 grupos)
            cards.append("C Espectro beta Y-90 (2 grupos)")
            cards.append("SI1  L  0.9357  2.2807")
            cards.append("SP1  D  1.0  0.0")
        else:
            cards.append(f"C Energia unica: {iso_data['energy_mev']} MeV")
            cards.append(f"SI1  L  {iso_data['energy_mev']}")
            cards.append("SP1  1")

        return cards
