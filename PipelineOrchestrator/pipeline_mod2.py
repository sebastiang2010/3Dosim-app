"""
PipelineMod2 - Modulo 2: Generacion de entrada MCNP desde escena Mod1.
Flujo: carga escena .mrb, escanea nodos, genera input MCNP, valida.

NO incluye carga DICOM/segmentacion/tumor (eso es Mod1).
NO incluye analisis dosimetrico (eso es Mod3).

Sigue el mismo patron que PipelineMod1 (CheckpointManager, _checkpoint_step, etc.).
"""

import logging
import os
import time

from PipelineOrchestrator.checkpoint import CheckpointManager
from PipelineOrchestrator.utils import logger as base_logger, add_module_path, show_progress, track_time
from PipelineOrchestrator.views import load_pipeline_config
from PipelineOrchestrator.comandos import ConsolaComandos
from PipelineOrchestrator import ai_supervisor

logger = logging.getLogger("3DosimMod2")


# ──────────────────────────────────────────────────────────
# PipelineMod2 class
# ──────────────────────────────────────────────────────────

class PipelineMod2:
    """
    Pipeline Modulo 2: carga escena .mrb (generada por Mod1),
    escanea nodos y genera entrada MCNP.
    """

    STEP_CHECK_SLICER  = "check_slicer"
    STEP_LOAD_SCENE    = "load_scene"
    STEP_SCAN_NODES    = "scan_nodes"
    STEP_GENERATE_MCNP = "generate_mcnp"
    STEP_VALIDATE_MCNP = "validate_mcnp"

    def __init__(self, scene_path=None, output_dir=None, reset=False,
                 isotope="Y-90", n_particles=int(1e7),
                 flip_rows=True, flip_z=False, refine_hu=False,
                 n_liver_tallies=5, n_tumor_tallies=10,
                 no_consola=False):
        """
        Args:
            scene_path: Ruta al archivo .mrb (de Mod1). Si None, auto-detecta.
            output_dir: Directorio de salida. Si None, usa junto a scene_path.
            reset: Si True, reinicia checkpoints.
            isotope: Isotopo para la fuente (Y-90, I-131, Lu-177, Tc-99m).
            n_particles: Numero de historias MCNP.
            flip_rows: Invertir eje Y antes de RLE.
            flip_z: Invertir eje Z.
            refine_hu: Refinar mapeo HU -> materiales.
            n_liver_tallies: Numero de tallies de higado en FMESH4.
            n_tumor_tallies: Numero de tallies de tumor en FMESH4.
            no_consola: Si True, deshabilita la consola interactiva.
        """
        # ── Scene path ──
        self.scene_path = scene_path or self._auto_detect_scene()
        if not self.scene_path or not os.path.exists(self.scene_path):
            logger.warning("No se encontro escena .mrb. Se requiere --scene al ejecutar.")

        # ── Output dir ──
        if output_dir:
            self.output_dir = output_dir
        elif self.scene_path:
            scene_parent = os.path.dirname(os.path.dirname(self.scene_path))
            self.output_dir = scene_parent  # scenes/ -> ai-pipe/
        else:
            self.output_dir = r"C:\MAT\3Dosim\ai-pipe"

        self.mcnp_dir = os.path.join(self.output_dir, "mcnp_input")
        self.checkpoint_dir = os.path.join(self.output_dir, ".checkpoints", "mod2")
        self.results = {"pasos": [], "errores": [], "tiempos": {}}

        self.checkpoint = CheckpointManager(self.checkpoint_dir)
        if reset:
            self.checkpoint.reset()

        # ── MCNP params ──
        self.isotope = isotope
        self.n_particles = n_particles
        self.flip_rows = flip_rows
        self.flip_z = flip_z
        self.refine_hu = refine_hu
        self.n_liver_tallies = n_liver_tallies
        self.n_tumor_tallies = n_tumor_tallies
        self.mcnp_output_path = None

        # ── Consola interactiva ──
        self.no_consola = no_consola
        self.consola = None
        if not no_consola:
            try:
                self.consola = ConsolaComandos(output_dir=self.output_dir)
            except Exception:
                self.consola = None

        # ── Nodos (se llenan en scan_nodes) ──
        self.ct_node = None
        self.ct_masked_node = None
        self.pet_node = None
        self.segmentation_node = None

        # ── Config ──
        self.pipeline_config = load_pipeline_config()
        self.scene_output_dir = self.pipeline_config.get(
            "scene_output_dir",
            os.path.join(self.output_dir, "scenes"),
        )

        logger.info("=" * 60)
        logger.info(" 3Dosim Pipeline Modulo 2 — Generacion MCNP")
        logger.info("=" * 60)
        logger.info(f"  Escena:       {self.scene_path or 'NO DISPONIBLE'}")
        logger.info(f"  Output:       {self.mcnp_dir}")
        logger.info(f"  Checkpoints:  {self.checkpoint_dir}")
        logger.info(f"  Isotopo:      {isotope}")
        logger.info(f"  Particulas:   {n_particles:.0e}")
        logger.info(f"  Flip Y:       {flip_rows}")
        logger.info(f"  Flip Z:       {flip_z}")
        logger.info(f"  Reset:        {'SI' if reset else 'NO (retoma checkpoints)'}")
        logger.info(f"  Consola:      {'SI' if not no_consola else 'NO'}")
        if not no_consola and self.consola:
            logger.info(f"  Consola OK")
        logger.info("")

    # ==================================================================
    # RUN
    # ==================================================================

    def run(self):
        """Ejecuta el pipeline Mod2 completo."""
        logger.info("")
        logger.info("INICIANDO PIPELINE MODULO 2")
        logger.info("")

        # ── Mostrar consola interactiva ──
        if self.consola:
            self.consola.log("=" * 50)
            self.consola.log(" 3Dosim Mod2 - Generacion MCNP")
            self.consola.log(" Escribi 'ayuda' para comandos disponibles")
            self.consola.log("=" * 50)
            self.consola.log("")
            self.consola.mostrar()
        self._log_consola("Iniciando Modulo 2...")

        if not self.scene_path or not os.path.exists(self.scene_path):
            logger.error("No hay escena .mrb disponible. Abortando.")
            logger.error("Use --scene <path> o ejecute Mod1 primero.")
            self._log_consola("ERROR: No hay escena .mrb disponible")
            self._report()
            return

        if self._checkpoint_step(self.STEP_CHECK_SLICER, "Verificando entorno Slicer",
                                 self._check_slicer):
            add_module_path()

        # load_scene SIEMPRE se ejecuta (no checkpointeable)
        # porque cada sesion de Slicer es fresh y necesita la escena cargada
        try:
            self._load_scene()
            self.results["pasos"].append({
                "nombre": "Cargando escena .mrb", "ok": True, "tiempo": 0
            })
            self._log_consola("Escena cargada exitosamente")
        except Exception as e:
            logger.error(f"Fallo critico al cargar escena: {e}. Abortando.")
            self._log_consola(f"ERROR: Fallo al cargar escena - {e}")
            self._report()
            return

        # scan_nodes SIEMPRE se ejecuta (es barato y asegura nodos frescos)
        try:
            self._scan_nodes()
            self.results["pasos"].append({
                "nombre": "Escaneando nodos de la escena", "ok": True, "tiempo": 0
            })
            self._log_consola(f"Nodos: CT={self.ct_node.GetName() if self.ct_node else 'N/A'}, "
                             f"PET={self.pet_node.GetName() if self.pet_node else 'N/A'}, "
                             f"Seg={self.segmentation_node.GetName() if self.segmentation_node else 'N/A'}")
        except Exception as e:
            logger.error(f"Fallo al escanear nodos: {e}. Abortando.")
            self._log_consola(f"ERROR: Fallo al escanear nodos - {e}")
            self._report()
            return

        # ── VALIDACION PRE-MCNP ──
        self._log_consola("Verificando prerrequisitos para MCNP...")
        if not self._checkpoint_step("validate_prereqs", "Validando prerrequisitos MCNP",
                                      self._validate_prerequisites,
                                      data_func=lambda: {"validado": True}):
            logger.error("Prerrequisitos MCNP no satisfechos. Abortando.")
            self._log_consola("ERROR: Prerrequisitos MCNP no satisfechos. Revise logs.")
            self._report()
            return
        self._log_consola("Prerrequisitos OK")

        # ── GENERACION MCNP ──
        self._log_consola(f"Generando entrada MCNP (isotopo: {self.isotope})...")
        if not self._checkpoint_step(self.STEP_GENERATE_MCNP, "Generando entrada MCNP",
                                      self._generate_mcnp,
                                      data_func=lambda: {
                                          "isotope": self.isotope,
                                          "n_particles": self.n_particles,
                                          "output_path": self.mcnp_output_path,
                                          "file_size_kb": os.path.getsize(self.mcnp_output_path) / 1024 if self.mcnp_output_path and os.path.exists(self.mcnp_output_path) else 0,
                                      }):
            logger.error("Generacion MCNP fallida. Abortando.")
            self._log_consola("ERROR: Generacion MCNP fallida. Revise logs.")
            self._report()
            return

        self._save_scene("02_post_mcnp")
        self._log_consola(f"Archivo MCNP generado: {os.path.basename(self.mcnp_output_path)}")

        # ── VALIDACION MCNP ──
        self._log_consola("Validando archivo MCNP...")
        if not self._checkpoint_step(self.STEP_VALIDATE_MCNP, "Validando archivo MCNP",
                                      self._validate_mcnp,
                                      data_func=lambda: {
                                          "mcnp_path": self.mcnp_output_path,
                                          "exists": os.path.exists(self.mcnp_output_path) if self.mcnp_output_path else False,
                                      }):
            logger.warning("Validacion MCNP encontro problemas potenciales.")
            self._log_consola(f"ADVERTENCIA: Validacion MCNP encontro problemas")

        # ── DIALOGO FINAL ──
        self._show_mcnp_summary_dialog()

        # Pipeline Mod2 completado
        logger.info("")
        logger.info("  PIPELINE MODULO 2 COMPLETADO")
        logger.info("")
        logger.info("  Flujo ejecutado:")
        logger.info("    1. Verificar Slicer")
        logger.info("    2. Cargar escena .mrb desde Mod1")
        logger.info("    3. Escanear nodos (CT, PET, Segmentacion)")
        logger.info("    4. Validar prerrequisitos MCNP")
        logger.info("    5. Generar entrada MCNP")
        logger.info("    6. Validar archivo MCNP generado")
        logger.info("")
        logger.info("  Siguiente paso:")
        logger.info("    Modulo 3: analisis dosimetrico desde output MCNP")
        logger.info("")

        ok = self._report()
        if ok:
            self._log_consola("Modulo 2 finalizado EXITOSAMENTE")
        else:
            self._log_consola("Modulo 2 finalizado con ERRORES. Revise el reporte.")

    # ==================================================================
    # CHECKPOINT + HELPERS (mismo patron que PipelineMod1)
    # ==================================================================

    def _checkpoint_step(self, step_name, display_name, func, data_func=None):
        if self.checkpoint.is_completed(step_name):
            logger.info(f"  [{'...'}]: ya completado (checkpoint salta)")
            self.results["pasos"].append({
                "nombre": display_name, "ok": True, "tiempo": 0, "checkpoint": True
            })
            cp_data = self.checkpoint.get_data(step_name)
            if cp_data:
                self._restore_step_state(step_name, cp_data)
            return True

        logger.info(f"[{len(self.results['pasos'])+1}] {display_name}...")
        show_progress(f"Ejecutando: {display_name}")

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
            self._ai_review_paso(display_name, ok=False, elapsed=elapsed,
                                 step_name=step_name, error=str(e))
            return False

    def _ai_review_paso(self, display_name, ok, elapsed, step_name, data=None, error=None):
        """Envia el paso completado al AI supervisor para revision."""
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
            ctx["datos"]["nodos_activos"] = nodos_info
            ctx["datos"]["isotope"] = self.isotope
            ctx["datos"]["output_dir"] = self.mcnp_dir
            ai_supervisor.revisar_paso(ctx, consola=self.consola)
        except Exception as e:
            logger.debug(f"AI review no disponible: {e}")

    def _restore_step_state(self, step_name, data):
        """Restaura estado desde checkpoint data.

        Soporta dos formatos:
        - Nuevo: ``{"ct_node_name": "nombre"}`` → ``slicer.util.getNode("nombre")``
        - Viejo: ``{"ct_node": "nombre"}`` → mismo lookup, para compatibilidad

        NOTA: Si la escena no esta cargada (checkpoint load_scene salteado
        y Slicer fresh), este metodo fallara silenciosamente y los nodos
        quedaran en None. Por eso load_scene se ejecuta SIEMPRE (ver run()).
        """
        if not data:
            return
        import slicer
        # Mapeo de compatibilidad: keys viejos del checkpoint → attr actual
        compat_keys = {"seg_node": "segmentation_node"}
        # Restaurar nodos
        for key in ["ct_node", "pet_node", "segmentation_node"]:
            name_key = key + "_name"
            node_name = None
            # Nuevo formato: _name suffix
            if name_key in data and data[name_key] is not None:
                node_name = data[name_key]
            # Viejo formato 1: key directo con string (ej: "ct_node": "nombre")
            elif key in data and isinstance(data[key], str) and data[key]:
                node_name = data[key]
            # Viejo formato 2: key legacy (ej: "seg_node": "nombre")
            for old_key, mapped_key in compat_keys.items():
                if mapped_key == key and old_key in data and isinstance(data[old_key], str) and data[old_key]:
                    node_name = data[old_key]
                    break
            if node_name:
                try:
                    node = slicer.util.getNode(node_name)
                    setattr(self, key, node)
                except Exception:
                    pass
        if self.mcnp_output_path is None and data.get("output_path"):
            self.mcnp_output_path = data["output_path"]

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
            allowed = {"01_post_load_scene", "02_post_mcnp"}
            if tag not in allowed:
                logger.info(f"  Escena '{tag}' omitida (save_scene.frequency=minimal)")
                return None

        # ── Mostrar cartel no-modal "Guardando escena..." ──
        from PipelineOrchestrator.utils import show_save_scene_dialog, close_save_scene_dialog
        dialog = show_save_scene_dialog()

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
            close_save_scene_dialog(dialog)

    def _save_results_json(self):
        """Guarda resultados en JSON (historial acumulado)."""
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
            "modulo": "Mod2",
            "scene_path": self.scene_path,
            "output_dir": self.output_dir,
            "isotope": self.isotope,
            "n_particles": self.n_particles,
            "total_pasos": total,
            "exitosos": ok_count,
            "fallos": fails,
            "resultado": "OK" if fails == 0 else "ERROR",
            "mcnp_output": self.mcnp_output_path,
            "pasos": self.results["pasos"],
            "errores": self.results["errores"],
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
        logger.info(" REPORTE FINAL - MODULO 2")
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
        if self.mcnp_output_path and os.path.exists(self.mcnp_output_path):
            size_kb = os.path.getsize(self.mcnp_output_path) / 1024
            logger.info(f"  Archivo MCNP: {self.mcnp_output_path}")
            logger.info(f"  Tamano:       {size_kb:.1f} KB")
        logger.info(f"  Output: {self.mcnp_dir}")
        all_ok = fails == 0
        if all_ok:
            logger.info("  RESULTADO: TODOS LOS PASOS EXITOSOS")
        else:
            logger.info(f"  RESULTADO: {fails}/{total} PASOS FALLARON")
        logger.info("=" * 70)
        return all_ok

    # ==================================================================
    # STEP METHODS
    # ==================================================================

    # ==================================================================
    # LOGGING A CONSOLA
    # ==================================================================

    def _log_consola(self, mensaje: str):
        """Envia un mensaje a la consola interactiva (si existe)."""
        if self.consola:
            self.consola.log(mensaje)

    def _log_consola_ok(self, mensaje: str):
        """Envia un mensaje de exito a la consola."""
        if self.consola:
            self.consola.log_ok(mensaje)

    def _log_consola_error(self, mensaje: str):
        """Envia un mensaje de error a la consola."""
        if self.consola:
            self.consola.log_error(mensaje)

    # ==================================================================
    # VALIDACION PRE-MCNP
    # ==================================================================

    def _validate_prerequisites(self):
        """Valida que todos los prerrequisitos para generar MCNP esten OK.
        
        Si algo falta, lanza RuntimeError con mensaje claro de lo que falla.
        """
        import slicer
        errores = []

        # 1. CT node debe existir y tener datos
        if self.ct_node is None:
            errores.append("No se encontro nodo CT en la escena")
        else:
            img = self.ct_node.GetImageData()
            if img is None:
                errores.append(f"El nodo CT '{self.ct_node.GetName()}' no tiene datos de imagen")

        # 2. Segmentation node debe existir
        if self.segmentation_node is None:
            errores.append("No se encontro nodo de segmentacion/labelmap en la escena")
        else:
            # Si es labelmap, verificar que tenga datos
            if hasattr(self.segmentation_node, 'GetImageData'):
                img = self.segmentation_node.GetImageData()
                if img is None:
                    errores.append(f"Nodo '{self.segmentation_node.GetName()}' no tiene datos")

        # 3. Output dir debe ser escribible
        try:
            os.makedirs(self.mcnp_dir, exist_ok=True)
            test_file = os.path.join(self.mcnp_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            errores.append(f"El directorio de salida no es escribible: {e}")

        # 4. MCNPInputGenerator debe ser importable
        try:
            from SlicerDosim.SlicerDosimLib import MCNPInputGenerator
        except ImportError:
            try:
                from SlicerDosimLib import MCNPInputGenerator
            except ImportError as e:
                errores.append(f"No se pudo importar MCNPInputGenerator: {e}")

        if errores:
            msg = "PRERREQUISITOS MCNP NO SATISFECHOS:\n"
            for i, err in enumerate(errores, 1):
                msg += f"  {i}. {err}\n"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info("  Todos los prerrequisitos MCNP OK:")
        logger.info(f"    CT:       {self.ct_node.GetName()}")
        logger.info(f"    Segment:  {self.segmentation_node.GetName()}")
        logger.info(f"    Output:   {self.mcnp_dir}")
        logger.info(f"    Generator: importable")

    # ==================================================================
    # DIALOGO FINAL MCNP
    # ==================================================================

    def _show_mcnp_summary_dialog(self):
        """Muestra dialogo NO modal con resumen MCNP y comando de ejecucion."""
        try:
            import slicer
            from qt import QMessageBox

            if not self.mcnp_output_path or not os.path.exists(self.mcnp_output_path):
                logger.warning("No hay archivo MCNP para mostrar en dialogo")
                return

            file_size_kb = os.path.getsize(self.mcnp_output_path) / 1024
            file_name = os.path.basename(self.mcnp_output_path)

            # Construir comando de ejecucion MCNP
            mcnp_exe = "mcnp5"  # o mcnp6
            exec_cmd = (
                f"{mcnp_exe} i={file_name} name=3Dosim."
            )

            msg_box = QMessageBox(slicer.util.mainWindow())
            msg_box.setWindowTitle("3Dosim - MCNP Generado")
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setTextFormat(1)  # Qt.RichText

            labelmap_name = self.segmentation_node.GetName() if self.segmentation_node else "N/A"
            ct_name = self.ct_node.GetName() if self.ct_node else "N/A"

            html = (
                f"<b>Archivo MCNP generado correctamente</b><br><br>"
                f"<b>Archivo:</b> {file_name}<br>"
                f"<b>Ubicacion:</b> {self.mcnp_dir}<br>"
                f"<b>Tamano:</b> {file_size_kb:.1f} KB<br><br>"
                f"<b>Isotopo:</b> {self.isotope}<br>"
                f"<b>Particulas:</b> {self.n_particles:.0e}<br>"
                f"<b>Flip Y:</b> {'Si' if self.flip_rows else 'No'}<br>"
                f"<b>Flip Z:</b> {'Si' if self.flip_z else 'No'}<br>"
                f"<b>Refinar HU:</b> {'Si' if self.refine_hu else 'No'}<br><br>"
                f"<b>Referencias espaciales:</b><br>"
                f"&nbsp;&nbsp;CT: {ct_name}<br>"
                f"&nbsp;&nbsp;Labelmap: {labelmap_name}<br><br>"
                f"<b>Ejecutar MCNP:</b><br>"
                f"<code style='background:#f0f0f0; padding:4px 8px; display:block; "
                f"margin:4px 0; border-radius:4px;'>"
                f"cd /d {self.mcnp_dir}<br>"
                f"{exec_cmd}"
                f"</code>"
            )
            msg_box.setText(html)
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.setModal(False)
            msg_box.show()
            msg_box.raise_()
            msg_box.activateWindow()
            logger.info("  Dialogo de resumen MCNP mostrado")
        except Exception as e:
            logger.warning(f"No se pudo mostrar dialogo MCNP: {e}")
            # Fallback: mostrar en log
            logger.info("  =========== RESUMEN MCNP ===========")
            logger.info(f"  Archivo: {self.mcnp_output_path}")
            logger.info(f"  Tamano: {file_size_kb:.1f} KB")
            logger.info(f"  Isotopo: {self.isotope}")
            logger.info(f"  Particulas: {self.n_particles:.0e}")
            logger.info(f"  cd {self.mcnp_dir}")
            logger.info(f"  mcnp5 i={os.path.basename(self.mcnp_output_path)} name=3Dosim.")
            logger.info("  ====================================")

    def _check_slicer(self):
        """Verifica que estamos dentro de 3D Slicer."""
        try:
            import slicer
            version = f"{slicer.app.majorVersion}.{slicer.app.minorVersion}"
            logger.info(f"  Slicer version: {version}")
        except ImportError:
            raise RuntimeError("No se detecta 3D Slicer. Ejecutar dentro de Slicer.")

    def _load_scene(self):
        """Carga escena .mrb con barra de progreso."""
        import slicer

        if not os.path.exists(self.scene_path):
            raise FileNotFoundError(f"Escena no encontrada: {self.scene_path}")

        size_mb = os.path.getsize(self.scene_path) / (1024 * 1024)
        logger.info(f"  Escena: {self.scene_path}")
        logger.info(f"  Tamano: {size_mb:.0f} MB")

        with track_time("Cargando escena"):
            success = slicer.util.loadScene(self.scene_path)
            slicer.app.processEvents()
            if not success:
                raise RuntimeError("slicer.util.loadScene() devolvio False")

        logger.info("  Escena cargada exitosamente")

    def _scan_nodes(self):
        """Busca nodos CT, PET y Segmentacion en la escena cargada."""
        import slicer
        import vtk

        vol_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        seg_nodes_list = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        lb_nodes = slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")

        logger.info(f"  Volumenes: {len(vol_nodes)}, Segmentaciones: {len(seg_nodes_list)}, LabelMaps: {len(lb_nodes)}")

        # ── CT ──
        ct_candidates = [n for n in vol_nodes if "CT" in n.GetName() or "ct" in n.GetName().lower()]
        if ct_candidates:
            preferred = [n for n in ct_candidates if "anon" in n.GetName().lower() or "sin_camilla" in n.GetName().lower()]
            self.ct_node = preferred[0] if preferred else ct_candidates[0]
            logger.info(f"  CT: '{self.ct_node.GetName()}'")
        elif vol_nodes:
            self.ct_node = vol_nodes[0]
            logger.info(f"  CT (fallback): '{self.ct_node.GetName()}'")
        else:
            raise RuntimeError("No se encontraron volumenes CT en la escena")

        # ── CT_masked (opcional) ──
        masked = [n for n in vol_nodes if "sin_camilla" in n.GetName().lower() or "masked" in n.GetName().lower()]
        if masked:
            self.ct_masked_node = masked[0]
            logger.info(f"  CT_masked: '{self.ct_masked_node.GetName()}'")

        # ── PET (opcional) ──
        pet_candidates = [n for n in vol_nodes if "PET" in n.GetName() or "pet" in n.GetName().lower()]
        if pet_candidates:
            self.pet_node = pet_candidates[0]
            logger.info(f"  PET: '{self.pet_node.GetName()}'")
        else:
            self.pet_node = None
            logger.info("  PET: No encontrado (fuente uniforme)")

        # ── Segmentacion ──
        seg_found = None

        # Prioridad 1: labelmap pre-exportada por Mod1 ("3Dosim_Labelmap")
        # Ya tiene TODOS los indices correctos (30=Tejido_blando, 50=Pulmon,
        # 80=Hueso, 90=Higado, 100=Tumor) y NO necesita re-extraccion.
        preferred_lb = [n for n in lb_nodes if "3Dosim_Labelmap" in n.GetName()]
        if preferred_lb:
            seg_found = preferred_lb[0]
            logger.info(f"  Labelmap dosimetrica: '{seg_found.GetName()}' (preferida)")
            logger.info(f"    Usando labelmap ya exportada con indices del tissue_config")
        elif seg_nodes_list:
            ts_candidates = [n for n in seg_nodes_list if "TotalSegmentator" in n.GetName() or "Segmentation" in n.GetName()]
            seg_found = ts_candidates[0] if ts_candidates else seg_nodes_list[0]
            logger.info(f"  Segmentacion: '{seg_found.GetName()}'")
            # Contar segmentos
            seg_ids = vtk.vtkStringArray()
            seg_found.GetSegmentation().GetSegmentIDs(seg_ids)
            n_segs = seg_ids.GetNumberOfValues()
            logger.info(f"    Segmentos: {n_segs}")
        elif lb_nodes:
            seg_found = lb_nodes[0]
            logger.info(f"  Segmentacion (labelmap fallback): '{seg_found.GetName()}'")
        else:
            raise RuntimeError("No se encontraron nodos de segmentacion en la escena")

        self.segmentation_node = seg_found

    def _generate_mcnp(self):
        """Genera archivo de entrada MCNP usando MCNPInputGenerator."""
        try:
            from SlicerDosim.SlicerDosimLib import MCNPInputGenerator
        except ImportError:
            from SlicerDosimLib import MCNPInputGenerator

        generator = MCNPInputGenerator()

        logger.info(f"\n  Isotopo:       {self.isotope}")
        logger.info(f"  Particulas:    {self.n_particles:.0e}")
        logger.info(f"  Flip rows:     {self.flip_rows}")
        logger.info(f"  Output dir:    {self.mcnp_dir}")

        os.makedirs(self.mcnp_dir, exist_ok=True)

        with track_time("Generando MCNP"):
            input_path = generator.generate(
                ct_volume_node=self.ct_node,
                pet_volume_node=self.pet_node,
                segmentation_node=self.segmentation_node,
                output_dir=self.mcnp_dir,
                isotope=self.isotope,
                n_particles=self.n_particles,
                refine_hu=self.refine_hu,
                flip_rows=self.flip_rows,
                flip_z=self.flip_z,
                n_liver_tallies=self.n_liver_tallies,
                n_tumor_tallies=self.n_tumor_tallies,
            )

        if not os.path.exists(input_path):
            raise RuntimeError(f"El archivo MCNP no fue creado: {input_path}")

        file_size_kb = os.path.getsize(input_path) / 1024
        logger.info(f"\n  {'='*50}")
        logger.info(f"  ARCHIVO MCNP: {input_path}")
        logger.info(f"  Tamano: {file_size_kb:.1f} KB")
        logger.info(f"  {'='*50}\n")

        self.mcnp_output_path = input_path

    def _validate_mcnp(self):
        """Valida que el archivo MCNP generado sea correcto."""
        if not self.mcnp_output_path or not os.path.exists(self.mcnp_output_path):
            raise RuntimeError("Archivo MCNP no encontrado para validar")

        file_size_kb = os.path.getsize(self.mcnp_output_path) / 1024
        logger.info(f"  Validando: {self.mcnp_output_path}")
        logger.info(f"  Tamano:    {file_size_kb:.1f} KB")

        issues = []

        # Verificar tamano minimo
        if file_size_kb < 10:
            issues.append(f"Archivo MCNP muy pequeno: {file_size_kb:.1f} KB")

        # Verificar contenido basico
        try:
            with open(self.mcnp_output_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(5000)  # Leer primeras ~5000 lines

            lines = content.split("\n")
            logger.info(f"  Lineas: {len(lines)} (primeras 5000)")

            # Verificar palabras clave esenciales
            checks = {
                "cell card": "c cell" in content.lower() or "cell" in content.lower(),
                "surface card": "c surface" in content.lower() or "surface" in content.lower(),
                "data card": "c data" in content.lower(),
                "mode": "mode" in content.lower(),
                "nps": "nps" in content.lower() or "ctme" in content.lower(),
                "tally": "fmesh" in content.lower() or "f6" in content.lower() or "f4" in content.lower(),
            }

            logger.info("  Verificando palabras clave MCNP:")
            for check_name, found in checks.items():
                status = "OK" if found else "AUSENTE"
                logger.info(f"    {check_name}: {status}")
                if not found:
                    issues.append(f"Palabra clave '{check_name}' no encontrada")

            # Verificar primer caracter (debe ser mensaje o celda)
            first_line = lines[0].strip() if lines else ""
            if first_line and not first_line.startswith("c ") and not first_line.startswith("1"):
                logger.info(f"  (Primera linea no es comentario: '{first_line[:60]}')")

        except Exception as e:
            issues.append(f"Error leyendo archivo MCNP: {e}")

        if issues:
            logger.warning("  POTENCIALES PROBLEMAS:")
            for issue in issues:
                logger.warning(f"    - {issue}")
            # No lanzamos excepcion, solo reportamos
            logger.info("  Validacion completada con advertencias")
        else:
            logger.info("  Validacion: TODAS LAS VERIFICACIONES PASARON")

        return len(issues) == 0

    # ==================================================================
    # AUTO-DETECT
    # ==================================================================

    @staticmethod
    def _auto_detect_scene():
        """Auto-detecta la escena .mrb mas reciente."""
        base = r"C:\MAT\3Dosim\ai-pipe\scenes"
        candidates = [
            os.path.join(base, "3Dosim.mrb"),         # nombre actual Mod1
            os.path.join(base, "3Dosim_mod1_scene.mrb"),
            os.path.join(base, "3Dosim_scene.mrb"),
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


# ──────────────────────────────────────────────────────────
# CLI entry point (para ejecucion directa)
# ──────────────────────────────────────────────────────────

def main():
    """Entry point CLI para PipelineMod2."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Pipeline Mod2 - Generacion MCNP desde escena .mrb")
    parser.add_argument("--scene", default=None, help="Ruta al archivo .mrb")
    parser.add_argument("--output", default=None, help="Directorio de salida")
    parser.add_argument("--reset", action="store_true", help="Reiniciar checkpoints")
    parser.add_argument("--isotope", default="Y-90", help="Isotopo (Y-90, I-131, Lu-177, Tc-99m)")
    parser.add_argument("--n-particles", type=float, default=1e7, help="Numero de historias")
    parser.add_argument("--flip", action="store_true", default=True, help="Flip Y")
    parser.add_argument("--no-flip", action="store_false", dest="flip", help="No flip Y")
    parser.add_argument("--flip-z", action="store_true", help="Flip Z")
    parser.add_argument("--refine-hu", action="store_true", help="Refinar HU")
    args, _ = parser.parse_known_args()

    # Agregar paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(script_dir)  # Testing/
    if parent not in sys.path:
        sys.path.insert(0, parent)

    pipeline = PipelineMod2(
        scene_path=args.scene,
        output_dir=args.output,
        reset=args.reset,
        isotope=args.isotope,
        n_particles=int(args.n_particles),
        flip_rows=args.flip,
        flip_z=args.flip_z,
        refine_hu=args.refine_hu,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
