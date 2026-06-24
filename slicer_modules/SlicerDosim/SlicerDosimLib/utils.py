"""
Utilidades generales para SlicerDosim.

Funciones de soporte: conversion de unidades, IO,
visualizacion, y helpers para interoperar con 3D Slicer.
"""

from __future__ import annotations

import logging
import os
from typing import Optional


class SlicerDosimUtils:
    """
    Utilidades generales del modulo.

    Metodos helper para conversion de unidades,
    manejo de archivos, y extensiones de Slicer.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def hu_to_density(hu: float) -> float:
        """
        Convierte unidades Hounsfield a densidad (g/cm3).

        Tabla de conversion:
          Aire:      -1000 HU -> 0.001 g/cm3
          Agua:           0 HU -> 1.0 g/cm3
          Hueso:      +1000 HU -> 1.9 g/cm3
        """
        if hu <= -1000:
            return 0.001
        elif hu <= 0:
            # Aire -> Agua (lineal)
            return 1.0 + hu * (1.0 - 0.001) / 1000.0
        elif hu <= 1000:
            # Agua -> Hueso compacto
            return 1.0 + hu * (1.9 - 1.0) / 1000.0
        else:
            return 1.9 + (hu - 1000) * 0.001

    @staticmethod
    def activity_gbq_to_bq(activity_gbq: float) -> float:
        """Convierte GBq a Bq."""
        return activity_gbq * 1e9

    @staticmethod
    def dose_gy_to_mgy(dose_gy: float) -> float:
        """Convierte Gy a mGy."""
        return dose_gy * 1000.0

    @staticmethod
    def convert_dicom_to_nifti(dicom_dir: str, output_path: str) -> bool:
        """
        Convierte serie DICOM a NIfTI usando Slicer.
        """
        try:
            import slicer

            # Cargar DICOM
            dicom_node = slicer.util.loadVolume(dicom_dir)
            if dicom_node is None:
                return False

            # Guardar como NIfTI
            success = slicer.util.saveNode(dicom_node, output_path)
            return success
        except Exception as e:
            logging.getLogger(__name__).error(f"Error convirtiendo DICOM: {e}")
            return False

    @staticmethod
    def create_output_directory(base_dir: str, patient_id: str) -> str:
        """
        Crea estructura de directorios para resultados.

        Estructura:
          <base_dir>/<patient_id>/
            ├── mcnp/          (archivos de entrada/salida MCNP)
            ├── dose/          (mapas de dosis)
            ├── dvh/           (histogramas y reportes)
            └── segments/      (segmentaciones exportadas)
        """
        dirs = ["mcnp", "dose", "dvh", "segments"]
        patient_dir = os.path.join(base_dir, patient_id)

        for subdir in dirs:
            os.makedirs(os.path.join(patient_dir, subdir), exist_ok=True)

        return patient_dir

    @staticmethod
    def export_report_to_pdf(report_text: str, output_path: str) -> bool:
        """
        Exporta reporte de dosimetria a PDF.
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph

            doc = SimpleDocTemplate(output_path, pagesize=A4)
            story = [Paragraph(line) for line in report_text.split("\n")]
            doc.build(story)
            return True
        except ImportError:
            # Fallback: exportar como texto
            with open(output_path.replace(".pdf", ".txt"), "w") as f:
                f.write(report_text)
            return False
        except Exception as e:
            logging.getLogger(__name__).error(f"Error exportando PDF: {e}")
            return False
