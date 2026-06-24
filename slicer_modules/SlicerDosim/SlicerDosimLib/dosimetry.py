"""
Modulo de calculo dosimetrico para SlicerDosim.

Procesa el output MCNP (archivos MCTAL) y genera mapas de dosis 3D.
Incluye metodo Monte Carlo (FMESH4 → Gy) y metodo analitico MIRD.

Conversion a Gy — MATLAB cargo_mctal.m (lineas 389-395):
  1. D_MeV_cm3 / rho(g/cm³) → D_MeV/g   (f_div_densidad)
  2. D_MeV/g * 1.6e-13      → D_J/g      (MeV2J)
  3. D_J/g * t * Actividad   → D_J/g totales
  4. * 1000                  → D_J/kg = Gy
"""

from __future__ import annotations

import logging
import numpy as np
import os
from typing import Optional

try:
    from .mctal_parser import MCTALParser, Y90_MEAN_LIFE_S
except ImportError:
    from mctal_parser import MCTALParser, Y90_MEAN_LIFE_S

logger = logging.getLogger(__name__)


class DoseCalculator:
    """
    Calculador de dosis a partir de simulaciones MCNP.

    Lee archivos MCTAL via MCTALParser, extrae dosis por voxel,
    convierte a Gy con formula MATLAB-correcta, y genera volumenes
    de dosis 3D en el escenario de 3D Slicer.
    """

    def __init__(self):
        self.logger = logger
        self.parser = MCTALParser()

    def load_mctal(
        self,
        mctal_path: str,
        nx: Optional[int] = None,
        ny: Optional[int] = None,
        nz: Optional[int] = None,
    ) -> dict:
        """
        Carga un archivo MCTAL de salida MCNP.

        Args:
            mctal_path: ruta al archivo MCTAL
            nx, ny, nz: dimensiones de la mesh (auto-detecta si None)

        Returns:
            dict con:
              - 'dose_3d': array 3D (nx, ny, nz) en MeV/cm³/particula
              - 'uncertainty': array 3D de incertidumbre
              - 'dimensions': (nx, ny, nz)
              - 'nps': numero de historias
              - 'title': titulo
        """
        if not os.path.exists(mctal_path):
            raise FileNotFoundError(f"Archivo MCTAL no encontrado: {mctal_path}")

        self.logger.info(f"Cargando MCTAL: {mctal_path}")
        dose_data = self.parser.parse(mctal_path, nx=nx, ny=ny, nz=nz)
        return dose_data

    def compute_dose_gy(
        self,
        mctal_data: dict,
        labelmap_node,
        cell_densities: dict[int, float],
        activity_bq: float,
        t_meanlife_s: float = Y90_MEAN_LIFE_S,
        error_eliminar: float = 1.5,
    ) -> Optional[np.ndarray]:
        """
        Convierte dosis MCTAL (MeV/cm³/particula) a Gy.

        Usa MCTALParser.compute_dose_gy() para la conversion exacta.

        Args:
            mctal_data: datos parseados del MCTAL
            labelmap_node: nodo de labelmap en Slicer (para densidades)
            cell_densities: dict {indice_tejido: densidad_g_cm3}
            activity_bq: actividad total en Bq
            t_meanlife_s: tiempo de integracion (mean lifetime)
            error_eliminar: umbral de error relativo

        Returns:
            array 3D de dosis en Gy, o None
        """
        import slicer

        dose_raw = mctal_data.get("dose_3d")
        if dose_raw is None:
            raise ValueError("No hay datos de dosis en MCTAL")

        # Extraer labelmap array de Slicer
        labelmap_array = slicer.util.arrayFromVolume(labelmap_node)
        # Slicer da array en (nz, ny, nx) — transponer a (nx, ny, nz)
        labelmap_array = labelmap_array.transpose(2, 1, 0)

        dims = mctal_data.get("dimensions")
        if dims and dims != (0, 0, 0):
            if labelmap_array.shape[:3] != dims:
                self.logger.warning(
                    f"Labelmap shape {labelmap_array.shape} != MCTAL dims {dims}"
                )
                # Redimensionar labelmap si es necesario
                from scipy.ndimage import zoom
                if hasattr(labelmap_array, 'shape'):
                    zx = dims[0] / labelmap_array.shape[0]
                    zy = dims[1] / labelmap_array.shape[1]
                    zz = dims[2] / labelmap_array.shape[2]
                    labelmap_array = zoom(labelmap_array, (zx, zy, zz), order=0)

        # Convertir a Gy usando el metodo estatico
        dose_gy = MCTALParser.compute_dose_gy(
            dose_raw,
            labelmap_array,
            cell_densities,
            activity_bq,
            t_meanlife_s,
            error_eliminar,
        )

        return dose_gy

    def create_dose_volume(
        self, dose_gy: np.ndarray, reference_node
    ) -> Optional[object]:
        """
        Crea un nodo de volumen escalar en Slicer con la dosis en Gy.

        Usa slicer.util.updateVolumeFromArray() que es el metodo
        recomendado por 3D Slicer y soporta arrays grandes.

        Args:
            dose_gy: array 3D (nx, ny, nz) en Gy
            reference_node: nodo de referencia para metadatos (CT/labelmap)

        Returns:
            vtkMRMLScalarVolumeNode
        """
        import slicer
        import vtk

        # Slicer espera array en (nz, ny, nx)
        dose_slicer = np.ascontiguousarray(dose_gy.astype(np.float32).transpose(2, 1, 0))

        dose_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", "Dosis_3D_Gy"
        )

        slicer.util.updateVolumeFromArray(dose_node, dose_slicer)

        if reference_node:
            dose_node.SetSpacing(reference_node.GetSpacing())
            dose_node.SetOrigin(reference_node.GetOrigin())
            ref_ijk = vtk.vtkMatrix4x4()
            reference_node.GetIJKToRASMatrix(ref_ijk)
            dose_node.SetIJKToRASMatrix(ref_ijk)

        self.logger.info(f"Nodo de dosis creado: Dosis_3D_Gy")
        return dose_node

    def compute_mird(
        self,
        liver_volume_ml: float,
        tumor_volume_ml: float,
        shunt_fraction: float = 0.0,
        t_n_ratio: Optional[float] = None,
        activity_gbq: Optional[float] = None,
        target_dose_gy: Optional[float] = None,
    ) -> dict:
        """
        Calculo MIRD partition model — MATLAB cargo_mctal.m lineas 211-227.

        Si se da activity_gbq, calcula dosis a higado y tumor.
        Si se da target_dose_gy, calcula actividad requerida.

        Args:
            liver_volume_ml: volumen de higado (ml)
            tumor_volume_ml: volumen tumoral (ml)
            shunt_fraction: fraccion de shunt pulmonar (SF, 0-1)
            t_n_ratio: relacion T/N (si no se da, se calcula de PET)
            activity_gbq: actividad administrada en GBq
            target_dose_gy: dosis target al tumor en Gy

        Returns:
            dict con resultados MIRD
        """
        k = 48.98  # J-s (MATLAB cargo_mctal.m linea 220)
        densidad_liver = 1.06  # g/cm³

        m_liver = liver_volume_ml * densidad_liver / 1000  # kg
        m_tumor = tumor_volume_ml * densidad_liver / 1000  # kg

        if t_n_ratio is None or t_n_ratio <= 0:
            t_n_ratio = 2.8  # default si no se puede calcular

        # Fracciones de uptake (MATLAB lineas 222-223)
        fu_normal = (1 - shunt_fraction) * (
            liver_volume_ml / (t_n_ratio * tumor_volume_ml + liver_volume_ml)
        )
        fu_tumor = (1 - shunt_fraction) * (
            t_n_ratio * tumor_volume_ml / (t_n_ratio * tumor_volume_ml + liver_volume_ml)
        )

        result = {
            "k_mird": k,
            "t_n_ratio": t_n_ratio,
            "shunt_fraction": shunt_fraction,
            "liver_volume_ml": liver_volume_ml,
            "tumor_volume_ml": tumor_volume_ml,
            "m_liver_kg": m_liver,
            "m_tumor_kg": m_tumor,
            "fu_normal": fu_normal,
            "fu_tumor": fu_tumor,
        }

        if activity_gbq is not None:
            # Calcular dosis desde actividad (MATLAB lineas 226-227)
            d_liver = activity_gbq * k * fu_normal / m_liver if m_liver > 0 else 0
            d_tumor = activity_gbq * k * fu_tumor / m_tumor if m_tumor > 0 else 0
            result["activity_gbq"] = activity_gbq
            result["liver_dose_gy"] = d_liver
            result["tumor_dose_gy"] = d_tumor

        if target_dose_gy is not None and m_tumor > 0 and fu_tumor > 0:
            # Calcular actividad desde dosis target
            act = target_dose_gy * m_tumor / (k * fu_tumor)
            result["target_dose_gy"] = target_dose_gy
            result["required_activity_gbq"] = act
            if activity_gbq is None:
                d_liver = act * k * fu_normal / m_liver if m_liver > 0 else 0
                result["liver_dose_gy"] = d_liver
                result["tumor_dose_gy"] = target_dose_gy

        return result
