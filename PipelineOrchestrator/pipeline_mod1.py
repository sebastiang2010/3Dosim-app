"""
PipelineMod1 - Modulo 1: Carga, segmentacion y tumor.
Flujo completo hasta exportacion de labelmap dosimetrica.

NO incluye generacion MCNP (eso es Mod2).
NO incluye analisis dosimetrico (eso es Mod3).

Todos los imports son absolutos para compatibilidad con Slicer --python-script.
"""

import logging
import os
import time

from PipelineOrchestrator.checkpoint import CheckpointManager
from PipelineOrchestrator import anonymize
from PipelineOrchestrator import couch_remover
from PipelineOrchestrator import segmentation
from PipelineOrchestrator import validation
from PipelineOrchestrator import tumor_creator
from PipelineOrchestrator import tumor_validation
from PipelineOrchestrator import labelmap_exporter
from PipelineOrchestrator import git_commit
from PipelineOrchestrator import ai_supervisor
from PipelineOrchestrator.utils import logger, add_module_path, show_progress
from PipelineOrchestrator.mcp_helper import MCP
from PipelineOrchestrator.comandos import ConsolaComandos
from PipelineOrchestrator.views import setup_medical_views, load_pipeline_config

logger = logging.getLogger("3DosimMod1")


class PipelineMod1:
    """
    Pipeline Modulo 1: carga PET/CT, segmentacion anatomica (TotalSegmentator),
    creacion de tumor (3 modos), validacion medica, y exportacion de labelmap.
    """

    STEP_CHECK_SLICER  = "check_slicer"
    STEP_LOAD_DICOM    = "load_dicom"
    STEP_SHOW_FUSION   = "show_fusion"
    STEP_ANONYMIZE     = "anonymize"
    STEP_EXPORT_DICOM_INFO = "export_dicom_info"
    STEP_REMOVE_COUCH  = "remove_couch_air"
    STEP_RESAMPLE_PET  = "resample_pet_to_ct"
    STEP_SEGMENT       = "segment_phantom"
    STEP_VALIDATE_AUTO = "validate_segmentation_auto"
    STEP_VALIDATE      = "validate_segmentation"
    STEP_ADD_TUMOR     = "add_synthetic_tumor"
    STEP_VALIDATE_TUMOR = "validate_tumor"
    STEP_HEALTHY_LIVER  = "create_healthy_liver"
    STEP_SEGMENT_BODY   = "segment_body"
    STEP_EXPORT_LABELMAP = "export_labelmap"

    def __init__(self, data_dir: str, reset: bool = False, mcp_port: int = 0,
                 no_consola: bool = False, segmenter: str = "totalsegmentator",
                 stop_before_segment: bool = False, force_cpu: bool = True,
                 patient_id: str = None):
        self.data_dir = data_dir
        self.patient_id = patient_id or ""
        self.ct_dir = os.path.join(data_dir, "CT")
        self.pet_dir = os.path.join(data_dir, "PET")
        self.output_dir = os.path.join(data_dir, "..", "resultados_test")
        self.checkpoint_dir = os.path.join(self.output_dir, ".checkpoints")
        self.anon_dir = os.path.join(self.output_dir, ".anon")
        self.labelmap_dir = os.path.join(self.output_dir, "labelmaps")

        self.results = {"pasos": [], "errores": [], "tiempos": {}}

        self.checkpoint = CheckpointManager(self.checkpoint_dir)
        if reset:
            self.checkpoint.reset()

        # Nodos Slicer
        self.ct_node = None
        self.ct_masked_node = None
        self.pet_node = None
        self.segmentation_node = None
        self.body_node = None
        self.phantom_nifti_path = None
        self.ct_node_name = None
        self.pet_node_name = None
        self.pet_activity = None

        # MCP
        self.mcp = MCP()
        self.mcp_server = None
        self.mcp_port = mcp_port
        self.screenshots = []

        # Segmentacion
        self.segmenter = segmenter
        logger.info(f"  Segmentador:    {segmenter}")
        self.force_cpu = force_cpu
        logger.info(f"  Force CPU:      {force_cpu}")
        self.stop_before_segment = stop_before_segment
        if stop_before_segment:
            logger.info("  Modo:           STOP antes de segmentacion (manual)")

        # Consola
        self.no_consola = no_consola
        self.pipeline_config = load_pipeline_config()
        self.scene_output_dir = self.pipeline_config.get(
            "scene_output_dir",
            os.path.join(self.output_dir, "scenes"),
        )
        logger.info(f"  Scene output dir:  {self.scene_output_dir}")
        self.screenshot_output_dir = self.pipeline_config.get(
            "screenshot_output_dir",
            os.path.join(self.output_dir, "screenshots"),
        )
        logger.info(f"  Screenshot dir:    {self.screenshot_output_dir}")
        self.image_output_dir = self.pipeline_config.get(
            "image_output_dir",
            os.path.join(self.output_dir, "imagenes"),
        )
        logger.info(f"  Image output dir:  {self.image_output_dir}")

        # Config del tumor
        self.tumor_config = self.pipeline_config.get("tumor", {})
        tumor_mode = self.tumor_config.get("mode", "synthetic")
        logger.info(f"  Tumor mode:     {tumor_mode}")
        if tumor_mode == "load_file":
            logger.info(f"  Tumor file:     {self.tumor_config.get('load_file_path', '')}")
        elif tumor_mode == "manual":
            logger.info(f"  Tumor segment:  {self.tumor_config.get('manual_segment_name', 'Tumor_Manual')}")
        elif tumor_mode == "ts_liver_lesions":
            logger.info(f"  TS segment:     {self.tumor_config.get('ts_liver_lesions_segment_name', 'Tumor_TS')}")
            logger.info(f"  Min volume:     {self.tumor_config.get('ts_liver_lesions_min_volume_cc', 1.0)} cc")

        self.consola = None
        if not no_consola:
            try:
                self.consola = ConsolaComandos(output_dir=self.output_dir)
            except Exception as e:
                logger.debug(f"Consola no disponible: {e}")
                self.consola = None

        logger.info("=" * 60)
        logger.info(" 3Dosim Pipeline Modulo 1 — Carga, Segmentacion, Tumor")
        logger.info("=" * 60)
        logger.info(f"Datos:        {self.data_dir}")
        logger.info(f"Output:       {self.output_dir}")
        logger.info(f"Checkpoints:  {self.checkpoint_dir}")
        logger.info(f"Reset:        {'SI' if reset else 'NO (retoma checkpoints)'}")
        logger.info(f"Consola:      {'SI' if not no_consola else 'NO'}")
        logger.info("")

    # ==================================================================
    # RUN
    # ==================================================================

    def run(self):
        logger.info("")
        logger.info("INICIANDO PIPELINE MODULO 1")
        logger.info("")

        if self.consola:
            self.consola.log("=" * 50)
            self.consola.log(" 3Dosim Mod1 - Consola de Comandos")
            self.consola.log(" Escribi 'ayuda' para comandos disponibles")
            self.consola.log("=" * 50)
            self.consola.log("")
            self.consola.mostrar()

        self._log_consola("Iniciando modulo 1...")

        # Cargar escena guardada si existe
        self._load_scene_if_needed()
        if getattr(self, 'segmentation_node', None):
            self._show_segmentation_3d(self.segmentation_node)

        if self._checkpoint_step(self.STEP_CHECK_SLICER, "Verificando entorno Slicer",
                                 self._check_slicer,
                                 data_func=lambda: {"slicer_version": self._slicer_version()}):
            add_module_path()

        if not self._checkpoint_step(self.STEP_LOAD_DICOM, "Cargando imagenes DICOM",
                                      self._load_dicom,
                                      data_func=lambda: {"ct_node_name": self.ct_node.GetName() if self.ct_node else None,
                                                         "pet_node_name": self.pet_node.GetName() if self.pet_node else None,
                                                         "ct_dir": self.ct_dir, "pet_dir": self.pet_dir}):
            logger.error("Fallo critico en carga DICOM. Abortando.")
            self._report()
            return

        self._save_scene("01_post_load_dicom")
        self.tomar_screenshot("01_carga_dicom")
        setup_medical_views(
            ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )

        if not self._checkpoint_step(self.STEP_REMOVE_COUCH, "Eliminando camilla y aire",
                                      self._remove_couch_air,
                                      data_func=lambda: {"ct_node_name": self.ct_node.GetName() if self.ct_node else None,
                                                         "ct_masked_node_name": self.ct_masked_node.GetName() if self.ct_masked_node else None}):
            logger.warning("No se pudo eliminar camilla, continuando...")
        self._save_scene("02_remove_couch")
        self.tomar_screenshot("02_remove_couch")

        # Resample PET
        if not self._checkpoint_step(self.STEP_RESAMPLE_PET, "Re-muestreando PET a geometria CT",
                                      self._resample_pet_to_ct,
                                      data_func=lambda: {"pet_resampled": self.pet_node is not None}):
            logger.warning("Re-muestreo PET fallo, continuando con PET original...")
        self._save_scene("03_pet_resampled")
        self.tomar_screenshot("03_pet_resampled")
        setup_medical_views(
            ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )

        if not self._checkpoint_step(self.STEP_SHOW_FUSION, "Mostrando fusion CT+PET registrada",
                                      self._show_fusion):
            logger.warning("No se pudo mostrar fusion, continuando de todos modos")
        self._save_scene("04_fusion_ct_pet_registrada")
        self.tomar_screenshot("04_fusion_ct_pet_registrada")

        if not self._checkpoint_step(self.STEP_ANONYMIZE, "Anonimizando imagenes",
                                      self._anonymize,
                                      data_func=lambda: {"ct_node_name": self.ct_node.GetName() if self.ct_node else None,
                                                         "pet_node_name": self.pet_node.GetName() if self.pet_node else None}):
            logger.warning("Anonimizacion fallo, continuando...")
        self._save_scene("05_anonymize")
        self.tomar_screenshot("05_anonymize")

        # Exportar metadata DICOM a JSON (despues de anonimizar)
        if not self._checkpoint_step(self.STEP_EXPORT_DICOM_INFO, "Exportando metadata DICOM a JSON",
                                      self._export_dicom_info_json):
            logger.warning("Export de metadata DICOM fallo, continuando...")

        # Stop before segment
        if self.stop_before_segment:
            self._stop_before_segment_handler()
            return

        # Segmentacion
        seg_display = f"Segmentando ({self.segmenter})"
        if self.segmenter == "totalsegmentator":
            self._log_consola("Iniciando TotalSegmentator modo rapido (5-15 min)")
        else:
            self._log_consola("Iniciando segmentacion simple (threshold + morfologia)")
        seg_ok = self._checkpoint_step(self.STEP_SEGMENT, seg_display,
                                       self._segment,
                                       data_func=lambda: {"segmentation_node_name": self.segmentation_node.GetName() if self.segmentation_node else None,
                                                          "segmenter": self.segmenter})
        if not seg_ok:
            logger.error("SEGMENTACION FALLIDA. El pipeline no puede continuar.")
            self._log_consola("ERROR: Segmentacion fallida. Pipeline detenido.")
            self._report()
            return

        self._save_scene("08_segmentacion")
        self.tomar_screenshot("08_segmentacion")
        setup_medical_views(
            ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node, segmentation_node=self.segmentation_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )
        self._show_segmentation_3d(self.segmentation_node)

        # Autovalidacion
        if not self._checkpoint_step(self.STEP_VALIDATE_AUTO, "Autochequeo de segmentos",
                                      self._validate_segmentation_auto,
                                      data_func=lambda: {"segmenter": self.segmenter}):
            if self.segmenter == "simple":
                logger.warning("Segmentacion SIMPLE solo genera mascara corporal.")
            else:
                logger.warning("Autovalidacion: faltan segmentos esperados.")

        # Validacion medica
        self._log_consola("Esperando validacion medica de la segmentacion...")
        if not self._checkpoint_step(self.STEP_VALIDATE + "_seg", "Validacion medica de la segmentacion",
                                      lambda: self._do_validation(context="segmentacion"),
                                      data_func=lambda: {"validado_por": "medico", "contexto": "segmentacion",
                                                         "timestamp": __import__('datetime').datetime.now().isoformat()}):
            logger.error("Validacion medica rechazada. Pipeline detenido.")
            self._log_consola("Validacion medica RECHAZADA. Pipeline detenido.")
            self._report()
            return

        self._save_scene("08_post_validacion_segmentacion")
        self.tomar_screenshot("08_validacion_segmentacion")
        setup_medical_views(
            ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node, segmentation_node=self.segmentation_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )

        # Tumor (segun config)
        tumor_mode = self.tumor_config.get("mode", "synthetic")
        mode_labels = {
            "synthetic": "Tumor sintetico esferico en higado",
            "load_file": "Cargar tumor desde archivo NIfTI",
            "manual": "Segmentacion manual del tumor en Slicer",
            "ts_liver_lesions": "Segmentacion automatica (TS liver_lesions)",
        }
        step_label = mode_labels.get(tumor_mode, f"Tumor (modo: {tumor_mode})")
        self._log_consola(f"Creando tumor (modo: {tumor_mode})...")
        if not self._checkpoint_step(self.STEP_ADD_TUMOR, step_label,
                                      self._add_tumor,
                                      data_func=lambda: {"mode": tumor_mode, "config": self.tumor_config}):
            logger.error("Creacion de tumor FALLO — abortando pipeline")
            self._log_consola_error("Creacion de tumor FALLO — abortando")
            raise RuntimeError(f"No se pudo crear el tumor (modo={tumor_mode})")
        scene_tag = {"synthetic": "09_tumor_sintetico", "load_file": "09_tumor_cargado",
                     "manual": "09_tumor_manual",
                     "ts_liver_lesions": "09_tumor_automatico"}.get(tumor_mode, "09_tumor")
        self._save_scene(scene_tag)
        self.tomar_screenshot(scene_tag)
        setup_medical_views(
            ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node, segmentation_node=self.segmentation_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )

        # Higado sano
        create_healthy = self.tumor_config.get("create_healthy_liver", True)
        if create_healthy:
            self._log_consola("Verificando higado sano = higado - tumor...")
            if not self._checkpoint_step(self.STEP_HEALTHY_LIVER, "Higado sano (higado - tumor)",
                                          self._create_healthy_liver,
                                          data_func=lambda: {"created": True}):
                logger.warning("Verificacion de higado sano fallo, continuando...")
            self._save_scene("10_higado_sano")
            self.tomar_screenshot("10_higado_sano")

        # Validacion medica del tumor
        self._log_consola("Esperando validacion medica del tumor...")
        if not self._checkpoint_step(self.STEP_VALIDATE_TUMOR, "Validacion medica del tumor",
                                      lambda: self._validate_tumor(context=tumor_mode),
                                      data_func=lambda: {"context": tumor_mode,
                                                         "timestamp": __import__('datetime').datetime.now().isoformat()}):
            logger.error("Validacion tumoral rechazada. Pipeline detenido.")
            self._log_consola("Validacion tumoral RECHAZADA. Pipeline detenido.")
            self._report()
            return
        self._save_scene("11_validacion_tumor")
        self.tomar_screenshot("11_validacion_tumor")

        # Segmentacion corporal (body)
        self._log_consola("Segmentando contorno corporal con TotalSegmentator (task='body')...")
        if not self._checkpoint_step(self.STEP_SEGMENT_BODY, "Segmentacion corporal (body)",
                                      self._segment_body,
                                      data_func=lambda: {"task": "body", "fast": True, "force_cpu": True}):
            logger.warning("Segmentacion corporal fallo, continuando sin body...")
        self._save_scene("12_segment_body")
        self.tomar_screenshot("12_segment_body")

        # Exportar labelmap (NIfTI + NRRD ya van a disco)
        # NOTA: NO se guarda escena ni screenshot post-labelmap porque
        # el nodo 3Dosim_Labelmap (89MB) dentro del MRB cuelga Slicer.
        self._log_consola("Exportando labelmap dosimetrica con IDs de tissue_config...")
        if not self._checkpoint_step(self.STEP_EXPORT_LABELMAP, "Exportar labelmap dosimetrica",
                                      self._export_labelmap,
                                      data_func=lambda: {"output_dir": self.labelmap_dir}):
            logger.warning("Exportacion de labelmap fallo, continuando...")

        # Pipeline Mod1 completado
        logger.info("")
        logger.info("  PIPELINE MODULO 1 COMPLETADO")
        logger.info("")
        logger.info("  Flujo ejecutado:")
        logger.info("    1. Carga DICOM")
        logger.info("    2. Eliminar camilla/aire")
        logger.info("    3. Re-muestreo PET")
        logger.info("    4. Fusion CT+PET")
        logger.info("    5. Anonimizar")
        logger.info("    6. TotalSegmentator (task=total)")
        logger.info("    7. Validacion segmentacion")
        logger.info(f"    8. Tumor (modo: {tumor_mode})")
        logger.info("    9. Validacion medica del tumor")
        if create_healthy:
            logger.info("   10. Higado sano = higado - tumor")
        logger.info("   11. TotalSegmentator (task=body)")
        logger.info("   12. Exportar labelmap dosimetrica")
        logger.info("")
        logger.info("  Siguiente paso:")
        logger.info("    Modulo 2: pipeline_mod2.py para generar entrada MCNP")
        logger.info("    Modulo 3: analisis dosimetrico desde output MCNP")
        logger.info("")

        self._log_consola("Modulo 1 completado. Generando reporte...")
        ok = self._report()
        if ok:
            self._log_consola("Modulo 1 finalizado EXITOSAMENTE")
        else:
            self._log_consola("Modulo 1 finalizado con ERRORES. Revise el reporte.")

    # ==================================================================
    # METODOS INTERNOS (extraidos de pipeline.py)
    # ==================================================================

    def _checkpoint_step(self, step_name, display_name, func, data_func=None):
        if self.checkpoint.is_completed(step_name):
            logger.info(f"  [{'...'}]: ya completado (checkpoint salta)")
            self.results["pasos"].append({
                "nombre": display_name, "ok": True, "tiempo": 0, "checkpoint": True
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
                "nombre": display_name, "ok": True, "tiempo": elapsed
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
                "nombre": display_name, "ok": False, "tiempo": elapsed
            })
            self.results["errores"].append(f"{display_name}: {e}")
            show_progress(f"FALLO: {display_name}")
            self._log_consola_error(f"{display_name} — FALLO: {e}")
            self._ai_review_paso(display_name, ok=False, elapsed=elapsed,
                                 step_name=step_name, error=str(e))
            return False

    def _ai_review_paso(self, display_name, ok, elapsed, step_name, data=None, error=None):
        try:
            ctx = {
                "paso": display_name, "ok": ok, "tiempo": elapsed,
                "datos": data or {}, "errores": [error] if error else [],
            }
            nodos_info = {}
            if self.ct_node:
                nodos_info["CT"] = self.ct_node.GetName()
            if self.pet_node:
                nodos_info["PET"] = self.pet_node.GetName()
            if self.segmentation_node:
                nodos_info["Segmentacion"] = self.segmentation_node.GetName()
                try:
                    seg_metrics = self._extract_segmentation_metrics()
                    if seg_metrics:
                        ctx["datos"]["segmentation_metrics"] = seg_metrics
                except Exception:
                    pass
            ctx["datos"]["segmenter_type"] = getattr(self, "segmenter", "desconocido")
            ctx["datos"]["nodos_activos"] = nodos_info
            ai_supervisor.revisar_paso(ctx, consola=self.consola)
        except Exception as e:
            logger.debug(f"AI review no disponible: {e}")

    def _extract_segmentation_metrics(self) -> dict:
        metrics = {}
        try:
            import slicer
            import vtk
            seg_node = self.segmentation_node
            if not seg_node:
                return metrics
            seg_display = seg_node.GetDisplayNode()
            if not seg_display:
                return metrics
            seg_collection = seg_node.GetSegmentation()
            if not seg_collection:
                return metrics
            segment_ids = vtk.vtkStringArray()
            seg_collection.GetSegmentIDs(segment_ids)
            num_segments = segment_ids.GetNumberOfValues()
            metrics["num_segments"] = num_segments
            names = []
            for i in range(num_segments):
                seg_id = segment_ids.GetValue(i)
                segment = seg_collection.GetSegment(seg_id)
                if segment:
                    names.append(segment.GetName())
            metrics["segment_names"] = names
            try:
                labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLLabelMapVolumeNode", "_tmp_metrics")
                success = slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                    seg_node, labelmap_node, seg_display.GetReferenceImageGeometryNode(),
                    segment_ids, 1, labelmap_node.GetName())
                if success and labelmap_node.GetImageData():
                    import numpy as np
                    arr = slicer.util.arrayFromVolume(labelmap_node)
                    spacing = labelmap_node.GetSpacing()
                    voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
                    total_voxels = np.count_nonzero(arr)
                    metrics["volume_cc"] = round(total_voxels * voxel_vol_cc, 1)
                    if self.ct_masked_node:
                        ct_arr = slicer.util.arrayFromVolume(self.ct_masked_node)
                        fuera_cuerpo = np.count_nonzero((arr > 0) & (ct_arr <= -200))
                        metrics["voxels_fuera_cuerpo"] = int(fuera_cuerpo)
                slicer.mrmlScene.RemoveNode(labelmap_node)
            except Exception:
                pass
            warnings = []
            if num_segments <= 2:
                warnings.append(
                    f"Solo {num_segments} segmento(s). "
                    "Un cuerpo completo deberia tener ~104 organos."
                )
            if metrics.get("voxels_fuera_cuerpo", 0) > 1000:
                warnings.append(
                    f"{metrics['voxels_fuera_cuerpo']} voxels segmentados fuera del contorno corporal."
                )
            metrics["warnings"] = warnings
        except Exception as e:
            logger.debug(f"Error extrayendo metricas: {e}")
        return metrics

    def _restore_step_state(self, step_name, data):
        if not data:
            return
        import slicer
        restore_map = {
            "ct_node": "ct_node", "pet_node": "pet_node",
            "segmentation_node": "segmentation_node",
            "ct_node_name": "ct_node_name", "pet_node_name": "pet_node_name",
            "ct_masked_node_name": "ct_masked_node_name",
        }
        for data_key, attr_name in restore_map.items():
            if data_key in data and data[data_key] is not None:
                if data_key.endswith("_name"):
                    try:
                        node = slicer.util.getNode(data[data_key])
                        actual_attr = data_key.replace("_name", "_node")
                        if hasattr(self, actual_attr):
                            setattr(self, actual_attr, node)
                    except Exception:
                        self._restore_node_by_type(data_key, data[data_key])
                else:
                    setattr(self, attr_name, data[data_key])
        if self.ct_node or self.pet_node:
            try:
                setup_medical_views(
                    ct_node=self.ct_node, ct_masked_node=self.ct_masked_node,
                    pet_node=self.pet_node, segmentation_node=self.segmentation_node,
                    layout_name=self.pipeline_config.get("views", {}).get("layout", "ConventionalView"),
                    pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
                    link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
                )
            except Exception as e:
                logger.debug(f"No se pudo restaurar visualizacion: {e}")

    def _restore_node_by_type(self, data_key, node_name):
        import slicer
        type_map = {
            "ct_node": "vtkMRMLScalarVolumeNode",
            "pet_node": "vtkMRMLScalarVolumeNode",
            "segmentation_node": "vtkMRMLSegmentationNode",
            "ct_node_name": "vtkMRMLScalarVolumeNode",
            "pet_node_name": "vtkMRMLScalarVolumeNode",
            "ct_masked_node_name": "vtkMRMLScalarVolumeNode",
        }
        node_type = type_map.get(data_key, "vtkMRMLScalarVolumeNode")
        nodes = slicer.util.getNodesByClass(node_type)
        if not nodes:
            logger.warning(f"  No se encontraron nodos de tipo {node_type}")
            return
        if len(nodes) == 1:
            chosen = nodes[0]
        else:
            keywords = {"ct": "CT", "pet": "PET", "seg": "Seg", "masked": "sin_camilla"}
            key = "ct"
            if "pet" in data_key:
                key = "pet"
            elif "seg" in data_key:
                key = "seg"
            elif "masked" in data_key:
                key = "masked"
            kw = keywords.get(key, key)
            candidates = [n for n in nodes if kw in n.GetName()]
            chosen = candidates[0] if candidates else nodes[0]
        attr = data_key.replace("_name", "_node") if data_key.endswith("_name") else data_key
        if hasattr(self, attr):
            setattr(self, attr, chosen)
            logger.info(f"  Nodo restaurado: '{chosen.GetName()}' -> self.{attr}")

    # ==================================================================
    # HELPER METHODS
    # ==================================================================

    def _slicer_version(self) -> str:
        try:
            import slicer
            return f"{slicer.app.majorVersion}.{slicer.app.minorVersion}"
        except ImportError:
            return "desconocido"

    def _check_slicer(self):
        try:
            import slicer
            logger.info(f"  Slicer version: {self._slicer_version()}")
            self._mcp_start()
        except ImportError:
            raise RuntimeError("No se detecta 3D Slicer. Ejecutar dentro de Slicer.")

    def _mcp_start(self):
        mcp_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "slicer-mcp-server.py"
        )
        if os.path.exists(mcp_script):
            logger.info(f"  Iniciando MCP server desde: {mcp_script}")
            try:
                with open(mcp_script) as f:
                    code = f.read()
                import slicer
                exec(compile(code, mcp_script, 'exec'),
                     {"__name__": "__mcp_server__", "slicer": slicer})
                logger.info("  MCP server listo")
            except Exception as e:
                logger.warning(f"No se pudo iniciar MCP local: {e}")
        else:
            logger.info("  MCP server no disponible (slicer-mcp-server.py no encontrado)")

    def _log_consola(self, mensaje):
        if self.consola:
            self.consola.log(mensaje)

    def _log_consola_ok(self, mensaje):
        if self.consola:
            self.consola.log_ok(mensaje)

    def _log_consola_error(self, mensaje):
        if self.consola:
            self.consola.log_error(mensaje)

    def tomar_screenshot(self, nombre, view="full"):
        try:
            import slicer
            from datetime import datetime
            ts = datetime.now().strftime("%H%M%S")
            filename = f"{ts}_{nombre}.png"
            shot_dir = getattr(self, "screenshot_output_dir", None) or \
                       os.path.join(self.output_dir, "screenshots")
            filepath = os.path.join(shot_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            pixmap = None
            if view == "full":
                mw = slicer.util.mainWindow()
                if mw:
                    pixmap = mw.grab()
            elif view == "3D":
                lm = slicer.app.layoutManager()
                if lm:
                    w = lm.threeDWidget(0)
                    if w:
                        pixmap = w.threeDView().grab()
            elif view in ("Red", "Yellow", "Green"):
                lm = slicer.app.layoutManager()
                if lm:
                    sw = lm.sliceWidget(view.upper())
                    if sw:
                        pixmap = sw.sliceView().grab()
            if pixmap is None:
                return None
            pixmap.save(filepath)
            self.screenshots.append(filepath)
            logger.info(f"  Screenshot: {os.path.basename(filepath)}")
            return filepath
        except Exception as e:
            logger.warning(f"No se pudo tomar screenshot '{nombre}': {e}")
            return None

    def _load_scene_if_needed(self):
        import slicer
        scene_path = os.path.join(self.scene_output_dir, "3Dosim.mrb")
        if not os.path.exists(scene_path):
            return
        checkpoint_keys = [
            self.STEP_LOAD_DICOM, self.STEP_REMOVE_COUCH,
            self.STEP_RESAMPLE_PET, self.STEP_SEGMENT,
        ]
        needs_restore = any(self.checkpoint.is_completed(k) for k in checkpoint_keys)
        if not needs_restore:
            return
        logger.info(f"  Cargando escena guardada: {scene_path}")
        try:
            success = slicer.util.loadScene(scene_path)
            if success:
                logger.info("  Escena cargada OK desde checkpoint")
        except Exception as e:
            logger.warning(f"No se pudo cargar escena: {e}")
        self._scan_scene_for_nodes()

    def _scan_scene_for_nodes(self):
        import slicer
        import vtk
        vol_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        seg_nodes_list = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        logger.info(f"  Escaneando: {len(vol_nodes)} volumenes, {len(seg_nodes_list)} segmentaciones")
        ct_candidates = [n for n in vol_nodes if "CT" in n.GetName() or "ct" in n.GetName().lower()]
        if ct_candidates and not getattr(self, 'ct_node', None):
            self.ct_node = ct_candidates[0]
        masked = [n for n in vol_nodes if "sin_camilla" in n.GetName().lower() or "masked" in n.GetName().lower()]
        if not masked:
            masked = ct_candidates
        if masked and not getattr(self, 'ct_masked_node', None):
            self.ct_masked_node = masked[0]
        pet_candidates = [n for n in vol_nodes if "PET" in n.GetName() or "pet" in n.GetName().lower()]
        if pet_candidates and not getattr(self, 'pet_node', None):
            self.pet_node = pet_candidates[0]
        if seg_nodes_list and not getattr(self, 'segmentation_node', None):
            ts_nodes = [n for n in seg_nodes_list if "TotalSegmentator" in n.GetName()]
            self.segmentation_node = ts_nodes[0] if ts_nodes else seg_nodes_list[0]
            seg_ids = vtk.vtkStringArray()
            self.segmentation_node.GetSegmentation().GetSegmentIDs(seg_ids)
            logger.info(f"  Segmentos: {seg_ids.GetNumberOfValues()}")
        body_candidates = [n for n in seg_nodes_list if "Body" in n.GetName()]
        if body_candidates and not getattr(self, 'body_node', None):
            self.body_node = body_candidates[0]

    def _show_segmentation_3d(self, seg_node=None):
        import slicer
        import vtk
        seg_node = seg_node or getattr(self, 'segmentation_node', None)
        if not seg_node:
            return
        seg_ids = vtk.vtkStringArray()
        seg_node.GetSegmentation().GetSegmentIDs(seg_ids)
        n = seg_ids.GetNumberOfValues()
        logger.info(f"  Modelos 3D para {n} segmentos...")
        try:
            seg_node.CreateClosedSurfaceRepresentation()
            disp_node = seg_node.GetDisplayNode()
            if disp_node:
                try:
                    disp_node.SetAllSegmentsVisible(True)
                except AttributeError:
                    pass
        except Exception as e:
            logger.warning(f"No se pudo generar representacion 3D: {e}")

    def _save_scene(self, tag=None):
        try:
            import slicer
            # Una sola escena — se sobrescribe acumulando cada paso
            filename = "3Dosim.mrb"
            scene_dir = getattr(self, "scene_output_dir", None)
            if not scene_dir:
                scene_dir = os.path.join(self.output_dir, "scenes")
            filepath = os.path.join(scene_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            logger.info(f"  Escena{' ['+tag+']' if tag else ''} -> {filepath}")
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
            if success:
                logger.info(f"  Escena guardada: {os.path.basename(filepath)}")
                return filepath
        except Exception as e:
            logger.warning(f"No se pudo guardar escena '{tag}': {e}")
            return None

    def _stop_before_segment_handler(self):
        logger.info("")
        logger.info("=" * 60)
        logger.info(" PIPELINE DETENIDO ANTES DE SEGMENTACION")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Pasos completados:")
        logger.info("  1. check_slicer")
        logger.info("  2. load_dicom")
        logger.info("  3. remove_couch_air")
        logger.info("  4. resample_pet")
        logger.info("  5. show_fusion")
        logger.info("  6. anonymize")
        logger.info("")
        logger.info("Para correr TotalSegmentator manual:")
        logger.info("  from TotalSegmentator import TotalSegmentatorLogic")
        logger.info("  seg_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode')")
        logger.info("  logic = TotalSegmentatorLogic()")
        logger.info("  logic.setupPythonRequirements()")
        logger.info("  logic.process(inputVolume=ct_node, outputSegmentation=seg_node,")
        logger.info("                fast=True, cpu=True, task='total')")
        logger.info("")
        logger.info("Para retomar: ejecutar sin --reset")
        logger.info("=" * 60)
        self._save_scene("07_pre_segmentacion_manual")
        self._log_consola("Pipeline detenido antes de segmentacion (modo manual)")
        self._report()

    # ==================================================================
    # STEP METHODS
    # ==================================================================

    def _load_dicom(self):
        import slicer
        from DICOMLib import DICOMUtils
        for d in [self.ct_dir, self.pet_dir]:
            if not os.path.isdir(d):
                raise FileNotFoundError(f"Directorio no encontrado: {d}")
        original_db_dir = DICOMUtils.openTemporaryDatabase()
        try:
            for dir_path, label in [(self.ct_dir, "CT"), (self.pet_dir, "PET")]:
                logger.info(f"  Indexando {label}...")
                ok = DICOMUtils.importDicom(dir_path)
                if not ok:
                    raise RuntimeError(f"Fallo indexacion {label}")
            series_uids = DICOMUtils.allSeriesUIDsInDatabase()
            if not series_uids:
                raise RuntimeError("No se encontraron series DICOM")
            loaded_node_ids = DICOMUtils.loadSeriesByUID(series_uids)
        except Exception as e:
            DICOMUtils.closeTemporaryDatabase(original_db_dir, cleanup=True)
            raise RuntimeError(f"Error cargando DICOM: {e}")
        DICOMUtils.closeTemporaryDatabase(original_db_dir, cleanup=True)
        loaded_ct, loaded_pet = False, False
        for node_id in loaded_node_ids:
            node = slicer.mrmlScene.GetNodeByID(node_id)
            if not node:
                continue
            name = node.GetName().upper()
            if "CT" in name and not loaded_ct:
                self.ct_node = node
                loaded_ct = True
            elif ("PET" in name or "PT" in name or "NM" in name) and not loaded_pet:
                self.pet_node = node
                loaded_pet = True
        if not loaded_ct:
            for node_id in loaded_node_ids:
                node = slicer.mrmlScene.GetNodeByID(node_id)
                if node:
                    self.ct_node = node
                    loaded_ct = True
                    break
        if not loaded_pet and len(loaded_node_ids) > 1:
            for node_id in loaded_node_ids:
                node = slicer.mrmlScene.GetNodeByID(node_id)
                if node and node != self.ct_node:
                    self.pet_node = node
                    loaded_pet = True
                    break
        if not loaded_ct:
            raise RuntimeError("No se pudo cargar CT desde DICOM")
        if not loaded_pet:
            logger.warning("  PET no identificado")
        dims = self.ct_node.GetImageData().GetDimensions()
        spacing = self.ct_node.GetSpacing()
        logger.info(f"  CT: {dims[0]}x{dims[1]}x{dims[2]}, {spacing[0]:.3f}x{spacing[1]:.3f}x{spacing[2]:.3f} mm")

    def _read_dicom_patient_id(self) -> str:
        """Lee el PatientID real desde los archivos DICOM con pydicom.

        Prueba primero PET, luego CT. Retorna '' si no se puede leer.
        """
        for directory in [self.pet_dir, self.ct_dir]:
            if not directory or not os.path.isdir(directory):
                continue
            try:
                import pydicom
                for fname in sorted(os.listdir(directory)):
                    fpath = os.path.join(directory, fname)
                    if not os.path.isfile(fpath):
                        continue
                    try:
                        ds = pydicom.dcmread(fpath, stop_before_pixels=True, force=True)
                        pid = getattr(ds, "PatientID", None)
                        if pid is not None:
                            val = str(pid.val if hasattr(pid, "val") else pid)
                            if val.strip():
                                logger.info(f"  PatientID real desde DICOM: {val}")
                                return val.strip()
                    except Exception:
                        continue
            except ImportError:
                logger.debug("  pydicom no disponible para leer PatientID")
                break
            except Exception:
                continue
        return ""

    def _show_fusion(self):
        import slicer
        lm = slicer.app.layoutManager()
        if lm is None:
            logger.warning("  No hay layout manager. Saltando config visual.")
            return
        lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        bg_node = self.ct_masked_node if self.ct_masked_node else self.ct_node
        if not self.pet_node:
            slicer.util.setSliceViewerLayers(background=bg_node)
        else:
            pet_dn = self.pet_node.GetDisplayNode()
            if not pet_dn:
                from slicer import vtkMRMLScalarVolumeDisplayNode
                pet_dn = vtkMRMLScalarVolumeDisplayNode()
                slicer.mrmlScene.AddNode(pet_dn)
                pet_dn.SetDefaultColorMap()
                self.pet_node.SetAndObserveDisplayNodeID(pet_dn.GetID())
            # Rainbow estandar: azul=bajo, rojo=alto (intuitivo para PET)
            pet_dn.SetAndObserveColorNodeID("vtkMRMLColorTableNodeRainbow")
            pet_dn.AutoWindowLevelOff()
            pet_dn.SetWindowLevel(40.0, 20.0)
            pet_dn.SetApplyThreshold(False)  # Sin threshold
            slicer.util.setSliceViewerLayers(
                background=bg_node, foreground=self.pet_node, foregroundOpacity=0.35)
            bg_dn = bg_node.GetDisplayNode()
            if bg_dn:
                bg_dn.AutoWindowLevelOff()
                bg_dn.SetWindowLevel(400.0, 40.0)
        slicer.app.processEvents()
        slicer.util.resetSliceViews()
        slicer.app.processEvents()

        # ── 2. Leer actividad PET desde DICOM raw ──
        if self.pet_node and os.path.isdir(self.pet_dir):
            try:
                from PipelineOrchestrator.pet_dicom_reader import read_pet_dicom_activity
                logger.info("  Leyendo actividad PET desde DICOM raw (replicando f_Rescale_Bq.m)...")
                pet_activity = read_pet_dicom_activity(self.pet_dir)
                self.pet_activity = pet_activity
                total_bq = pet_activity.get("total_bq", 0)
                total_gbq = pet_activity.get("total_gbq", 0)
                logger.info(f"  Actividad PET: {total_bq:.4e} Bq  ({total_gbq:.4f} GBq)")
                if pet_activity.get("error"):
                    logger.warning(f"  Error lectura PET: {pet_activity['error']}")
                for w in pet_activity.get("warnings", []):
                    logger.warning(f"  Advertencia PET: {w}")
            except Exception as e:
                logger.warning(f"  No se pudo leer actividad PET desde DICOM: {e}")
                self.pet_activity = None
        else:
            logger.info("  No hay PET o directorio PET, saltando lectura de actividad")
            self.pet_activity = None

        # ── 3. Mostrar dialogo informativo MODAL (bloquea hasta cerrar) ──
        try:
            from PipelineOrchestrator.fusion_dialog import show_fusion_info_dialog
            ct_dims = self.ct_node.GetImageData().GetDimensions() if self.ct_node else None
            ct_spacing = self.ct_node.GetSpacing() if self.ct_node else None
            pet_dims = self.pet_node.GetImageData().GetDimensions() if self.pet_node else None
            pet_spacing = self.pet_node.GetSpacing() if self.pet_node else None
            # Extraer ID: CLI > DICOM (via pydicom) > extraer numero del directorio
            pid = self.patient_id
            if not pid:
                # Leer PatientID real desde archivos DICOM con pydicom
                pid = self._read_dicom_patient_id()
            if not pid:
                # Intentar extraer numero del nombre del directorio: "Paciente_2" → "2"
                dir_name = os.path.basename(os.path.normpath(self.data_dir))
                import re
                m = re.search(r'(\d+)', dir_name)
                pid = m.group(1) if m else dir_name
            patient_id = pid
            show_fusion_info_dialog(
                pet_activity=self.pet_activity or {},
                ct_dims=ct_dims,
                ct_spacing=ct_spacing,
                ct_slices=ct_dims[2] if ct_dims else 0,
                pet_dims=pet_dims,
                pet_spacing=pet_spacing,
                pet_slices_loaded=pet_dims[2] if pet_dims else 0,
                ct_node_name=self.ct_node.GetName() if self.ct_node else "",
                pet_node_name=self.pet_node.GetName() if self.pet_node else "",
                patient_id=patient_id,
                patient_weight_kg=self.pipeline_config.get("patient_weight_kg"),
                registration_method="Elastix rigid",
                registration_conserved=True,
            )
            logger.info("  Dialogo informativo de fusion cerrado por el usuario (modal)")
        except Exception as e:
            logger.warning(f"  No se pudo mostrar dialogo de fusion: {e}")

    def _anonymize(self):
        anonymize.anonymize(self.ct_node, self.ct_dir, self.pet_dir, self.anon_dir, self.pet_node)

    def _export_dicom_info_json(self):
        """
        Extrae metadata DICOM de CT y PET (nombre, ID, fechas, etc.)
        y la guarda como JSON en exports/ para la base de datos.
        Similar al info_PET / info_CT del paciente.mat de Matlab.
        """
        import json
        try:
            import slicer
        except Exception:
            logger.warning("slicer no disponible, no se puede exportar metadata DICOM")
            return
        info = {"CT": {}, "PET": {}}
        # Intentar extraer desde la base DICOM de Slicer via atributos de nodo
        for modality, node, directory in [
            ("CT", self.ct_node, self.ct_dir),
            ("PET", self.pet_node, self.pet_dir)
        ]:
            if node is None:
                continue
            # Obtener UID de serie desde atributos del nodo
            series_uid = node.GetAttribute("DICOM.seriesInstanceUID") or ""
            study_uid = node.GetAttribute("DICOM.studyInstanceUID") or ""
            info[modality]["SeriesInstanceUID"] = series_uid
            info[modality]["StudyInstanceUID"] = study_uid
            info[modality]["Modality"] = modality
            # Nombre del nodo (ya anonimizado por _anonymize)
            info[modality]["NodeName"] = node.GetName()
            # Leer tags desde los archivos DICOM originales con pydicom
            dicom_tags = {}
            if os.path.isdir(directory):
                try:
                    import pydicom
                    for fname in sorted(os.listdir(directory)):
                        fpath = os.path.join(directory, fname)
                        if not os.path.isfile(fpath):
                            continue
                        try:
                            ds = pydicom.dcmread(fpath, stop_before_pixels=True, force=True)
                            for tag_name in [
                                "PatientName", "PatientID", "PatientBirthDate",
                                "PatientSex", "StudyDate", "StudyTime",
                                "StudyDescription", "StudyInstanceUID",
                                "SeriesDescription", "SeriesInstanceUID",
                                "SeriesDate", "SeriesTime",
                                "Modality", "Manufacturer", "InstitutionName",
                                "ManufacturerModelName", "DeviceSerialNumber",
                                "ReferringPhysicianName", "OperatorsName",
                                "AccessionNumber", "PatientAge", "PatientWeight",
                                "NumberOfSeriesRelatedInstances",
                                "Rows", "Columns", "SliceThickness",
                                "PixelSpacing", "SpacingBetweenSlices",
                                "RescaleIntercept", "RescaleSlope",
                            ]:
                                if hasattr(ds, tag_name) and getattr(ds, tag_name) is not None:
                                    val = getattr(ds, tag_name)
                                    if hasattr(val, "repval"):
                                        val = val.repval
                                    else:
                                        val = str(val)
                                    dicom_tags[tag_name] = val
                            break  # solo leer el primer archivo de la serie
                        except Exception:
                            continue
                except ImportError:
                    logger.debug(f"  pydicom no disponible para {modality}, usando solo atributos Slicer")
                except Exception as e:
                    logger.debug(f"  Error leyendo DICOM {modality}: {e}")
            info[modality]["DICOM"] = dicom_tags
        # Guardar JSON — usar PatientID real de DICOM si esta disponible
        export_dir = getattr(self, "image_output_dir", None)
        if not export_dir:
            export_dir = os.path.join(self.output_dir, "exports")
        os.makedirs(export_dir, exist_ok=True)
        dicom_patient_id = (
            info.get("CT", {}).get("DICOM", {}).get("PatientID") or
            info.get("PET", {}).get("DICOM", {}).get("PatientID") or
            ""
        )
        pid = dicom_patient_id or self.patient_id.strip() or "unknown"
        json_path = os.path.join(export_dir, f"{pid}_info.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
        logger.info(f"  Metadata DICOM exportada -> {json_path}")

    def _resample_pet_to_ct(self):
        try:
            import slicer
        except Exception as e:
            logger.error(f"Error importando slicer: {e}")
            return
        if not self.pet_node or not self.ct_node:
            logger.warning("PET o CT no disponible, saltando re-muestreo")
            return
        ct_dims = self.ct_node.GetImageData().GetDimensions()
        ct_spacing = self.ct_node.GetSpacing()
        pet_dims = self.pet_node.GetImageData().GetDimensions()
        pet_spacing = self.pet_node.GetSpacing()
        if (ct_dims == pet_dims and
            abs(ct_spacing[0] - pet_spacing[0]) < 0.001 and
            abs(ct_spacing[1] - pet_spacing[1]) < 0.001 and
            abs(ct_spacing[2] - pet_spacing[2]) < 0.001):
            logger.info("PET ya tiene la misma geometria que CT")
            return
        try:
            from SlicerDosim.SlicerDosimLib import registration
            pet_resampled_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeNode", self.pet_node.GetName() + "_resampled_to_CT")
            reg = registration.DosimetryRegistration()
            registered_pet = reg.register(
                fixed_node=self.ct_node, moving_node=self.pet_node,
                method=registration.DosimetryRegistration.METHOD_ELASTIX_RIGID,
                output_volume_node=pet_resampled_node)
            if registered_pet is None or registered_pet.GetImageData() is None:
                raise RuntimeError("Registro Elastix fallo")
            registered_pet.SetName(self.pet_node.GetName())
            old_pet = self.pet_node
            self.pet_node = registered_pet
            slicer.mrmlScene.RemoveNode(old_pet)
            logger.info("PET re-muestreado a geometria CT: EXITOSO")
        except Exception as e:
            logger.error(f"Error en re-muestreo PET: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.warning("Continuando con PET original")

    def _remove_couch_air(self):
        masked_node = couch_remover.remove_couch_and_air(self.ct_node)
        if masked_node is not None:
            self.ct_masked_node = masked_node

    def _segment(self):
        ct_input = self.ct_node.GetName() if self.ct_node else None
        seg_node = segmentation.run_segmentation(
            ct_input, self.output_dir, force_cpu=self.force_cpu)
        self.segmentation_node = seg_node

    def _validate_segmentation_auto(self):
        logger.info("")
        logger.info("  ========================================================")
        logger.info("  Autochequeo de segmentos")
        logger.info("  ========================================================")
        if self.segmentation_node is None:
            logger.error("  No hay nodo de segmentacion")
            return False
        try:
            import vtk
            seg_node = self.segmentation_node
            segment_ids = vtk.vtkStringArray()
            seg_node.GetSegmentation().GetSegmentIDs(segment_ids)
            num_segments = segment_ids.GetNumberOfValues()
            logger.info(f"  Segmentos: {num_segments}")
            if num_segments == 0:
                logger.error("Sin segmentos")
                return False
            all_segments = []
            for i in range(num_segments):
                sid = segment_ids.GetValue(i)
                all_segments.append(sid)
                segment = seg_node.GetSegmentation().GetSegment(sid)
                seg_name = segment.GetName() if segment else sid
                logger.info(f"    - {seg_name}")
            if self.segmenter == "totalsegmentator":
                expected_critical = ["bone", "liver", "lung"]
                found_critical = [e for e in expected_critical
                                  if any(e.lower() in s.lower() for s in all_segments)]
                logger.info(f"  Organos criticos: {found_critical}")
                if len(found_critical) < 2:
                    logger.warning("Solo {}/3 organos criticos".format(len(found_critical)))
                    return False
                return True
            else:
                if num_segments >= 1:
                    logger.info("  AUTOVALIDACION: OK")
                    return True
                else:
                    logger.error("Sin segmentos")
                    return False
        except Exception as e:
            logger.error(f"Error en autovalidacion: {e}")
            return False

    def _do_validation(self, context="segmentacion"):
        logger.info(f"  [VALIDACION MEDICA] Dialogo de {context}")
        try:
            validation.validate_segmentation(context=context)
            return True
        except RuntimeError:
            return False
        except Exception as e:
            logger.error(f"Error en dialogo de validacion: {e}")
            logger.warning("Fallback: auto-aprobando")
            return True

    def _add_tumor(self):
        import slicer
        logger.info("  Creando tumor (modo: {})...".format(
            self.tumor_config.get("mode", "synthetic")))
        result = tumor_creator.create_tumor(
            segmentation_node=self.segmentation_node,
            ct_node=self.ct_node,
            tumor_config=self.tumor_config)
        self._tumor_result = result
        logger.info(f"  Volumen tumor: {result.get('tumor_volume_cc', 'N/A')} cm^3")

    def _create_healthy_liver(self):
        import slicer
        import vtk
        seg_node = self.segmentation_node
        if seg_node is None:
            logger.error("No hay nodo de segmentacion")
            return
        seg_ids = vtk.vtkStringArray()
        seg_node.GetSegmentation().GetSegmentIDs(seg_ids)
        tumor_names = {"Tumor_Sintetico", "Tumor_Cargado", "Tumor_Manual", "Tumor_TS"}
        healthy_liver_name = "higado_sano"
        found_tumor = False
        found_healthy = False
        for i in range(seg_ids.GetNumberOfValues()):
            sid = seg_ids.GetValue(i)
            segment = seg_node.GetSegmentation().GetSegment(sid)
            if segment:
                name = segment.GetName()
                if name in tumor_names:
                    found_tumor = True
                    logger.info(f"  [OK] '{name}' presente")
                if name == healthy_liver_name:
                    found_healthy = True
        if found_healthy:
            logger.info("  [OK] 'higado_sano' presente")
        else:
            logger.warning("'higado_sano' NO encontrado")

    def _validate_tumor(self, context="sintetico"):
        import slicer
        logger.info("  Validacion medica del tumor...")
        ok = tumor_validation.validate_tumor_segmentation(context=context)
        if ok:
            logger.info("  [OK] Tumor validado por el medico")
        else:
            logger.error("Tumor RECHAZADO por el medico")
            raise RuntimeError("Validacion tumoral rechazada por el medico")

    def _segment_body(self):
        import slicer
        import vtk
        import json
        ct_node = getattr(self, 'ct_node', None) or getattr(self, 'ct_masked_node', None)
        if not ct_node:
            raise RuntimeError("Nodo CT no disponible para segmentacion corporal")
        body_config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "totalsegmentator_config_body.jsonc")
        body_config = {}
        if os.path.exists(body_config_path):
            try:
                import json5
                with open(body_config_path, "r", encoding="utf-8") as f:
                    body_config = json5.load(f)
            except Exception:
                pass
        task = body_config.get("task", "body")
        fast = body_config.get("fast", True)
        force_cpu = body_config.get("force_cpu", True)
        subset = body_config.get("subset", None)
        body_seg_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Body_Segmentation")
        body_seg_node.CreateDefaultDisplayNodes()
        slicer.util.selectModule("TotalSegmentator")
        from TotalSegmentator import TotalSegmentatorLogic
        logic = TotalSegmentatorLogic()
        logic.setupPythonRequirements()
        logic.process(
            inputVolume=ct_node, outputSegmentation=body_seg_node,
            task=task, fast=fast, cpu=force_cpu, subset=subset)
        self.body_node = body_seg_node

    def _export_labelmap(self):
        import slicer
        ct_node = getattr(self, 'ct_node', None) or getattr(self, 'ct_masked_node', None)
        seg_node = getattr(self, 'segmentation_node', None)
        body_node = getattr(self, 'body_node', None)
        if not seg_node or not ct_node:
            raise RuntimeError("Nodos necesarios no disponibles para exportar labelmap")
        labelmap_dir = getattr(self, 'image_output_dir', None) or \
                       getattr(self, 'labelmap_dir', None)
        if not labelmap_dir:
            labelmap_dir = os.path.join(self.output_dir, "exports")
            self.image_output_dir = labelmap_dir
        os.makedirs(labelmap_dir, exist_ok=True)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Buscar tissue_config.json en ubicaciones de v4
        tissue_config_candidates = [
            # v4: slicer_modules/SlicerDosim/Resources/Config/
            os.path.join(base_dir, "slicer_modules", "SlicerDosim",
                         "Resources", "Config", "tissue_config.json"),
            # v3.14 legacy: Modules/Scripted/SlicerDosim/Resources/Config/
            os.path.join(base_dir, "Modules", "Scripted", "SlicerDosim",
                         "Resources", "Config", "tissue_config.json"),
            # Relativo a PipelineOrchestrator/
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "slicer_modules", "SlicerDosim",
                         "Resources", "Config", "tissue_config.json"),
        ]
        tissue_config_path = None
        for candidate in tissue_config_candidates:
            if os.path.exists(candidate):
                tissue_config_path = candidate
                break
        if not tissue_config_path:
            logger.warning("tissue_config.json no encontrado — usando fallback")
            tissue_config_path = tissue_config_candidates[0]
        resultado = labelmap_exporter.export_labelmap(
            segmentation_node=seg_node, ct_node=ct_node,
            tissue_config_path=tissue_config_path,
            output_dir=labelmap_dir, body_segmentation_node=body_node)
        # Mostrar resumen en Slicer via status bar (NO QMessageBox — cuelga Slicer)
        nifti = resultado.get("nifti_path") or "N/A"
        nrrd = resultado.get("nrrd_path") or "N/A"
        segs = resultado.get("num_segments", 0)
        overlaps = resultado.get("overlap_voxels", 0)
        indices = resultado.get("phantom_indices_used", [])
        logger.info(f"  === LABELMAP EXPORTADA ===")
        logger.info(f"  Segmentos: {segs} | Overlap: {overlaps} | Indices: {indices}")
        logger.info(f"  NIfTI: {nifti}")
        logger.info(f"  NRRD:  {nrrd}")
        slicer.util.showStatusMessage(
            f"Labelmap exportada: {segs} segmentos, {overlaps} overlaps", 8000)
        slicer.app.processEvents()

    def _save_results_json(self):
        import json
        from datetime import datetime
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
            "fecha": datetime.now().isoformat(),
            "modulo": "Mod1",
            "patient_id": self.patient_id,
            "escena": "3Dosim.mrb",
            "data_dir": self.data_dir,
            "output_dir": self.output_dir,
            "segmenter": self.segmenter,
            "force_cpu": self.force_cpu,
            "total_pasos": total,
            "exitosos": ok_count,
            "fallos": fails,
            "resultado": "OK" if fails == 0 else "ERROR",
            "pasos": self.results["pasos"],
            "errores": self.results["errores"],
            "screenshots": self.screenshots,
            "checkpoint_data": self.checkpoint.state.get("data", {}),
        }
        historial.append(registro)
        with open(results_file, "w") as f:
            json.dump(historial, f, indent=2, default=str)
        logger.info(f"  Resultados guardados en: {results_file}")

    def _report(self) -> bool:
        try:
            self._save_results_json()
        except Exception as e:
            logger.warning(f"No se pudo guardar results.json: {e}")
        logger.info("")
        logger.info("=" * 70)
        logger.info(" REPORTE FINAL - MODULO 1")
        logger.info("=" * 70)
        total = len(self.results["pasos"])
        ok_count = sum(1 for p in self.results["pasos"] if p["ok"])
        fails = total - ok_count
        skipped = sum(1 for p in self.results["pasos"] if p.get("checkpoint"))
        logger.info(f"Pasos totales:     {total}")
        logger.info(f"Exitosos:          {ok_count}")
        logger.info(f"Desde checkpoint:  {skipped}")
        logger.info(f"Fallos:            {fails}")
        if fails > 0:
            logger.info("ERRORES:")
            for err in self.results["errores"]:
                logger.info(f"  - {err}")
        logger.info("DETALLE DE PASOS:")
        logger.info("-" * 70)
        for paso in self.results["pasos"]:
            status = "+" if paso["ok"] else "-"
            cp = " (checkpoint)" if paso.get("checkpoint") else ""
            tiempo = f"{paso['tiempo']:.1f}s" if paso['tiempo'] > 0 else "-"
            logger.info(f"  {status} {paso['nombre']:<45s} {tiempo:>8s}{cp}")
        logger.info(f"Output: {self.output_dir}")
        all_ok = fails == 0
        if all_ok:
            logger.info(" RESULTADO: TODOS LOS PASOS EXITOSOS")
        else:
            logger.info(f" RESULTADO: {fails}/{total} PASOS FALLARON")
        logger.info("=" * 70)
        return all_ok
