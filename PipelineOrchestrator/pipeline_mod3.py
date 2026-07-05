"""
PipelineMod3 - Modulo 3: Analisis Dosimetrico desde escena + MCTAL.
Flujo: carga escena .mrb, parsea MCTAL, convierte a Gy, DVH, MIRD,
reporte PDF, nodo de dosis 3D en Slicer.

REUTILIZA las funciones de run_dosimetry_from_scene.py (no duplica 1890 lines).

Sigue EXACTAMENTE el mismo patron que PipelineMod1 y PipelineMod2:
CheckpointManager, _checkpoint_step, _ai_review_paso, ConsolaComandos.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Optional

import numpy as np

from PipelineOrchestrator.checkpoint import CheckpointManager
from PipelineOrchestrator.utils import logger as base_logger, add_module_path, show_progress, track_time
from PipelineOrchestrator.views import setup_medical_views, load_pipeline_config
from PipelineOrchestrator.comandos import ConsolaComandos
from PipelineOrchestrator import ai_supervisor
from PipelineOrchestrator.latex_report_generator import generate_latex_report

# ─── Reutilizar funciones de run_dosimetry_from_scene ────────────────────────
from PipelineOrchestrator.run_dosimetry_from_scene import (
    load_scene,
    find_nodes,
    compute_activity_from_pet,
    parse_mctal,
    convert_to_gy,
    compute_dvh,
    compute_biophysical,
    compute_mird,
    generate_pdf_report,
    _create_dvh_plots_slicer,
    # Constantes
    LIVER_INDEX,
    TUMOR_INDEX,
    PRETUMOR_INDEX,
    AIR_INDEX,
    ALPHA_BETA_LIVER,
    ALPHA_BETA_TUMOR,
    DENSIDAD_LIVER,
    DENSIDAD_TUMOR,
    DENSIDAD_PRETUMOR,
    DENSIDAD_BODY,
    DENSIDAD_AIR,
    Y90_HALF_LIFE_H,
    LAMDA_DECAY,
    MU_REPAIR,
    MEV2J,
    OUTPUT_DIR_DEFAULT,
    SCENE_DEFAULT,
    MCTAL_DEFAULT,
    LABELMAP_DEFAULT,
    AI_PIPE_DIR,
)

logger = logging.getLogger("3DosimMod3")

# ─── Constantes locales ──────────────────────────────────────────────────────

DEFAULT_NPS_LABEL = "1.0e+08"


# ======================================================================
# PipelineMod3
# ======================================================================

class PipelineMod3:
    """
    Pipeline Modulo 3: Analisis Dosimetrico desde escena + MCTAL.

    Pasos:
      1. Cargar escena .mrb
      2. Buscar CT, PET, Labelmap
      3. Computar actividad desde PET
      4. Parsear archivo MCTAL
      5. Convertir MeV/cm³ → Gy
      6. DVH y radiobiologia por estructura
      7. MIRD partition model
      8. Exportar reporte (JSON + TXT + PDF)
      9. Crear nodo de dosis 3D en Slicer + overlay
     10. Mostrar DVH en Slicer + guardar escena
    """

    STEP_LOAD_SCENE     = "load_scene"
    STEP_FIND_NODES     = "find_nodes"
    STEP_ACTIVITY       = "compute_activity"
    STEP_PARSE_MCTAL    = "parse_mctal"
    STEP_CONVERT        = "convert_to_gy"
    STEP_DVH            = "compute_dvh"
    STEP_MIRD           = "compute_mird"
    STEP_EXPORT_REPORT  = "export_report"
    STEP_DOSE_NODE      = "create_dose_node"
    STEP_DOSE_SCENE     = "dvh_and_save_scene"

    # ==================================================================
    # __init__
    # ==================================================================

    def __init__(
        self,
        scene_path: Optional[str] = None,
        mctal_path: Optional[str] = None,
        labelmap_path: Optional[str] = None,
        activity_gbq: Optional[float] = None,
        output_dir: Optional[str] = None,
        reset: bool = False,
        flip: bool = True,
        no_consola: bool = False,
        patient_id: Optional[str] = None,
    ):
        """
        Args:
            scene_path: Ruta a escena .mrb. Si None, auto-detecta.
            mctal_path: Ruta a archivo MCTAL. Si None, usa default.
            labelmap_path: Ruta a labelmap NIfTI. Si None, busca en escena.
            activity_gbq: Actividad en GBq. Si None, computa del PET.
            output_dir: Directorio de salida. Si None, usa default.
            reset: Reiniciar checkpoints.
            flip: Aplicar flip Y a dosis MCTAL (default True).
            no_consola: Deshabilitar consola interactiva.
        """
        # ── Paths ──
        self.scene_path = scene_path or self._auto_detect_scene()
        self.mctal_path = mctal_path or MCTAL_DEFAULT
        self.labelmap_path = labelmap_path or LABELMAP_DEFAULT
        self.activity_gbq_input = activity_gbq
        self.flip = flip
        self.patient_id = patient_id

        if output_dir:
            self.output_dir = output_dir
        else:
            self.output_dir = OUTPUT_DIR_DEFAULT

        self.checkpoint_dir = os.path.join(self.output_dir, ".checkpoints", "mod3")
        self.results_data = {
            "metadata": {},
            "structures": {},
            "mird": {},
        }

        self.checkpoint = CheckpointManager(self.checkpoint_dir)
        if reset:
            self.checkpoint.reset()

        # ── Nodos Slicer (se llenan en load/find nodes) ──
        self.ct_node = None
        self.pet_node = None
        self.labelmap_node = None
        self.segmentation_node = None
        self.dose_node = None

        # ── Arrays (se llenan durante el pipeline) ──
        self.labelmap_array: Optional[np.ndarray] = None
        self.dose_mev_cm3: Optional[np.ndarray] = None
        self.dose_gy: Optional[np.ndarray] = None
        self.error_3d: Optional[np.ndarray] = None
        self.activity_bq: float = 0.0
        self.activity_gbq: float = 0.0
        self.dims: tuple = ()
        self.spacing: tuple = ()
        self.dvh_curves_for_pdf: list = []
        self.pdf_path: Optional[str] = None

        # ── Resultados para checkpoint ──
        self.results = {"pasos": [], "errores": [], "tiempos": {}}

        # ── Consola ──
        self.no_consola = no_consola
        self.consola = None
        if not no_consola:
            try:
                self.consola = ConsolaComandos(output_dir=self.output_dir)
            except Exception:
                self.consola = None

        # ── Config ──
        self.pipeline_config = load_pipeline_config()
        self.scene_output_dir = self.pipeline_config.get(
            "scene_output_dir",
            os.path.join(self.output_dir, "scenes"),
        )

        logger.info("=" * 60)
        logger.info(" 3Dosim Pipeline Modulo 3 — Analisis Dosimetrico")
        logger.info("=" * 60)
        logger.info(f"  Escena:       {self.scene_path or 'NO DISPONIBLE'}")
        logger.info(f"  MCTAL:        {self.mctal_path}")
        logger.info(f"  Labelmap:     {self.labelmap_path}")
        logger.info(f"  Activity:     {activity_gbq if activity_gbq is not None else 'desde PET'} GBq")
        logger.info(f"  Flip Y:       {flip}")
        logger.info(f"  Output:       {self.output_dir}")
        logger.info(f"  Checkpoints:  {self.checkpoint_dir}")
        logger.info(f"  Reset:        {'SI' if reset else 'NO (retoma checkpoints)'}")
        logger.info(f"  Consola:      {'SI' if not no_consola else 'NO'}")
        logger.info("")

    # ==================================================================
    # RUN
    # ==================================================================

    def run(self):
        """Ejecuta el pipeline Mod3 completo."""
        logger.info("")
        logger.info("INICIANDO PIPELINE MODULO 3")
        logger.info("")

        # ── Mostrar consola interactiva ──
        if self.consola:
            self.consola.log("=" * 50)
            self.consola.log(" 3Dosim Mod3 - Analisis Dosimetrico")
            self.consola.log(" Escribi 'ayuda' para comandos disponibles")
            self.consola.log("=" * 50)
            self.consola.log("")
            self.consola.mostrar()
        self._log_consola("Iniciando Modulo 3...")

        # ── Verificar pre-requisitos ──
        if not self.scene_path or not os.path.exists(self.scene_path):
            logger.error(f"Escena .mrb no encontrada: {self.scene_path}")
            logger.error("Ejecute Modulo 1 primero o especifique --scene")
            self._log_consola_error("ERROR: Escena .mrb no encontrada")
            self._report()
            return

        if not os.path.exists(self.mctal_path):
            logger.error(f"Archivo MCTAL no encontrado: {self.mctal_path}")
            logger.error("Ejecute MCNP primero o especifique --mctal")
            self._log_consola_error("ERROR: Archivo MCTAL no encontrado")
            self._report()
            return

        # ── 1. Cargar escena ──
        self._log_consola("Paso 1/10: Cargando escena .mrb...")
        try:
            self._load_scene()
            self.results["pasos"].append({
                "nombre": "Cargando escena .mrb", "ok": True, "tiempo": 0
            })
            self._log_consola_ok("Escena cargada exitosamente")
        except Exception as e:
            logger.error(f"Fallo critico al cargar escena: {e}. Abortando.")
            self._log_consola_error(f"ERROR: Fallo al cargar escena - {e}")
            self._report()
            return

        # ── 2. Buscar nodos ──
        self._log_consola("Paso 2/10: Buscando nodos (CT, PET, Labelmap)...")
        try:
            self._find_and_prepare_nodes()
            self.results["pasos"].append({
                "nombre": "Buscando nodos", "ok": True, "tiempo": 0
            })
            self._log_consola_ok(
                f"Nodos: CT={self.ct_node.GetName() if self.ct_node else 'N/A'}, "
                f"PET={self.pet_node.GetName() if self.pet_node else 'N/A'}, "
                f"Labelmap={self.labelmap_node.GetName() if self.labelmap_node else 'N/A'}"
            )
        except Exception as e:
            logger.error(f"Fallo al buscar nodos: {e}. Abortando.")
            self._log_consola_error(f"ERROR: Fallo al buscar nodos - {e}")
            self._report()
            return

        # ── 3. Actividad ──
        self._log_consola("Paso 3/10: Computando actividad desde PET...")
        if not self._checkpoint_step(
            self.STEP_ACTIVITY, "Actividad desde PET",
            self._compute_activity,
            data_func=lambda: {
                "activity_bq": self.activity_bq,
                "activity_gbq": self.activity_gbq,
                "method": "from_PET" if self.activity_gbq_input is None else "input",
            },
        ):
            logger.warning("Computo de actividad fallo, usando default (3 GBq)")
            self.activity_bq = 3e9
            self.activity_gbq = 3.0

        self._save_scene("01_post_activity")
        self._tomar_screenshot("01_actividad")

        # ── 4. Parsear MCTAL ──
        self._log_consola("Paso 4/10: Parseando archivo MCTAL...")
        if not self._checkpoint_step(
            self.STEP_PARSE_MCTAL, "Parsear MCTAL",
            self._parse_mctal,
            data_func=lambda: {
                "mctal_path": self.mctal_path,
                "dims": list(self.dims),
                "nps": int(getattr(self, '_mctal_nps', 0)),
            },
        ):
            logger.error("Fallo al parsear MCTAL. Abortando.")
            self._log_consola_error("ERROR: Fallo al parsear MCTAL")
            self._report()
            return

        self._save_scene("02_post_mctal")
        self._tomar_screenshot("02_mctal_parseado")

        # ── 5. Convertir a Gy ──
        self._log_consola("Paso 5/10: Convirtiendo MeV/cm3 a Gy...")
        if not self._checkpoint_step(
            self.STEP_CONVERT, "Convertir a Gy",
            self._convert_to_gy,
            data_func=lambda: {
                "mean_dose": float(np.mean(self.dose_gy[self.dose_gy > 0])) if self.dose_gy is not None and np.any(self.dose_gy > 0) else 0,
                "max_dose": float(np.max(self.dose_gy)) if self.dose_gy is not None else 0,
                "bad_voxels_removed": int(getattr(self, '_n_bad_voxels', 0)),
                "neg_voxels_zeroed": int(getattr(self, '_n_neg_voxels', 0)),
            },
        ):
            logger.error("Conversion a Gy fallida. Abortando.")
            self._log_consola_error("ERROR: Conversion a Gy fallida")
            self._report()
            return

        self._tomar_screenshot("03_dosis_gy")

        # ── 6. DVH por estructura ──
        self._log_consola("Paso 6/10: Computando DVH y radiobiologia...")
        if not self._checkpoint_step(
            self.STEP_DVH, "DVH y radiobiologia",
            self._compute_dvh,
            data_func=lambda: {
                "structures": {
                    name: {
                        "n_voxels": s.get("n_voxels", 0),
                        "mean_dose_gy": s.get("mean_dose_gy", 0),
                        "d98_gy": s.get("d98_gy", 0),
                        "bed_gy": s.get("bed_gy", 0),
                    }
                    for name, s in self.results_data.get("structures", {}).items()
                },
            },
        ):
            logger.warning("DVH computado con problemas, continuando...")

        self._save_scene("03_post_dvh")
        self._tomar_screenshot("04_dvh")

        # ── 7. MIRD ──
        self._log_consola("Paso 7/10: Calculando MIRD partition model...")
        if not self._checkpoint_step(
            self.STEP_MIRD, "MIRD partition model",
            self._compute_mird,
            data_func=lambda: {
                "mird": self.results_data.get("mird", {}),
            },
        ):
            logger.warning("MIRD fallo, continuando...")

        self._tomar_screenshot("05_mird")

        # ── 8. Exportar reporte ──
        self._log_consola("Paso 8/10: Exportando reporte (JSON + TXT + PDF)...")
        if not self._checkpoint_step(
            self.STEP_EXPORT_REPORT, "Exportar reporte",
            self._export_report,
            data_func=lambda: {
                "json_path": self._report_json_path if hasattr(self, '_report_json_path') else "",
                "txt_path": self._report_txt_path if hasattr(self, '_report_txt_path') else "",
                "pdf_path": self.pdf_path or "",
            },
        ):
            logger.warning("Exportacion de reporte fallo, continuando...")

        self._save_scene("04_post_report")
        self._tomar_screenshot("06_reporte")

        # ── 9. Crear nodo de dosis 3D ──
        self._log_consola("Paso 9/10: Creando nodo de dosis 3D en Slicer...")
        if not self._checkpoint_step(
            self.STEP_DOSE_NODE, "Nodo de dosis 3D",
            self._create_dose_node,
            data_func=lambda: {
                "dose_node_name": self.dose_node.GetName() if self.dose_node else None,
            },
        ):
            logger.warning("Creacion de nodo de dosis fallo, continuando...")

        self._save_scene("05_post_dose_node")
        self._tomar_screenshot("07_dosis_3d")

        # ── 10. DVH en Slicer + guardar escena final ──
        self._log_consola("Paso 10/10: Graficando DVH en Slicer y guardando escena...")
        if not self._checkpoint_step(
            self.STEP_DOSE_SCENE, "DVH en Slicer + escena final",
            self._create_dvh_and_save,
            data_func=lambda: {
                "scene_saved": os.path.exists(os.path.join(self.output_dir, "3Dosim_dosis_scene.mrb")),
            },
        ):
            logger.warning("DVH / escena final con problemas, continuando...")

        self._tomar_screenshot("10_dvh_final")

        # ── Pipeline Mod3 completado ──
        logger.info("")
        logger.info("  PIPELINE MODULO 3 COMPLETADO")
        logger.info("")
        logger.info("  Flujo ejecutado:")
        logger.info("    1. Cargar escena .mrb")
        logger.info("    2. Buscar nodos (CT, PET, Labelmap)")
        logger.info("    3. Computar actividad desde PET")
        logger.info("    4. Parsear archivo MCTAL")
        logger.info("    5. Convertir MeV/cm3 a Gy")
        logger.info("    6. DVH y radiobiologia por estructura")
        logger.info("    7. MIRD partition model")
        logger.info("    8. Exportar reporte (JSON + TXT + PDF)")
        logger.info("    9. Crear nodo de dosis 3D en Slicer")
        logger.info("   10. Graficar DVH en Slicer + guardar escena")
        logger.info("")

        self._log_consola("Modulo 3 completado. Generando reporte...")
        ok = self._report()
        if ok:
            self._log_consola("Modulo 3 finalizado EXITOSAMENTE")
        else:
            self._log_consola("Modulo 3 finalizado con ERRORES. Revise el reporte.")

    # ==================================================================
    # CHECKPOINT + HELPERS (mismo patron que PipelineMod1)
    # ==================================================================

    def _checkpoint_step(self, step_name, display_name, func, data_func=None):
        if self.checkpoint.is_completed(step_name):
            logger.info(f"  [{'...'}]: ya completado (checkpoint salta)")
            self.results["pasos"].append({
                "nombre": display_name, "ok": True, "tiempo": 0, "checkpoint": True,
            })
            self._log_consola(f"[checkpoint] {display_name} — ya completado, saltando")
            cp_data = self.checkpoint.get_data(step_name)
            if cp_data:
                self._restore_step_state(step_name, cp_data)
            return True

        logger.info(f"[{len(self.results['pasos'])+1}] {display_name}...")
        show_progress(f"Ejecutando: {display_name}")
        self._log_consola(f"Ejecutando: {display_name}...")

        t0 = time.time()
        try:
            func()
            elapsed = time.time() - t0
            logger.info(f"  Completado en {elapsed:.1f}s")
            self.results["pasos"].append({
                "nombre": display_name, "ok": True, "tiempo": elapsed,
            })
            self.results["tiempos"][display_name] = elapsed
            data = data_func() if data_func else {}
            self.checkpoint.mark_completed(step_name, data=data)
            show_progress(f"{display_name} completado")
            self._log_consola_ok(f"{display_name} — {elapsed:.1f}s")
            self._ai_review_paso(display_name, ok=True, elapsed=elapsed,
                                 step_name=step_name, data=data)
            return True
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"  FALLO: {e}")
            self.results["pasos"].append({
                "nombre": display_name, "ok": False, "tiempo": elapsed,
            })
            self.results["errores"].append(f"{display_name}: {e}")
            show_progress(f"FALLO: {display_name}")
            self._log_consola_error(f"{display_name} — FALLO: {e}")
            self._ai_review_paso(display_name, ok=False, elapsed=elapsed,
                                 step_name=step_name, error=str(e))
            return False

    def _ai_review_paso(self, display_name, ok, elapsed, step_name, data=None, error=None):
        """Revisa el paso via AI supervisor (DeepSeek/OpenRouter)."""
        try:
            ctx = {
                "paso": display_name,
                "ok": ok,
                "tiempo": elapsed,
                "datos": data or {},
                "errores": [error] if error else [],
            }
            nodos_info = {}
            if self.ct_node:
                nodos_info["CT"] = self.ct_node.GetName()
            if self.pet_node:
                nodos_info["PET"] = self.pet_node.GetName()
            if self.labelmap_node:
                nodos_info["Labelmap"] = self.labelmap_node.GetName()
            if self.dose_node:
                nodos_info["Dosis"] = self.dose_node.GetName()
            ctx["datos"]["nodos_activos"] = nodos_info
            ctx["datos"]["activity_gbq"] = self.activity_gbq
            if self.dose_gy is not None:
                ctx["datos"]["dose_max_gy"] = float(np.max(self.dose_gy))
                ctx["datos"]["dose_mean_gt0_gy"] = float(np.mean(self.dose_gy[self.dose_gy > 0])) if np.any(self.dose_gy > 0) else 0
            ai_supervisor.revisar_paso(ctx, consola=self.consola)
        except Exception as e:
            logger.debug(f"AI review no disponible: {e}")

    def _restore_step_state(self, step_name, data):
        """Restaura estado desde checkpoint data."""
        if not data:
            return
        import slicer

        # Restaurar nodos por nombre
        node_keys = {
            "ct_node": "ct_node",
            "pet_node": "pet_node",
            "labelmap_node": "labelmap_node",
            "dose_node": "dose_node",
        }
        for data_key, attr_name in node_keys.items():
            name_key = data_key + "_name"
            node_name = None
            if name_key in data and data[name_key]:
                node_name = data[name_key]
            elif data_key in data and isinstance(data[data_key], str) and data[data_key]:
                node_name = data[data_key]
            if node_name:
                try:
                    node = slicer.util.getNode(node_name)
                    setattr(self, attr_name, node)
                except Exception:
                    pass

        # Restaurar valores escalares
        scalar_map = {
            "activity_bq": "activity_bq",
            "activity_gbq": "activity_gbq",
            "dims": "dims",
            "spacing": "spacing",
        }
        for data_key, attr_name in scalar_map.items():
            if data_key in data and data[data_key] is not None:
                setattr(self, attr_name, data[data_key])

        # Restaurar arrays desde paths guardados
        if data.get("dose_gy_path") and os.path.exists(data["dose_gy_path"]):
            try:
                self.dose_gy = np.load(data["dose_gy_path"])
            except Exception:
                pass
        if data.get("labelmap_path_saved") and os.path.exists(data["labelmap_path_saved"]):
            try:
                self.labelmap_array = np.load(data["labelmap_path_saved"])
            except Exception:
                pass

        # Restaurar resultados_data
        if data.get("results_data"):
            self.results_data = data["results_data"]

        # Restaurar PDF path
        if data.get("pdf_path"):
            self.pdf_path = data["pdf_path"]

        # Restaurar visualizacion si hay nodos
        if self.ct_node or self.pet_node:
            try:
                setup_medical_views(
                    ct_node=self.ct_node,
                    pet_node=self.pet_node,
                )
            except Exception as e:
                logger.debug(f"No se pudo restaurar visualizacion: {e}")

    def _save_scene(self, tag=None, force=False):
        """Guarda la escena 3Dosim.mrb (una sola, se sobrescribe).

        Args:
            tag: Identificador opcional para el paso (log).
            force: Si True, guarda siempre ignorando config save_scene.frequency.
        """
        import slicer
        # ── Verificar config de frecuencia ──
        freq = self.pipeline_config.get("save_scene", {}).get("frequency", "minimal")
        if not force and freq == "minimal":
            allowed = {"01_post_activity", "02_post_mctal", "03_post_dvh", "04_post_report", "05_post_dose_node"}
            if tag not in allowed:
                logger.info(f"  Escena '{tag}' omitida (save_scene.frequency=minimal)")
                return None

        # ── Mostrar cartel no-modal "Guardando escena..." ──
        dialog = None
        try:
            from qt import QDialog, QVBoxLayout, QLabel, QApplication
            main_w = slicer.util.mainWindow()
            dialog = QDialog(main_w)
            dialog.setWindowTitle("3Dosim — Guardando escena")
            dialog.setModal(False)
            dialog.setMinimumWidth(320)
            layout = QVBoxLayout(dialog)
            msg = QLabel(
                "<b>Guardando escena...</b><br>"
                "Puede tomar hasta 2 minutos si la escena es grande.<br>"
                "No cerrar Slicer."
            )
            msg.setWordWrap(True)
            msg.setStyleSheet("font-size: 13px; padding: 15px; color: #2c3e50;")
            layout.addWidget(msg)
            dialog.show()
            QApplication.processEvents()
        except Exception:
            dialog = None  # Qt no disponible, seguir sin cartel

        try:
            # Una sola escena — se sobrescribe acumulando cada paso
            filename = "3Dosim.mrb"
            scene_dir = getattr(self, "scene_output_dir", None)
            if not scene_dir:
                scene_dir = os.path.join(self.output_dir, "scenes")
            filepath = os.path.join(scene_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            t0 = time.time()
            logger.info(f"  Escena{' ['+tag+']' if tag else ''} -> {filepath}")
            logger.info(f"  Guardando escena (puede tomar hasta 2 min si la escena es grande)...")
            old_tmp = os.environ.get("TMP", "")
            old_temp = os.environ.get("TEMP", "")
            try:
                short_tmp = r"C:\tmp"
                os.makedirs(short_tmp, exist_ok=True)
                os.environ["TMP"] = short_tmp
                os.environ["TEMP"] = short_tmp
                success = slicer.util.saveScene(filepath)
            finally:
                os.environ["TMP"] = old_tmp
                os.environ["TEMP"] = old_temp
            elapsed = time.time() - t0
            if success:
                new_size = os.path.getsize(filepath)
                logger.info(f"  Escena guardada ({elapsed:.0f}s): {os.path.basename(filepath)} ({new_size/1024/1024:.0f} MB)")
                return filepath
            else:
                logger.warning(f"  saveScene devolvio False ({elapsed:.0f}s)")
                return None
        except Exception as e:
            logger.warning(f"No se pudo guardar escena '{tag}': {e}")
            return None
        finally:
            if dialog is not None:
                try:
                    dialog.close()
                    dialog.deleteLater()
                    from qt import QApplication
                    QApplication.processEvents()
                except Exception:
                    pass

    def _tomar_screenshot(self, nombre):
        """Toma screenshot de toda la ventana de Slicer."""
        try:
            import slicer
            from datetime import datetime
            ts = datetime.now().strftime("%H%M%S")
            shot_dir = os.path.join(self.output_dir, "screenshots")
            os.makedirs(shot_dir, exist_ok=True)
            filepath = os.path.join(shot_dir, f"{ts}_{nombre}.png")
            mw = slicer.util.mainWindow()
            if mw:
                pixmap = mw.grab()
                pixmap.save(filepath)
                logger.info(f"  Screenshot: {os.path.basename(filepath)}")
                return filepath
        except Exception as e:
            logger.warning(f"No se pudo tomar screenshot '{nombre}': {e}")
            return None

    def _save_results_json(self):
        """Guarda resultados en JSON (historial acumulado)."""
        results_file = os.path.join(self.output_dir, "pipeline_results.json")
        historial = []
        if os.path.exists(results_file):
            try:
                with open(results_file, "r") as f:
                    historial = json.load(f)
                    if not isinstance(historial, list):
                        historial = [historial]
            except (json.JSONDecodeError, Exception):
                historial = []
        total = len(self.results["pasos"])
        ok_count = sum(1 for p in self.results["pasos"] if p["ok"])
        fails = total - ok_count
        registro = {
            "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
            "modulo": "Mod3",
            "scene_path": self.scene_path,
            "mctal_path": self.mctal_path,
            "activity_gbq": self.activity_gbq,
            "output_dir": self.output_dir,
            "flip": self.flip,
            "total_pasos": total,
            "exitosos": ok_count,
            "fallos": fails,
            "resultado": "OK" if fails == 0 else "ERROR",
            "pasos": self.results["pasos"],
            "errores": self.results["errores"],
            "estructuras": {
                name: {
                    "mean_dose_gy": s.get("mean_dose_gy", 0),
                    "bed_gy": s.get("bed_gy", 0),
                }
                for name, s in self.results_data.get("structures", {}).items()
            },
        }
        historial.append(registro)
        with open(results_file, "w") as f:
            json.dump(historial, f, indent=2, default=str)
        logger.info(f"  Resultados guardados en: {results_file}")

    def _report(self) -> bool:
        """Genera reporte final."""
        try:
            self._save_results_json()
        except Exception as e:
            logger.warning(f"No se pudo guardar results.json: {e}")
        logger.info("")
        logger.info("=" * 70)
        logger.info(" REPORTE FINAL - MODULO 3")
        logger.info("=" * 70)
        total = len(self.results["pasos"])
        ok_count = sum(1 for p in self.results["pasos"] if p["ok"])
        fails = total - ok_count
        skipped = sum(1 for p in self.results["pasos"] if p.get("checkpoint"))
        logger.info(f"  Pasos totales:     {total}")
        logger.info(f"  Exitosos:          {ok_count}")
        logger.info(f"  Desde checkpoint:  {skipped}")
        logger.info(f"  Fallos:            {fails}")
        if fails > 0:
            logger.info("  ERRORES:")
            for err in self.results["errores"]:
                logger.info(f"    - {err}")
        logger.info("  DETALLE DE PASOS:")
        logger.info("-" * 70)
        for paso in self.results["pasos"]:
            status = "+" if paso["ok"] else "-"
            cp = " (checkpoint)" if paso.get("checkpoint") else ""
            tiempo = f"{paso['tiempo']:.1f}s" if paso['tiempo'] > 0 else "-"
            logger.info(f"  {status} {paso['nombre']:<45s} {tiempo:>8s}{cp}")
        logger.info("")
        if self.results_data.get("structures"):
            logger.info("  DOSIMETRIA POR ESTRUCTURA:")
            for name, s in self.results_data["structures"].items():
                logger.info(f"    {name}: Dmedia={s.get('mean_dose_gy', 0):.2f} Gy, "
                           f"BED={s.get('bed_gy', 0):.2f} Gy")
        logger.info(f"  Output: {self.output_dir}")
        if self.pdf_path:
            logger.info(f"  PDF:    {self.pdf_path}")
        all_ok = fails == 0
        if all_ok:
            logger.info("  RESULTADO: TODOS LOS PASOS EXITOSOS")
        else:
            logger.info(f"  RESULTADO: {fails}/{total} PASOS FALLARON")
        logger.info("=" * 70)
        return all_ok

    # ==================================================================
    # LOGGING A CONSOLA
    # ==================================================================

    def _log_consola(self, mensaje: str):
        if self.consola:
            self.consola.log(mensaje)

    def _log_consola_ok(self, mensaje: str):
        if self.consola:
            self.consola.log_ok(mensaje)

    def _log_consola_error(self, mensaje: str):
        if self.consola:
            self.consola.log_error(mensaje)

    # ==================================================================
    # STEP METHODS
    # ==================================================================

    # ── 1. Cargar escena ──

    def _load_scene(self):
        """Carga escena .mrb en Slicer."""
        import slicer

        if not os.path.exists(self.scene_path):
            raise FileNotFoundError(f"Escena no encontrada: {self.scene_path}")

        size_mb = os.path.getsize(self.scene_path) / (1024 * 1024)
        logger.info(f"  Escena: {self.scene_path} ({size_mb:.0f} MB)")

        with track_time("Cargando escena"):
            success = load_scene(self.scene_path)
            import slicer
            slicer.app.processEvents()
            if not success:
                raise RuntimeError(f"No se pudo cargar escena: {self.scene_path}")

        logger.info("  Escena cargada exitosamente")

    # ── 2. Buscar nodos ──

    def _find_and_prepare_nodes(self):
        """Busca CT, PET, Labelmap en la escena cargada."""
        import slicer

        nodes = find_nodes(labelmap_name="3Dosim_labelmap")

        if nodes.get("ct"):
            self.ct_node = nodes["ct"]
            logger.info(f"  CT: '{self.ct_node.GetName()}'")
        else:
            raise RuntimeError("No se encontro nodo CT en la escena")

        if nodes.get("pet"):
            self.pet_node = nodes["pet"]
            logger.info(f"  PET: '{self.pet_node.GetName()}'")
        else:
            self.pet_node = None
            logger.info("  PET: No encontrado (se requiere --activity)")

        # Labelmap: primero buscar en escena, luego en NIfTI
        labelmap_from_scene = nodes.get("labelmap")
        if labelmap_from_scene:
            self.labelmap_node = labelmap_from_scene
            logger.info(f"  Labelmap: '{self.labelmap_node.GetName()}' (desde escena)")
        elif os.path.exists(self.labelmap_path):
            logger.info(f"  Cargando labelmap desde NIfTI: {self.labelmap_path}")
            labelmap_node = slicer.util.loadVolume(self.labelmap_path)
            if labelmap_node:
                self.labelmap_node = labelmap_node
                logger.info(f"  Labelmap: '{self.labelmap_node.GetName()}' (desde NIfTI)")
            else:
                raise RuntimeError(f"No se pudo cargar labelmap NIfTI: {self.labelmap_path}")
        else:
            # Buscar segmentacion como fallback
            seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
            if seg_nodes:
                self.segmentation_node = seg_nodes[0]
                logger.info(f"  Segmentacion: '{self.segmentation_node.GetName()}' (fallback)")
                # No hay labelmap array disponible, continuar con datos limitados
                logger.warning("  No hay labelmap numerico. MIRD y DVH no estaran disponibles.")
            else:
                raise RuntimeError("No se encontro labelmap ni segmentacion")

        # Extraer labelmap array
        if self.labelmap_node:
            self.labelmap_array = self._get_labelmap_array(self.labelmap_node)
            self.dims = self.labelmap_array.shape  # (nx, ny, nz)
            self.spacing = self.labelmap_node.GetSpacing()
            logger.info(f"  Labelmap shape: {self.dims}")
            logger.info(f"  Spacing: {self.spacing}")
            logger.info(f"  Indices unicos: {np.unique(self.labelmap_array)}")
        else:
            # Sin labelmap: usar dimensiones del CT
            if self.ct_node:
                img = self.ct_node.GetImageData()
                if img:
                    self.dims = (img.GetDimensions()[0], img.GetDimensions()[1], img.GetDimensions()[2])
                else:
                    self.dims = (512, 512, 171)
            self.spacing = (1.0, 1.0, 1.0)

    @staticmethod
    def _get_labelmap_array(labelmap_node):
        """Extrae array 3D del labelmap, transpone a (nx, ny, nz)."""
        import slicer
        arr = slicer.util.arrayFromVolume(labelmap_node)  # (nz, ny, nx)
        arr = arr.transpose(2, 1, 0).astype(np.int32)    # (nx, ny, nz)
        return arr

    # ── 3. Actividad ──

    def _compute_activity(self):
        """Computa actividad total desde PET o usa valor ingresado."""
        if self.activity_gbq_input is not None:
            self.activity_gbq = float(self.activity_gbq_input)
            self.activity_bq = self.activity_gbq * 1e9
            logger.info(f"  Actividad (input): {self.activity_gbq:.4f} GBq")
            return

        if self.pet_node is None:
            raise RuntimeError("No hay PET y no se especifico --activity")

        activity_bq = compute_activity_from_pet(self.pet_node)
        self.activity_bq = float(activity_bq)
        self.activity_gbq = self.activity_bq / 1e9

        logger.info(f"  Actividad: {self.activity_bq:.2e} Bq = {self.activity_gbq:.4f} GBq")

    # ── 4. Parsear MCTAL ──

    def _parse_mctal(self):
        """Parsea archivo MCTAL usando MCTALParser."""
        if not os.path.exists(self.mctal_path):
            raise FileNotFoundError(f"MCTAL no encontrado: {self.mctal_path}")

        size_mb = os.path.getsize(self.mctal_path) / (1024 * 1024)
        logger.info(f"  MCTAL: {self.mctal_path} ({size_mb:.0f} MB)")

        nx, ny, nz = self.dims
        mctal_result = parse_mctal(self.mctal_path, (nx, ny, nz))

        self.dose_mev_cm3 = mctal_result["dose_3d"]
        self.error_3d = mctal_result.get("uncertainty", np.zeros_like(self.dose_mev_cm3))
        self._mctal_nps = mctal_result.get("nps", 0)

        logger.info(f"  Dose shape: {self.dose_mev_cm3.shape}")
        logger.info(f"  NPS: {self._mctal_nps:,}")

        # Aplicar flip Y si corresponde (compatibilidad MATLAB)
        if self.flip:
            self.dose_mev_cm3 = self.dose_mev_cm3[:, ::-1, :].copy()
            self.error_3d = self.error_3d[:, ::-1, :].copy()
            logger.info("  Flip Y aplicado a dosis MCTAL")

    # ── 5. Convertir a Gy ──

    def _convert_to_gy(self):
        """Convierte MeV/cm3/particula a Gy."""
        if self.dose_mev_cm3 is None:
            raise RuntimeError("No hay datos de dosis MCTAL para convertir")

        t_meanlife_s = Y90_HALF_LIFE_H * 3600 / np.log(2)  # ~332,753 s

        if self.labelmap_array is not None:
            self.dose_gy = convert_to_gy(
                self.dose_mev_cm3, self.labelmap_array,
                self.activity_bq, t_meanlife_s,
            )
        else:
            # Sin labelmap: densidad uniforme
            self.dose_gy = self.dose_mev_cm3 * MEV2J * t_meanlife_s * self.activity_bq * 1000

        # Aplicar filtro de error (MATLAB cargo_mctal.m:375-379)
        error_eliminar = 1.5
        bad_voxels = self.error_3d >= error_eliminar
        self.dose_gy[bad_voxels] = 0
        self._n_bad_voxels = int(np.sum(bad_voxels))

        # Eliminar dosis negativas
        neg_mask = self.dose_gy < 0
        self._n_neg_voxels = int(np.sum(neg_mask))
        self.dose_gy[neg_mask] = 0

        # Estadisticas
        positive = self.dose_gy > 0
        n_pos = int(np.sum(positive))
        logger.info(f"  Voxels eliminados por error>={error_eliminar}: {self._n_bad_voxels}")
        logger.info(f"  Voxels con dosis negativa: {self._n_neg_voxels}")
        logger.info(f"  Dosis en Gy: media={np.mean(self.dose_gy[positive]) if np.any(positive) else 0:.2f}, "
                    f"max={np.max(self.dose_gy):.2f}, n_pos={n_pos}")

    # ── 6. DVH por estructura ──

    def _compute_dvh(self):
        """Computa DVH y radiobiologia para higado, tumor, pretumor."""
        if self.dose_gy is None or self.labelmap_array is None:
            raise RuntimeError("Dosis Gy o labelmap no disponibles para DVH")

        structures_def = {
            "higado": {"idx": LIVER_INDEX, "alpha_beta": ALPHA_BETA_LIVER, "is_tumor": False},
            "tumor": {"idx": TUMOR_INDEX, "alpha_beta": ALPHA_BETA_TUMOR, "is_tumor": True},
            "pretumor": {"idx": PRETUMOR_INDEX, "alpha_beta": ALPHA_BETA_LIVER, "is_tumor": False},
        }

        spacing = self.spacing
        struct_labels_pdf = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}
        dvh_colors_pdf = {
            "higado": (0.2, 0.4, 1.0),
            "tumor": (1.0, 0.2, 0.2),
            "pretumor": (0.8, 0.6, 0.0),
        }

        self.results_data["structures"] = {}
        self.dvh_curves_for_pdf = []

        for name, info in structures_def.items():
            idx = info["idx"]
            mask = self.labelmap_array == idx
            n_vox = int(np.sum(mask))

            if n_vox == 0:
                logger.info(f"  {name} ({idx}): sin voxeles, saltando")
                continue

            # DVH
            dvh = compute_dvh(self.dose_gy, self.labelmap_array, idx)
            logger.info(f"  {name} ({idx}): {dvh['n_voxels']} voxels, "
                        f"Dmedia={dvh['mean_dose_gy']:.2f} Gy")

            # Radiobiologia
            bio = compute_biophysical(dvh, info["alpha_beta"], info["is_tumor"])
            logger.info(f"    BED={bio['bed_gy']:.2f} Gy, EUD={bio['eud_gy']:.2f} Gy")

            volume_cm3 = n_vox * spacing[0] * spacing[1] * spacing[2] / 1000.0

            self.results_data["structures"][name] = {
                "index": idx,
                "n_voxels": dvh["n_voxels"],
                "volume_cm3": volume_cm3,
                "mean_dose_gy": dvh["mean_dose_gy"],
                "min_dose_gy": dvh["min_dose_gy"],
                "max_dose_gy": dvh["max_dose_gy"],
                "max_dose_pos_ijk": dvh["max_dose_pos_ijk"],
                "std_dose_gy": dvh["std_dose_gy"],
                "d98_gy": dvh["d98_gy"],
                "d95_gy": dvh["d95_gy"],
                "d70_gy": dvh["d70_gy"],
                "d50_gy": dvh["d50_gy"],
                "d5_gy": dvh["d5_gy"],
                "d2_gy": dvh["d2_gy"],
                "v30_pct": dvh["v30_pct"],
                "v70_pct": dvh["v70_pct"],
                "bed_gy": bio["bed_gy"],
                "eud_gy": bio["eud_gy"],
                "eqd2_gy": bio["eqd2_gy"],
                "dose_bins_gy": dvh.get("dose_bins_gy", []),
                "cumulative_vol_pct": dvh.get("cumulative_vol_pct", []),
                "volume_hist_pct": dvh.get("volume_hist_pct", []),
            }

            # Curva DVH para PDF
            doses = self.dose_gy[mask]
            n_doses = len(doses)
            if n_doses > 0 and np.max(doses) > 0:
                Dmax = float(np.max(doses))
                delta = Dmax / 1000.0
                d_vals = np.arange(0, Dmax + delta, delta)
                a_vals = np.zeros(len(d_vals))
                for i, d in enumerate(d_vals):
                    a_vals[i] = np.sum(doses >= d) * 100.0 / n_doses
                pdf_label = struct_labels_pdf.get(name, name)
                self.dvh_curves_for_pdf.append((pdf_label, d_vals, a_vals))

    # ── 7. MIRD ──

    def _compute_mird(self):
        """Calcula MIRD partition model."""
        if self.dose_gy is None or self.labelmap_array is None:
            raise RuntimeError("Dosis Gy o labelmap no disponibles para MIRD")

        mird = compute_mird(self.dose_gy, self.labelmap_array, self.activity_gbq)
        self.results_data["mird"] = mird

        logger.info(f"  Hígado:       {mird['liver']['mean_dose_gy']:.2f} Gy")
        logger.info(f"  Tumor:        {mird['tumor']['mean_dose_gy']:.2f} Gy")
        logger.info(f"  Peritumoral:  {mird['pretumor']['mean_dose_gy']:.2f} Gy")

    # ── Helpers para reporte LaTeX ──

    def _build_structure_list_for_latex(self):
        """Convierte results_data['structures'] al formato esperado por generate_latex_report."""
        struct_labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}
        result = []
        for name, s in self.results_data.get("structures", {}).items():
            result.append({
                "label": struct_labels.get(name, name),
                "n_voxels": s.get("n_voxels", 0),
                "volume_cm3": s.get("volume_cm3", 0),
                "mean_dose_gy": s.get("mean_dose_gy", 0),
                "d98_gy": s.get("d98_gy", 0),
                "d95_gy": s.get("d95_gy", 0),
                "d70_gy": s.get("d70_gy", 0),
                "d50_gy": s.get("d50_gy", 0),
                "d5_gy": s.get("d5_gy", 0),
                "d2_gy": s.get("d2_gy", 0),
                "bed_gy": s.get("bed_gy", 0),
                "eud_gy": s.get("eud_gy", 0),
                "eqd2_gy": s.get("eqd2_gy", 0),
            })
        return result

    def _build_mird_list_for_latex(self):
        """Convierte results_data['mird'] al formato esperado por generate_latex_report."""
        mird_labels = {"liver": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}
        result = []
        for name, m in self.results_data.get("mird", {}).items():
            result.append({
                "label": mird_labels.get(name, name),
                "n_voxels": m.get("n_voxels", 0),
                "mean_dose_gy": m.get("mean_dose_gy", 0),
            })
        if not result:
            # placeholder si no hay datos MIRD
            result = [
                {"label": "Hígado", "n_voxels": 0, "mean_dose_gy": 0},
                {"label": "Tumor", "n_voxels": 0, "mean_dose_gy": 0},
            ]
        return result

    @property
    def _alpha_beta_rows(self):
        """Tabla alpha/beta para reporte LaTeX."""
        return [
            {"label": "Hígado sano", "value": ALPHA_BETA_LIVER, "type": "Tardío"},
            {"label": "Tumor", "value": ALPHA_BETA_TUMOR, "type": "Agudo"},
        ]

    @property
    def _density_rows(self):
        """Tabla densidades para reporte LaTeX."""
        return [
            {"material": "Hígado", "density": DENSIDAD_LIVER, "use": "Parénquima hepático"},
            {"material": "Tumor", "density": DENSIDAD_TUMOR, "use": "Lesión tumoral"},
            {"material": "Tejido blando", "density": DENSIDAD_BODY, "use": "Fondo corporal"},
            {"material": "Aire", "density": DENSIDAD_AIR, "use": "Aire / pulmón"},
        ]

    # ── 8. Exportar reporte ──

    def _export_report(self):
        """Exporta reporte JSON + TXT + PDF."""
        # Determinar método de dosis
        mctal_lower = (self.mctal_path or "").lower()
        if "kernel" in mctal_lower or mctal_lower.endswith(".mat"):
            dose_method = "Kernel"
            dose_file = os.path.basename(self.mctal_path) if self.mctal_path else "kernel.mat"
        else:
            dose_method = "MCTALL"
            dose_file = os.path.basename(self.mctal_path) if self.mctal_path else ""

        # Metadata
        self.results_data["metadata"] = {
            "scene": self.scene_path,
            "mctal": self.mctal_path,
            "dose_method": dose_method,
            "dose_file": dose_file,
            "activity_bq": self.activity_bq,
            "activity_gbq": self.activity_gbq,
            "dimensions": list(self.dims),
            "nps": int(getattr(self, '_mctal_nps', 0)),
            "flip": self.flip,
        }

        # Información de fusión CT+PET (se llena si está disponible)
        if "fusion" not in self.results_data:
            ct_spacing = list(self.spacing) if hasattr(self, 'spacing') and self.spacing else []
            _dims = list(self.dims) if hasattr(self, 'dims') and self.dims else []
            self.results_data["fusion"] = {
                "ct_dim_x": _dims[0] if len(_dims) > 0 else 0,
                "ct_dim_y": _dims[1] if len(_dims) > 1 else 0,
                "ct_dim_z": _dims[2] if len(_dims) > 2 else 0,
                "ct_spacing_x": float(ct_spacing[0]) if len(ct_spacing) >= 1 else 0.0,
                "ct_spacing_y": float(ct_spacing[1]) if len(ct_spacing) >= 2 else 0.0,
                "ct_spacing_z": float(ct_spacing[2]) if len(ct_spacing) >= 3 else 0.0,
                "pet_dim_x": 0, "pet_dim_y": 0, "pet_dim_z": 0,
                "pet_spacing_x": 0.0, "pet_spacing_y": 0.0, "pet_spacing_z": 0.0,
                "registration_method": "BRAINS Resample (desde pipeline Mod1)",
                "registration_conserved": True,
                "total_gbq": self.activity_gbq,
            }

        # JSON
        report_path = os.path.join(self.output_dir, "dosimetria_report.json")
        with open(report_path, "w") as f:
            json.dump(self.results_data, f, indent=2, default=str)
        self._report_json_path = report_path
        logger.info(f"  Reporte JSON: {report_path}")

        # TXT
        report_txt_path = os.path.join(self.output_dir, "dosimetria_report.txt")
        with open(report_txt_path, "w") as f:
            f.write("=" * 60 + "\n")
            f.write(" REPORTE DE DOSIMETRIA 3Dosim\n")
            f.write("=" * 60 + "\n\n")
            meta = self.results_data.get("metadata", {})
            f.write(f"Escena:    {meta.get('scene', 'N/A')}\n")
            f.write(f"MCTAL:     {meta.get('mctal', 'N/A')}\n")
            f.write(f"Actividad: {meta.get('activity_gbq', 0):.4f} GBq\n")
            f.write(f"NPS:       {meta.get('nps', 0):,}\n")
            f.write(f"Dimensiones: {meta.get('dimensions', [])}\n\n")

            f.write("-" * 50 + "\n")
            f.write(" RESULTADOS POR ESTRUCTURA\n")
            f.write("-" * 50 + "\n\n")
            for name, s in self.results_data.get("structures", {}).items():
                f.write(f"  {name.upper()} (indice={s['index']}):\n")
                f.write(f"    Voxeles:     {s['n_voxels']}\n")
                f.write(f"    Dosis media: {s['mean_dose_gy']:.2f} Gy\n")
                f.write(f"    Dosis max:   {s['max_dose_gy']:.2f} Gy\n")
                pos = s.get('max_dose_pos_ijk')
                if pos:
                    f.write(f"    Pos max (IJK): i={pos[0]}, j={pos[1]}, k={pos[2]}\n")
                f.write(f"    D98:         {s['d98_gy']:.2f} Gy\n")
                f.write(f"    D95:         {s['d95_gy']:.2f} Gy\n")
                f.write(f"    D70:         {s['d70_gy']:.2f} Gy\n")
                f.write(f"    D50:         {s['d50_gy']:.2f} Gy\n")
                f.write(f"    D5:          {s['d5_gy']:.2f} Gy\n")
                f.write(f"    D2:          {s['d2_gy']:.2f} Gy\n")
                f.write(f"    V30:         {s['v30_pct']:.1f} %\n")
                f.write(f"    V70:         {s['v70_pct']:.1f} %\n")
                f.write(f"    BED:         {s['bed_gy']:.2f} Gy\n")
                f.write(f"    EUD:         {s['eud_gy']:.2f} Gy\n")
                f.write(f"    EQD2:        {s['eqd2_gy']:.2f} Gy\n\n")

            f.write("-" * 50 + "\n")
            f.write(" MIRD PARTITION MODEL\n")
            f.write("-" * 50 + "\n\n")
            mird = self.results_data.get("mird", {})
            f.write(f"  Actividad: {meta.get('activity_gbq', 0):.4f} GBq\n")
            f.write(f"  Higado:    {mird.get('liver', {}).get('mean_dose_gy', 0):.2f} Gy\n")
            f.write(f"  Tumor:     {mird.get('tumor', {}).get('mean_dose_gy', 0):.2f} Gy\n")
            f.write(f"  Peritumoral: {mird.get('pretumor', {}).get('mean_dose_gy', 0):.2f} Gy\n")
        self._report_txt_path = report_txt_path
        logger.info(f"  Reporte TXT: {report_txt_path}")

        # PDF (legacy)
        try:
            pdf_path = generate_pdf_report(
                self.results_data,
                AI_PIPE_DIR,
                self.dvh_curves_for_pdf,
            )
            if pdf_path:
                self.pdf_path = pdf_path
                logger.info(f"  Reporte PDF (legacy): {pdf_path}")
            else:
                logger.warning("  generate_pdf_report devolvio None")
        except Exception as e:
            logger.warning(f"  Error generando PDF legacy: {e}")
            import traceback
            logger.warning(traceback.format_exc())

        # PDF (LaTeX - nuevo)
        try:
            # generate_latex_report recibe el dict results_data completo
            latex_pdf_path = generate_latex_report(
                results_data=self.results_data,
                output_dir=self.output_dir,
                patient_id=self.patient_id or "Desconocido",
                dvh_curves=self.dvh_curves_for_pdf if self.dvh_curves_for_pdf else None,
            )
            if latex_pdf_path:
                logger.info(f"  Reporte PDF (LaTeX): {latex_pdf_path}")
            else:
                logger.warning("  generate_latex_report devolvio None")
        except Exception as e:
            logger.warning(f"  Error generando PDF LaTeX: {e}")
            import traceback
            logger.warning(traceback.format_exc())

    # ── 9. Nodo de dosis 3D ──

    def _create_dose_node(self):
        """Crea nodo de dosis 3D en Slicer y activa overlay."""
        import slicer

        if self.dose_gy is None:
            raise RuntimeError("No hay datos de dosis para crear nodo 3D")

        # Usar labelmap o CT como referencia espacial
        ref_node = self.labelmap_node or self.ct_node
        if ref_node is None:
            raise RuntimeError("No hay nodo de referencia para crear volumen de dosis")

        from SlicerDosim.SlicerDosimLib.dosimetry import DoseCalculator

        calc = DoseCalculator()
        dose_node = calc.create_dose_volume(self.dose_gy, ref_node)

        if dose_node is None:
            raise RuntimeError("create_dose_volume devolvio None")

        self.dose_node = dose_node
        logger.info(f"  Nodo de dosis creado: '{dose_node.GetName()}'")

        # Mostrar dosis como overlay en slices
        try:
            ct_for_bg = self.ct_node
            slice_nodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
            for sn in slice_nodes:
                if ct_for_bg:
                    sn.SetBackgroundVolumeID(ct_for_bg.GetID())
                sn.SetForegroundVolumeID(dose_node.GetID())
                sn.SetForegroundOpacity(0.5)
            slicer.util.setSliceViewerLayers(foreground=dose_node, foregroundOpacity=0.5)
            logger.info("  Overlay de dosis activado en slices")
        except Exception as e:
            logger.warning(f"  Error activando overlay: {e}")

    # ── 10. DVH en Slicer + guardar escena ──

    def _create_dvh_and_save(self):
        """Crea graficos DVH en Slicer y guarda escena final."""
        import slicer

        if self.dose_gy is not None and self.labelmap_array is not None:
            try:
                _create_dvh_plots_slicer(
                    self.dose_gy, self.labelmap_array, self.spacing, show_gui=True,
                )
                logger.info("  DVH graficado en Slicer")
            except Exception as e:
                logger.warning(f"  Error creando DVH plots: {e}")
        else:
            logger.warning("  DVH no disponible (sin labelmap o dosis)")

        # Guardar escena final
        scene_out = os.path.join(self.output_dir, "3Dosim_dosis_scene.mrb")
        try:
            old_tmp = os.environ.get("TMP", "")
            old_temp = os.environ.get("TEMP", "")
            try:
                short_tmp = r"C:\tmp"
                os.makedirs(short_tmp, exist_ok=True)
                os.environ["TMP"] = short_tmp
                os.environ["TEMP"] = short_tmp
                success = slicer.util.saveScene(scene_out)
            finally:
                os.environ["TMP"] = old_tmp
                os.environ["TEMP"] = old_temp

            if success:
                logger.info(f"  Escena final guardada: {scene_out}")
        except Exception as e:
            logger.warning(f"  No se pudo guardar escena final: {e}")

        # Mostrar Plots module
        try:
            slicer.util.selectModule("Plots")
            slicer.app.processEvents()
        except Exception:
            pass

        # Resumen en consola
        self._log_consola("=" * 50)
        self._log_consola("PIPELINE MODULO 3 COMPLETADO")
        self._log_consola(f"  Actividad: {self.activity_gbq:.4f} GBq")
        for name, s in self.results_data.get("structures", {}).items():
            label = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}.get(name, name)
            self._log_consola(f"  {label}: Dmedia={s.get('mean_dose_gy', 0):.2f} Gy, "
                             f"BED={s.get('bed_gy', 0):.2f} Gy")
        if self.pdf_path:
            self._log_consola(f"  PDF: {os.path.basename(self.pdf_path)}")
        self._log_consola("=" * 50)

    # ==================================================================
    # AUTO-DETECT
    # ==================================================================

    @staticmethod
    def _auto_detect_scene():
        """Auto-detecta la escena .mrb mas reciente."""
        candidates = [
            r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim_scene.mrb",
            r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim.mrb",
            r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim_mod1_scene.mrb",
            r"C:\MAT\3Dosim\pacientes-\pacientes\resultados_test\scenes\3Dosim.mrb",
        ]
        newest = None
        newest_time = 0
        for c in candidates:
            if os.path.exists(c):
                mtime = os.path.getmtime(c)
                if mtime > newest_time:
                    newest = c
                    newest_time = mtime
        if newest:
            logger.info(f"  Escena auto-detectada: {newest}")
        else:
            logger.warning("  No se pudo auto-detectar escena .mrb")
        return newest


# ======================================================================
# CLI entry point (para ejecucion directa)
# ======================================================================

def main():
    """Entry point CLI para PipelineMod3."""
    # ── Logging global: captura TODO a archivo ──
    try:
        from PipelineOrchestrator.logging_setup import setup_global_logging
        setup_global_logging()
    except Exception as _e:
        print(f"[3Dosim] No se pudo iniciar logging global: {_e}")

    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline Mod3 - Analisis Dosimetrico desde escena + MCTAL"
    )
    parser.add_argument("--scene", default=None, help="Ruta al archivo .mrb")
    parser.add_argument("--mctal", default=None, help="Ruta al archivo MCTAL")
    parser.add_argument("--labelmap", default=None, help="Ruta a labelmap NIfTI")
    parser.add_argument("--activity", type=float, default=None,
                        help="Actividad en GBq (default: computar del PET)")
    parser.add_argument("--output", default=None, help="Directorio de salida")
    parser.add_argument("--reset", action="store_true", help="Reiniciar checkpoints")
    parser.add_argument("--flip", action="store_true", default=True,
                        help="Aplicar flip Y a dosis MCTAL (default: True)")
    parser.add_argument("--no-flip", action="store_false", dest="flip",
                        help="No aplicar flip Y a dosis MCTAL")
    parser.add_argument("--no-consola", action="store_true",
                        help="Deshabilita la consola interactiva")
    args, _ = parser.parse_known_args()

    # Agregar paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(script_dir)  # Testing/
    if parent not in sys.path:
        sys.path.insert(0, parent)

    pipeline = PipelineMod3(
        scene_path=args.scene,
        mctal_path=args.mctal,
        labelmap_path=args.labelmap,
        activity_gbq=args.activity,
        output_dir=args.output,
        reset=args.reset,
        flip=args.flip,
        no_consola=args.no_consola,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
