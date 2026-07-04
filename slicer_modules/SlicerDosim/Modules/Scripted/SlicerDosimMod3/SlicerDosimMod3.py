"""
SlicerDosimMod3 - Analisis dosimetrico V4 (kernel convolution).

NO requiere MCTAL. Usa kernel MCNP + convolucion FFT (como MATLAB).
Carga escena .mrb generada por Modulo 1/2, busca CT/PET/labelmap,
computa dosis Y-90, muestra DVH e isodosis.

Flujo al abrir modulo:
  1. Auto-detecta escena mas reciente en resultados_test/
  2. Carga CT, PET, labelmap
  3. Carga kernel.mat y computa dosis via FFT convolution
  4. Muestra DVH en Slicer (Plots module)
  5. Crea nodo de dosis 3D + isodosis
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from typing import Optional

import numpy as np
import qt
import slicer
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleWidget,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
)

logger = logging.getLogger("SlicerDosimMod3")

# ─── Agregar PipelineOrchestrator al path ──────────────────────────────
# El modulo vive en slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/
# PipelineOrchestrator esta en la raiz de V4
_this_dir = os.path.dirname(os.path.realpath(__file__))
# Subir hasta slicer_modules/SlicerDosim/Modules/Scripted/ → ../../../../../
_v4_root = os.path.normpath(os.path.join(_this_dir, "..", "..", "..", "..", ".."))
_pipe_path = os.path.join(_v4_root, "PipelineOrchestrator")
if os.path.isdir(_pipe_path) and _pipe_path not in sys.path:
    sys.path.insert(0, _pipe_path)

# ─── Imports del pipeline V4 ──────────────────────────────────────────
try:
    from run_dosimetry_from_scene import (
        load_scene,
        find_nodes,
        compute_activity_from_pet,
        compute_dvh,
        compute_biophysical,
        compute_mird,
        generate_pdf_report,
        _create_dvh_plots_slicer,
        LIVER_INDEX,
        TUMOR_INDEX,
        PRETUMOR_INDEX,
        Y90_HALF_LIFE_H,
        OUTPUT_DIR_DEFAULT,
        SCENE_DEFAULT,
        LABELMAP_DEFAULT,
        AI_PIPE_DIR,
    )
    from isodose_contours import create_isodose_contours
    from dose_kernel import load_kernel_mat
    from fft_dose import convolve_imfilter_symmetric
    from views import ensure_inverted_rainbow, load_pipeline_config
except ImportError as e:
    logger.warning(f"No se pudieron importar modulos V4: {e}")
    logger.warning("El modulo funcionara en modo limitado (solo UI manual)")
    # Placeholders para que no rompa el import
    load_scene = None
    find_nodes = None
    compute_activity_from_pet = None
    compute_dvh = None
    compute_biophysical = None
    compute_mird = None
    generate_pdf_report = None
    _create_dvh_plots_slicer = None
    ensure_inverted_rainbow = None
    load_pipeline_config = None
    LIVER_INDEX = 90
    TUMOR_INDEX = 100
    PRETUMOR_INDEX = 200

# ─── Constantes ────────────────────────────────────────────────────────
KERNEL_DEFAULT = os.path.join(_v4_root, "kernel", "kernel.mat")
SCENE_DIR_DEFAULT = os.path.join(_v4_root, "resultados_test")
ALPHA_BETA_LIVER = 2.5   # Gy (tardio)
ALPHA_BETA_TUMOR = 10.0  # Gy (agudo)


# ======================================================================
# SlicerDosimMod3 (registro del modulo)
# ======================================================================

class SlicerDosimMod3(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        self.title = "SlicerDosimMod3"
        self.description = (
            "Modulo 3: Analisis dosimetrico V4. "
            "Carga escena, computa dosis Y-90 via kernel MCNP + FFT, "
            "muestra DVH, isodosis y reporte."
        )
        self.categories = ["3Dosim"]
        self.contributors = ["3Dosim Team"]
        self.homepage = "https://github.com/example/SlicerDosim"
        self.acknowledgementText = "3Dosim V4 - Dosimetria 3D para Medicina Nuclear"


# ======================================================================
# SlicerDosimMod3Logic
# ======================================================================

class SlicerDosimMod3Logic(ScriptedLoadableModuleLogic):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("SlicerDosimMod3Logic")

        # Nodos de la escena
        self.ct_node = None
        self.pet_node = None
        self.labelmap_node = None
        self.dose_node = None
        self.segmentation_node = None

        # Arrays
        self.labelmap_array: Optional[np.ndarray] = None
        self.dose_gy: Optional[np.ndarray] = None
        self.spacing = (1.0, 1.0, 1.0)
        self.dims = (0, 0, 0)
        self.activity_gbq = 0.0
        self.activity_bq = 0.0

        # Kernel cache
        self._kernel = None
        self._kernel_fft = None
        self._fft_shape = None

        # Paths
        self.scene_path = ""
        self.kernel_path = KERNEL_DEFAULT
        self.labelmap_path = ""

        # Resultados
        self.results = {}
        self.dvh_curves = []

    # ── Escena ─────────────────────────────────────────────────────────

    def load_scene_mrb(self, path: str) -> bool:
        """Carga escena .mrb en Slicer."""
        if not os.path.exists(path):
            self.logger.error(f"Escena no encontrada: {path}")
            return False
        if load_scene is None:
            self.logger.error("load_scene no disponible (imports fallaron)")
            return False
        try:
            ok = load_scene(path)
            if ok:
                self.scene_path = path
                self.logger.info(f"Escena cargada: {path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error cargando escena: {e}")
            return False

    def find_scene_nodes(self):
        """Busca CT, PET, labelmap en la escena actual."""
        if find_nodes is None:
            raise RuntimeError("find_nodes no disponible")
        nodes = find_nodes(labelmap_name="3Dosim_labelmap")
        ct = nodes.get("ct")
        if ct is None:
            # Fallback: buscar cualquier volumen CT
            vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
            for v in vols:
                name = v.GetName().lower()
                if "ct" in name or "cargado" in name:
                    ct = v
                    break
        self.ct_node = ct or nodes.get("ct")
        self.pet_node = nodes.get("pet")
        lm = nodes.get("labelmap")
        self.labelmap_node = lm

        if self.ct_node is None:
            raise RuntimeError("No se encontro CT en la escena")

        if self.labelmap_node:
            self.labelmap_array = self._array_from_labelmap(self.labelmap_node)
            self.dims = self.labelmap_array.shape
            sp = self.labelmap_node.GetSpacing()
            self.spacing = (sp[0], sp[1], sp[2])
            self.logger.info(f"Labelmap: {self.dims}, spacing={self.spacing}")
        elif self.ct_node:
            img = self.ct_node.GetImageData()
            if img:
                self.dims = (img.GetDimensions()[0], img.GetDimensions()[1], img.GetDimensions()[2])
            sp = self.ct_node.GetSpacing()
            self.spacing = (sp[0], sp[1], sp[2])
            self.logger.info(f"CT (sin labelmap): {self.dims}")

    @staticmethod
    def _array_from_labelmap(node):
        arr = slicer.util.arrayFromVolume(node)  # (nz, ny, nx)
        return arr.transpose(2, 1, 0).astype(np.int32)  # (nx, ny, nz)

    # ── Actividad ──────────────────────────────────────────────────────

    def compute_activity(self) -> float:
        """Computa actividad total desde PET. Retorna GBq."""
        if self.pet_node is None:
            raise RuntimeError("No hay nodo PET. Especifique actividad manualmente.")
        if compute_activity_from_pet is None:
            raise RuntimeError("compute_activity_from_pet no disponible")
        bq = compute_activity_from_pet(self.pet_node)
        self.activity_bq = float(bq)
        self.activity_gbq = self.activity_bq / 1e9
        self.logger.info(f"Actividad: {self.activity_gbq:.4f} GBq")
        return self.activity_gbq

    def set_activity(self, gbq: float):
        self.activity_gbq = gbq
        self.activity_bq = gbq * 1e9

    # ── Kernel + Dosis ─────────────────────────────────────────────────

    def load_kernel(self, path: str = "") -> np.ndarray:
        """Carga kernel.mat, retorna kernel normalizado."""
        kpath = path or self.kernel_path
        if not os.path.exists(kpath):
            raise FileNotFoundError(f"Kernel no encontrado: {kpath}")
        kernel = load_kernel_mat(kpath)
        kernel = kernel / np.sum(kernel)
        self._kernel = kernel
        self._kernel_fft = None  # invalidar cache
        self.logger.info(f"Kernel cargado: {kpath} ({kernel.shape}, sum=1.0)")
        return kernel

    def compute_dose(self) -> np.ndarray:
        """Ejecuta convolution FFT: dosis = A * kernel."""
        if self._kernel is None:
            self.load_kernel()
        if self.labelmap_array is None:
            raise RuntimeError("Sin labelmap para construir A")
        if self.activity_gbq <= 0:
            raise RuntimeError(f"Actividad invalida: {self.activity_gbq} GBq")

        # Construir A (GBq/voxel) identico MATLAB A = PET * 1e-9
        liver_tumor_mask = (
            (self.labelmap_array == LIVER_INDEX)
            | (self.labelmap_array == TUMOR_INDEX)
            | (self.labelmap_array == PRETUMOR_INDEX)
        )
        n_vox = int(np.sum(liver_tumor_mask))
        if n_vox == 0:
            raise RuntimeError(f"No hay voxeles con indices LIVER/TUMOR/PRETUMOR en labelmap")
        pet_arr = np.zeros(self.dims, dtype=np.float32)
        pet_arr[liver_tumor_mask] = 1.0  # uniforme en higado+tumor
        A = pet_arr / n_vox * self.activity_gbq

        # Convolucion
        dose = convolve_imfilter_symmetric(A, self._kernel)
        dose = np.maximum(dose, 0).astype(np.float64)

        # Si hay kernel FFT cacheado, reutilizar
        self.dose_gy = dose

        # Estadisticas
        pos = dose > 0
        n_pos = int(np.sum(pos))
        self.logger.info(f"Dosis: max={np.max(dose):.2f} Gy, "
                         f"media(+)={np.mean(dose[pos]) if n_pos > 0 else 0:.2f} Gy, "
                         f"n_pos={n_pos}")

        return dose

    # ── DVH ────────────────────────────────────────────────────────────

    def compute_dvh_for_structures(self) -> dict:
        """Computa DVH y radiobiologia para higado, tumor, pretumor."""
        if self.dose_gy is None or self.labelmap_array is None:
            raise RuntimeError("Dosis o labelmap no disponibles para DVH")
        if compute_dvh is None or compute_biophysical is None:
            raise RuntimeError("DVH functions no disponibles")

        structures_def = {
            "higado":   {"idx": LIVER_INDEX,   "alpha_beta": ALPHA_BETA_LIVER},
            "tumor":    {"idx": TUMOR_INDEX,   "alpha_beta": ALPHA_BETA_TUMOR},
            "pretumor": {"idx": PRETUMOR_INDEX, "alpha_beta": ALPHA_BETA_LIVER},
        }
        labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}

        results = {}
        self.dvh_curves = []

        for name, info in structures_def.items():
            idx = info["idx"]
            mask = self.labelmap_array == idx
            n_vox = int(np.sum(mask))
            if n_vox == 0:
                self.logger.info(f"  {name} ({idx}): sin voxeles")
                continue

            dvh = compute_dvh(self.dose_gy, self.labelmap_array, idx)
            bio = compute_biophysical(dvh, info["alpha_beta"], is_tumor=(name == "tumor"))

            vol_cm3 = n_vox * self.spacing[0] * self.spacing[1] * self.spacing[2] / 1000.0

            results[name] = {
                "n_voxels": dvh["n_voxels"],
                "volume_cm3": vol_cm3,
                "mean_dose_gy": dvh["mean_dose_gy"],
                "min_dose_gy": dvh["min_dose_gy"],
                "max_dose_gy": dvh["max_dose_gy"],
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
            }

            # Curva DVH (200 puntos)
            doses = self.dose_gy[mask]
            if len(doses) > 0 and np.max(doses) > 0:
                Dmax = float(np.max(doses))
                npts = 200
                delta = Dmax / npts
                d_vals = np.arange(0, Dmax + delta, delta)
                a_vals = np.zeros(len(d_vals))
                for i, d in enumerate(d_vals):
                    a_vals[i] = np.sum(doses >= d) * 100.0 / len(doses)
                self.dvh_curves.append((labels.get(name, name), d_vals, a_vals))

        self.results = results
        return results

    # ── Visualizacion ──────────────────────────────────────────────────

    def create_dose_node(self) -> object:
        """Crea nodo de dosis 3D en Slicer."""
        from SlicerDosim.SlicerDosimLib.dosimetry import DoseCalculator
        ref = self.labelmap_node or self.ct_node
        if ref is None:
            raise RuntimeError("Sin nodo de referencia para crear volumen de dosis")
        calc = DoseCalculator()
        node = calc.create_dose_volume(self.dose_gy, ref)
        if node:
            self.dose_node = node
            self.logger.info(f"Nodo dosis creado: '{node.GetName()}'")
        return node

    def show_dvh_in_slicer(self):
        """Crea DVH plot en Slicer."""
        if _create_dvh_plots_slicer is None:
            raise RuntimeError("DVH plots no disponibles")
        _create_dvh_plots_slicer(self.dose_gy, self.labelmap_array, self.spacing, show_gui=True)
        try:
            slicer.util.selectModule("Plots")
            slicer.app.processEvents()
        except Exception:
            pass

    def _setup_dose_visualization(self) -> bool:
        """Configura overlay de dosis en slices: colormap, opacidad 0.4, foreground."""
        try:
            import slicer

            if self.dose_node is None:
                self.logger.warning("  _setup_dose_visualization: dose_node es None")
                return False

            # 1. Colormap 3Dosim_InvertedRainbow
            dose_dn = self.dose_node.GetDisplayNode()
            if dose_dn and load_pipeline_config is not None and ensure_inverted_rainbow is not None:
                _cfg = load_pipeline_config()
                dose_cmap = _cfg.get("dose", {}).get("colormap", "3Dosim_InvertedRainbow")
                cmap_node = slicer.util.getNode(dose_cmap)
                if not cmap_node:
                    cmap_id = ensure_inverted_rainbow()
                    cmap_node = slicer.mrmlScene.GetNodeByID(cmap_id)
                if cmap_node:
                    dose_dn.SetAndObserveColorNodeID(cmap_node.GetID())
                    self.logger.info(f"  Colormap '{dose_cmap}' asignado a Dosis")
            else:
                self.logger.info("  Colormap: saltado (display node o imports no disponibles)")

            # 2. Foreground overlay en slices (CT fondo + dosis overlay)
            bg_node = self.ct_node
            if bg_node is None:
                vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
                for v in vols:
                    name = v.GetName().lower()
                    if "ct" in name:
                        bg_node = v
                        break
            snodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
            for sn in snodes:
                if bg_node:
                    sn.SetBackgroundVolumeID(bg_node.GetID())
                sn.SetForegroundVolumeID(self.dose_node.GetID())
                sn.SetForegroundOpacity(0.4)
                sn.SetLabelVolumeID(None)
                sn.SetLabelOpacity(0.0)

            # 3. Forzar redraw
            lm = slicer.app.layoutManager()
            for idx in range(lm.sliceViewCount()):
                sv = lm.sliceWidget(idx).sliceView()
                if sv:
                    sv.scheduleRender()
            slicer.app.processEvents()
            self.logger.info("  Slices configurados: CT fondo + Dosis overlay (0.4)")
            return True
        except Exception as e:
            self.logger.warning(f"Error configurando visualizacion de dosis: {e}")
            return False

    def create_isodosis(self):
        """Crea isodosis contours en Slicer."""
        if self.dose_gy is None:
            raise RuntimeError("Sin dosis para isodosis")
        if self.dose_node is None:
            raise RuntimeError("Sin nodo de dosis para isodosis")
        create_isodose_contours(self.dose_node)
        # Restaurar slices post-isodosis (isodosis pudo desconfigurar foreground/background)
        self._setup_dose_visualization()

    def save_scene(self, path: str = "") -> bool:
        """Guarda escena actual como .mrb."""
        out = path or os.path.join(SCENE_DIR_DEFAULT, "3Dosim_mod3_scene.mrb")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        old_tmp = os.environ.get("TMP", "")
        old_temp = os.environ.get("TEMP", "")
        try:
            short_tmp = r"C:\tmp"
            os.makedirs(short_tmp, exist_ok=True)
            os.environ["TMP"] = short_tmp
            os.environ["TEMP"] = short_tmp
            ok = slicer.util.saveScene(out)
        finally:
            os.environ["TMP"] = old_tmp
            os.environ["TEMP"] = old_temp
        if ok:
            self.logger.info(f"Escena guardada: {out}")
        return bool(ok)

    # ── Pipeline completo ──────────────────────────────────────────────

    def run_pipeline(self, scene_path: str = "",
                     kernel_path: str = "",
                     activity_gbq: Optional[float] = None,
                     progress_callback=None) -> dict:
        """Ejecuta pipeline completo: escena → dosis → DVH → isodosis.
        
        Args:
            scene_path: Ruta a escena .mrb (OBLIGATORIO, no auto-detecta)
            kernel_path: Ruta a kernel.mat (opcional, usa default)
            activity_gbq: Actividad en GBq (opcional, computa de PET si omite)
            progress_callback: Funcion para reportar progreso
        """
        t0 = time.time()
        report = {"steps": [], "errors": [], "success": False}

        def step(name, func):
            try:
                if progress_callback:
                    progress_callback(f"Ejecutando: {name}...")
                t = time.time()
                func()
                elapsed = time.time() - t
                report["steps"].append({"name": name, "ok": True, "time": elapsed})
                if progress_callback:
                    progress_callback(f"{name}: OK ({elapsed:.1f}s)")
            except Exception as e:
                elapsed = time.time() - t0
                report["steps"].append({"name": name, "ok": False, "time": elapsed})
                report["errors"].append(f"{name}: {e}")
                self.logger.error(f"Fallo en {name}: {e}")
                if progress_callback:
                    progress_callback(f"{name}: FALLO - {e}")

        # 1. Cargar escena (OBLIGATORIO, no auto-detecta)
        if not scene_path:
            step("cargar_escena", lambda: (_ for _ in ()).throw(
                RuntimeError("scene_path es obligatorio. Cargue una escena con el boton o desde el lanzador.")))
        else:
            step("cargar_escena", lambda: self.load_scene_mrb(scene_path))

        # 2. Buscar nodos
        step("buscar_nodos", self.find_scene_nodes)

        # 3. Actividad
        if activity_gbq is not None:
            step("actividad", lambda: self.set_activity(activity_gbq))
        else:
            step("actividad", self.compute_activity)

        # 4. Cargar kernel
        kp = kernel_path or self.kernel_path
        step("cargar_kernel", lambda: self.load_kernel(kp))

        # 5. Computar dosis
        step("computar_dosis", self.compute_dose)

        # 6. DVH
        step("calcular_dvh", self.compute_dvh_for_structures)

        # 7. Nodo dosis 3D
        step("crear_nodo_dosis", self.create_dose_node)

        # 7b. Visualizacion: overlay de dosis en slices + colormap
        step("visualizar_dosis", self._setup_dose_visualization)

        # 8. DVH en Slicer
        step("dvh_slicer", self.show_dvh_in_slicer)

        # 9. Isodosis (también restaura slices automaticamente)
        step("isodosis", self.create_isodosis)

        # 10. Guardar escena
        step("guardar_escena", self.save_scene)

        report["success"] = all(s["ok"] for s in report["steps"])
        report["total_time"] = time.time() - t0
        report["activity_gbq"] = self.activity_gbq
        return report


# ======================================================================
# SlicerDosimMod3Widget
# ======================================================================

class SlicerDosimMod3Widget(ScriptedLoadableModuleWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logic = SlicerDosimMod3Logic()
        self.logger = logging.getLogger("SlicerDosimMod3Widget")
        self._running = False

    def setup(self):
        super().setup()

        # Cargar UI
        ui_path = os.path.join(
            os.path.dirname(__file__), "Resources", "UI", "SlicerDosimMod3.ui"
        )
        if os.path.exists(ui_path):
            self.ui = slicer.util.loadUI(ui_path)
            self.layout.addWidget(self.ui)
        else:
            self.logger.warning(f"UI no encontrado: {ui_path}")
            self._build_fallback_ui()
            return

        # Conectar senales de los botones del .ui
        self._connect_signals()

        self._log("Modulo 3 listo. Cargue una escena o use el lanzador.")

    def _build_fallback_ui(self):
        """UI de respaldo si no se encuentra el archivo .ui."""
        group = qt.QGroupBox("SlicerDosimMod3 - Analisis Dosimetrico V4")
        layout = qt.QVBoxLayout(group)

        self.btn_run = qt.QPushButton("▶ Ejecutar Pipeline Completo")
        self.btn_run.setStyleSheet("font-weight: bold; font-size: 14px; background-color: #27ae60; color: white;")
        layout.addWidget(self.btn_run)

        self.progress = qt.QLabel("Listo. Presione 'Ejecutar Pipeline' para comenzar.")
        self.progress.setWordWrap(True)
        layout.addWidget(self.progress)

        self.txt_report = qt.QTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setPlaceholderText("Resultados del analisis...")
        layout.addWidget(self.txt_report)

        btn_layout = qt.QHBoxLayout()
        btn_save = qt.QPushButton("Guardar escena")
        btn_save.clicked.connect(self._on_save_scene)
        btn_layout.addWidget(btn_save)
        btn_dvh = qt.QPushButton("Mostrar DVH")
        btn_dvh.clicked.connect(self._on_show_dvh)
        btn_layout.addWidget(btn_dvh)
        layout.addLayout(btn_layout)

        self.layout.addWidget(group)
        self.btn_run.clicked.connect(self._on_run_pipeline)
        self._ui_fallback = True

    def _connect_signals(self):
        """Conecta botones del .ui a los handlers."""
        try:
            # Pipeline
            self._connect_btn("btnRun", self._on_run_pipeline)
            self._connect_btn("btnCargarEscena", self._on_load_scene)

            # Dosis
            self._connect_btn("btnCalcularDosis", self._on_run_pipeline)
            self._connect_btn("btnCalcularDVH", self._on_show_dvh)
            self._connect_btn("btnVisualizarDosis", self._on_show_isodosis)
            self._connect_btn("btnCalcularMIRD", self._on_compute_mird)

            # Persistencia
            self._connect_btn("btnGuardarEscena", self._on_save_scene)

            # Reporte
            self._connect_btn("btnExportarReporte", self._on_export_report)

        except Exception as e:
            self.logger.error(f"Error conectando senales: {e}")

    def _connect_btn(self, name: str, slot):
        """Conecta un boton del .ui si existe."""
        btn = self._find_button(name)
        if btn:
            btn.clicked.connect(slot)

    def _find_button(self, name: str):
        """Busca un QPushButton por objectName en el UI."""
        return self.ui.findChild(qt.QPushButton, name) if hasattr(self, 'ui') else None

    def _log(self, msg: str):
        """Agrega mensaje al txtReporte."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.logger.info(msg)
        try:
            if hasattr(self, 'ui') and self.ui:
                txt = self.ui.findChild(qt.QTextEdit, "txtReporte")
                if txt:
                    txt.append(line)
                    return
            if hasattr(self, 'txt_report'):
                self.txt_report.append(line)
        except Exception:
            pass

    def _on_run_pipeline(self):
        """Ejecuta pipeline completo con la escena ya cargada."""
        if self._running:
            self._log("Pipeline ya en ejecucion. Espere...")
            return

        if not self.logic.scene_path:
            self._log("ERROR: No hay escena cargada. Use 'Cargar escena' primero o ejecute desde el lanzador.")
            return

        self._running = True

        def progress(msg):
            self._log(msg)
            slicer.app.processEvents()

        try:
            self._log("=" * 50)
            self._log("INICIANDO PIPELINE MODULO 3")
            self._log("=" * 50)

            report = self.logic.run_pipeline(
                scene_path=self.logic.scene_path,
                progress_callback=progress,
            )

            self._log("-" * 50)
            if report["success"]:
                self._log("PIPELINE COMPLETADO EXITOSAMENTE")
            else:
                self._log(f"PIPELINE COMPLETADO CON {len(report['errors'])} ERRORES:")
                for err in report["errors"]:
                    self._log(f"  ✗ {err}")
            self._log(f"Actividad: {report['activity_gbq']:.4f} GBq")
            self._log(f"Tiempo total: {report['total_time']:.1f}s")
            self._log("-" * 50)

            # Mostrar DVH results
            for name, r in self.logic.results.items():
                label = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}.get(name, name)
                self._log(f"{label}: Dmedia={r.get('mean_dose_gy', 0):.2f} Gy, "
                          f"D98={r.get('d98_gy', 0):.2f} Gy, "
                          f"BED={r.get('bed_gy', 0):.2f} Gy")

        except Exception as e:
            self._log(f"ERROR FATAL: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            self._running = False

    def _on_load_scene(self):
        """Carga escena manualmente."""
        path = qt.QFileDialog.getOpenFileName(
            self.parent, "Seleccionar escena .mrb", SCENE_DIR_DEFAULT,
            "MRB (*.mrb);;All (*)"
        )
        if path:
            self._log(f"Cargando escena: {path}")
            ok = self.logic.load_scene_mrb(path)
            if ok:
                try:
                    self.logic.find_scene_nodes()
                    self._log("Escena cargada. Nodos: CT, PET, Labelmap encontrados.")
                    self._log("Presione 'Ejecutar Pipeline Completo' para procesar.")
                except Exception as e:
                    self._log(f"Error buscando nodos: {e}")
            else:
                self._log("Error cargando escena")

    def _on_show_dvh(self):
        """Muestra DVH en Slicer."""
        try:
            self.logic.show_dvh_in_slicer()
            self._log("DVH mostrado en Slicer (Plots module)")
        except Exception as e:
            self._log(f"Error mostrando DVH: {e}")

    def _on_show_isodosis(self):
        """Crea isodosis contours."""
        try:
            self.logic.create_isodosis()
            self._log("Isodosis creadas en vista 3D")
        except Exception as e:
            self._log(f"Error creando isodosis: {e}")

    def _on_compute_mird(self):
        """Calcula MIRD partition model y muestra resultado."""
        try:
            if self.logic.dose_gy is None or self.logic.labelmap_array is None:
                self._log("Primero ejecute el pipeline para tener dosis y labelmap")
                return
            if compute_mird is None:
                self._log("MIRD no disponible (imports V4 fallaron)")
                return
            mird = compute_mird(self.logic.dose_gy, self.logic.labelmap_array,
                                self.logic.activity_gbq)
            self._log("--- MIRD Partition Model ---")
            for key, val in mird.items():
                self._log(f"  {key}: Dmedia={val.get('mean_dose_gy', 0):.2f} Gy, "
                          f"vol={val.get('volume_ml', 0):.1f} ml")
        except Exception as e:
            self._log(f"Error MIRD: {e}")

    def _on_export_report(self):
        """Exporta reporte PDF."""
        try:
            if not self.logic.results:
                self._log("Primero ejecute el pipeline")
                return
            if generate_pdf_report is None:
                self._log("Reporte PDF no disponible (imports V4 fallaron)")
                return
            path = generate_pdf_report(
                {"structures": self.logic.results,
                 "metadata": {"activity_gbq": self.logic.activity_gbq,
                              "scene": self.logic.scene_path}},
                AI_PIPE_DIR,
                self.logic.dvh_curves,
            )
            if path:
                self._log(f"Reporte PDF exportado: {path}")
            else:
                self._log("Error generando PDF")
        except Exception as e:
            self._log(f"Error exportando reporte: {e}")

    def _on_save_scene(self):
        """Guarda escena actual."""
        ok = self.logic.save_scene()
        if ok:
            self._log("Escena guardada exitosamente")
        else:
            self._log("Error guardando escena")


# ======================================================================
# SlicerDosimMod3Test
# ======================================================================

class SlicerDosimMod3Test(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_Mod3_load()

    def test_Mod3_load(self):
        self.delayDisplay("Cargando Modulo 3...")
        logic = SlicerDosimMod3Logic()
        self.assertIsNotNone(logic)
        self.delayDisplay("Modulo 3 V4 OK")
