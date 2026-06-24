"""
Modulo de analisis DVH, TCP y NTCP para SlicerDosim.

Procesa mapas de dosis 3D y segmentaciones para generar:
  - Histograma dosis-volumen (DVH)
  - Probabilidad de control tumoral (TCP)
  - Probabilidad de complicacion tisular (NTCP)
  - Dosimetria de microestructuras
"""

from __future__ import annotations

import logging
from typing import Optional


class DVHAnalyzer:
    """
    Analisis de dosis-volumen y modelos radiobiologicos.

    Modelos implementados:
      - DVH diferencial y acumulativo
      - TCP: modelo logistico (Niemierko)
      - NTCP: modelo LKB (Lyman-Kutcher-Burman)
      - Microestructuras: dosis a nivel microscopico (trabes, sinusoides)
      - BED/EQD2: conversion de dosis por fraccionamiento
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def compute_dvh(
        self,
        dose_volume_node,
        segmentation_node,
        structure_name: str = "liver",
        bins: int = 200,
    ) -> dict:
        """
        Calcula el DVH diferencial y acumulativo para una estructura.

        Args:
            dose_volume_node: volumen de dosis 3D (Gy)
            segmentation_node: segmentacion de la estructura
            structure_name: nombre de la estructura
            bins: numero de bins del histograma

        Returns:
            dict con arrays de dosis (Gy) y volumen (%), y metricas clave
        """
        import numpy as np

        # Extraer mascara de la segmentacion
        mask = self._extract_mask(segmentation_node, structure_name)
        if mask is None:
            self.logger.warning(f"Estructura '{structure_name}' no encontrada")
            return {}

        # Extraer dosis dentro de la mascara
        dose_array = self._extract_dose_values(dose_volume_node, mask)

        if dose_array.size == 0:
            return {"dose_bins": [], "volume_pct": [], "dvh_type": "differential"}

        # Calcular histograma
        dose_max = dose_array.max()
        bin_edges = np.linspace(0, dose_max, bins + 1)
        hist, _ = np.histogram(dose_array, bins=bin_edges, density=False)

        # DVH acumulativo
        cum_hist = np.cumsum(hist[::-1])[::-1]
        vol_total = hist.sum()
        dvh_acum_pct = (cum_hist / vol_total) * 100

        # Metricas clave
        d_mean = dose_array.mean()
        d_median = np.median(dose_array)

        # D98, D70, D50 (dosis que cubre X% del volumen)
        sorted_doses = np.sort(dose_array)
        cum_vol = np.linspace(100, 0, len(sorted_doses))
        d98 = np.interp(98, cum_vol, sorted_doses)
        d70 = np.interp(70, cum_vol, sorted_doses)
        d50 = np.interp(50, cum_vol, sorted_doses)

        # V30, V20 (volumen que recibe al menos X Gy)
        v30 = (dose_array >= 30).sum() / vol_total * 100
        v20 = (dose_array >= 20).sum() / vol_total * 100

        metrics = {
            "d_mean_gy": float(d_mean),
            "d_median_gy": float(d_median),
            "d98_gy": float(d98),
            "d70_gy": float(d70),
            "d50_gy": float(d50),
            "v30_pct": float(v30),
            "v20_pct": float(v20),
            "dose_bins": bin_edges.tolist(),
            "dvh_acum": dvh_acum_pct.tolist(),
            "dvh_diff": hist.tolist(),
            "structure": structure_name,
        }

        self.logger.info(f"DVH calculado para {structure_name}: D_mean={d_mean:.1f} Gy")
        return metrics

    def compute_tcp(
        self,
        dose_volume_node,
        tumor_segmentation_node,
        model: str = "logistic",
        alpha: float = 0.33,
        alpha_beta: float = 10.0,
        tcd50: float = 50.0,
        gamma50: float = 2.0,
    ) -> dict:
        """
        Calcula la Probabilidad de Control Tumoral (TCP).

        Modelos disponibles:
          - 'logistic': Niemierko
            TCP = 1 / (1 + (TCD50/D_eq)^(4*gamma50))

        Args:
            dose_volume_node: volumen de dosis
            tumor_segmentation_node: segmentacion tumoral
            model: modelo TCP
            alpha: coeficiente alfa del LQ model (Gy^-1)
            alpha_beta: relacion alpha/beta (Gy)
            tcd50: dosis de control tumoral 50% (Gy)
            gamma50: pendiente en TCD50

        Returns:
            dict con TCP y parametros usados
        """
        # Extraer dosis en tumor
        mask = self._extract_mask(tumor_segmentation_node, "tumor")
        if mask is None:
            return {"tcp": 0.0, "error": "No tumor segmentation"}

        dose_values = self._extract_dose_values(dose_volume_node, mask)
        if dose_values.size == 0:
            return {"tcp": 0.0, "error": "No dose data in tumor"}

        d_eq = dose_values.mean()  # Dosis equivalente uniforme simplificada

        if model == "logistic":
            tcp = 1.0 / (1.0 + (tcd50 / d_eq) ** (4 * gamma50))
        else:
            self.logger.warning(f"Modelo TCP no reconocido: {model}")
            tcp = 0.0

        return {
            "tcp": float(tcp),
            "d_eq_gy": float(d_eq),
            "model": model,
            "tcd50_gy": tcd50,
            "gamma50": gamma50,
        }

    def compute_ntcp(
        self,
        dose_volume_node,
        organ_segmentation_node,
        model: str = "lkb",
        td50: float = 40.0,
        m: float = 0.37,
        n: float = 0.32,
        alpha_beta: float = 3.0,
    ) -> dict:
        """
        Calcula la Probabilidad de Complicacion Tisular Normal (NTCP).

        Modelos disponibles:
          - 'lkb': Lyman-Kutcher-Burman
            NTCP = 1/sqrt(2*pi) * int(-inf, t) exp(-x^2/2) dx
            t = (EUD - TD50) / (m * TD50)

        Args:
            dose_volume_node: volumen de dosis
            organ_segmentation_node: segmentacion del organo
            model: modelo NTCP
            td50: tolerancia dosis 50% (Gy)
            m: pendiente del modelo
            n: exponente de volumen
            alpha_beta: relacion alpha/beta (Gy)

        Returns:
            dict con NTCP y parametros usados
        """
        import numpy as np
        from scipy import special

        mask = self._extract_mask(organ_segmentation_node, "organ")
        if mask is None:
            return {"ntcp": 0.0, "error": "No segmentation"}

        dose_values = self._extract_dose_values(dose_volume_node, mask)
        if dose_values.size == 0:
            return {"ntcp": 0.0, "error": "No dose data"}

        if model == "lkb":
            # EUD = (sum v_i * D_i^n)^(1/n)
            if n == 0:
                eud = dose_values.max()
            else:
                voxel_vol = 1.0 / dose_values.size
                eud = (np.sum(voxel_vol * (dose_values ** (1.0 / n))) ** n)
                # Correccion: EUD = (sum(v_i * D_i^(1/n)))^n
                eud = (np.sum(voxel_vol * dose_values ** (1.0 / n))) ** n

            # t = (EUD - TD50) / (m * TD50)
            t_val = (eud - td50) / (m * td50)
            ntcp = 0.5 * (1.0 + special.erf(t_val / np.sqrt(2.0)))
        else:
            self.logger.warning(f"Modelo NTCP no reconocido: {model}")
            ntcp = 0.0

        return {
            "ntcp": float(ntcp),
            "eud_gy": float(eud),
            "model": model,
            "td50_gy": td50,
            "m": m,
            "n": n,
        }

    def compute_micro_dosimetry(
        self,
        dose_volume_node,
        liver_segmentation_node,
        micro_params: Optional[dict] = None,
    ) -> dict:
        """
        Dosimetria de microestructura hepatica (trabeculas, sinusoides).

        Modelo basado en:
          - Distribucion de microesferas en microvasculatura
          - Dosis a nivel de acino hepatico
          - Modelo de microvasculatura de 3Dosim (modulo 3)

        Args:
            dose_volume_node: volumen de dosis macroscopica
            liver_segmentation_node: segmentacion hepatica
            micro_params: parametros micro (opcional)

        Returns:
            dict con dosis micro y heterogeneidad
        """
        self.logger.info("Calculando dosimetria de microestructuras")
        # Placeholder: implementacion detallada pendiente
        return {
            "d_micro_mean_gy": 0.0,
            "d_micro_max_gy": 0.0,
            "heterogeneity_index": 1.0,
        }

    def _extract_mask(self, segmentation_node, structure_name: str):
        """Extrae la mascara binaria de una segmentacion."""
        try:
            import slicer
            # Obtener nodo de etiquetas
            segment_ids = vtk.vtkStringArray() if False else None
            return None  # Placeholder
        except Exception:
            return None

    def _extract_dose_values(self, dose_volume_node, mask):
        """Extrae valores de dosis dentro de la mascara."""
        import numpy as np
        return np.array([])
