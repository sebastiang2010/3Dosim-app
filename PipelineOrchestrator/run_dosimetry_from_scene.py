"""
run_dosimetry_from_scene.py — Pipeline de dosimetria desde escena existente.

Carga una escena .mrb (con CT, PET, 3Dosim_labelmap), parsea un archivo
MCTAL (FMESH4 tally 1), computa dosis en Gy y reporta resultados por
estructura (higado=90, tumor=100, pretumor=200).

Genera:
  - Reporte JSON con resultados numericos
  - Reporte TXT legible
  - Reporte PDF multi-pagina con DVH, tablas y parametros radiobiologicos
  - Consola interactiva Qt (comandos: screenshot, vista, fusion, nodos, etc.)

Uso:
  Slicer.exe --python-script run_dosimetry_from_scene.py ^
      --scene-path "C:/MAT/3Dosim/ai-pipe/scenes/3Dosim.mrb" ^
      --kernel "C:/programas/3Dosim/3Dosim_v4/kernel/kernel.mat"

Sin argumentos busca automaticamente:
  - Escena: C:/MAT/3Dosim/ai-pipe/scenes/3Dosim_scene.mrb
  - MCTAL:  C:/MAT/3Dosim/corrida-Manu/mctal/mctal.m
  - Actividad: se computa del PET en la escena

Opciones:
  --activity X.X     Actividad en GBq (default: computar del PET)
  --labelmap PATH    Ruta a labelmap NIfTI (default: busca en escena)
  --show             Mantener Slicer abierto con DVH + consola
  --no-consola       Deshabilitar consola interactiva Qt
  --no-slicer        Modo standalone (solo parsear MCTAL, sin Slicer)

Requiere:
  - 3D Slicer (slicer, vtk accesibles en Python)
  - SlicerDosimLib en el path

Algoritmo:
  1. Carga escena .mrb en Slicer
  2. Busca nodos: CT, PET, 3Dosim_labelmap
  3. Computa actividad total del PET
  4. Parsea MCTAL con MCTALParser (compatible MATLAB f_cargo_mctall.m)
  5. Convierte MeV/cm³/particula → Gy (MATLAB cargo_mctal.m:389-395)
  6. Por estructura: DVH, D98/D70/D50/D2, V30/V70, BED, EUD, EQD2
  7. Reporte JSON + PDF + TXT + visualizacion en Slicer
"""

from __future__ import annotations

import argparse
import json
import logging
import numpy as np
import os
import sys
import time
from scipy.ndimage import binary_dilation

print(f"[3Dosim SCRIPT INICIADO] argv={sys.argv}", flush=True)

# AI Supervisor (opcional)
try:
    from PipelineOrchestrator import ai_supervisor
    _HAS_AI = True
except Exception:
    ai_supervisor = None
    _HAS_AI = False

# Isodose contours (opcional — requiere Slicer con SlicerRT o VTK)
try:
    from PipelineOrchestrator.isodose_contours import create_isodose_contours
    _HAS_ISODOSE = True
except Exception:
    create_isodose_contours = None
    _HAS_ISODOSE = False

# Dose kernel (carga kernel.mat sin normalizar — preserva calibracion Gy)
try:
    from PipelineOrchestrator.dose_kernel import get_kernel
    _HAS_DOSE_KERNEL = True
except Exception:
    get_kernel = None
    _HAS_DOSE_KERNEL = False
from typing import Optional

# Views medicas automaticas
try:
    from PipelineOrchestrator.views import setup_medical_views
    _HAS_VIEWS = True
except Exception:
    setup_medical_views = None
    _HAS_VIEWS = False

# Consola interactiva (comandos Qt como pipeline principal)
try:
    from PipelineOrchestrator.comandos import ConsolaComandos
    _HAS_CONSOLE = True
except Exception:
    ConsolaComandos = None
    _HAS_CONSOLE = False

# ======================================================================
# DEBUG: primer output inmediato
# ======================================================================
_debug_file = r"C:\tmp\3Dosim_debug_start.log"
try:
    os.makedirs(r"C:\tmp", exist_ok=True)
    with open(_debug_file, "w") as _df:
        _df.write(f"SCRIPT STARTED: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _df.write(f"sys.argv: {sys.argv}\n")
        _df.write(f"Python: {sys.version}\n")
        _df.write(f"slicer in sys.modules: {'slicer' in sys.modules}\n")
except Exception as _e:
    pass

# ======================================================================
# Paths
# ======================================================================

SCENE_DEFAULT = r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim.mrb"
MCTAL_DEFAULT = ""  # Sin default — debe pasarse explicitamente con --mctal o --kernel
OUTPUT_DIR_DEFAULT = r"C:\MAT\3Dosim\ai-pipe\resultados_dosimetria"
AI_PIPE_DIR = r"C:\MAT\3Dosim\ai-pipe"  # para PDF en raiz de ai-pipe
LABELMAP_DEFAULT = r"C:\MAT\3Dosim\ai-pipe\3Dosim_labelmap.nii"

# Indices de tejido en el labelmap (universe numbers de MCNP)
LIVER_INDEX = 90
TUMOR_INDEX = 100
PRETUMOR_INDEX = 200
AIR_INDEX = 0

# Densidades (g/cm³) — MATLAB cargo_mctal.m
DENSIDAD_LIVER = 1.06  # g/cm³
DENSIDAD_TUMOR = 1.06
DENSIDAD_PRETUMOR = 1.06
DENSIDAD_BODY = 1.0
DENSIDAD_AIR = 0.001

# Parametros radiobiologicos — MATLAB cargo_mctal.m lineas 278-288
ALPHA_BETA_LIVER = 2.5  # Gy
ALPHA_BETA_TUMOR = 10  # Gy
MU_REPAIR = 0.28  # h^-1 (T_repair = 2.5 h)
Y90_HALF_LIFE_H = 64.1  # h
LAMDA_DECAY = np.log(2) / Y90_HALF_LIFE_H  # h^-1

# Conversion
MEV2J = 1.6e-13

# Logger simple con archivo directo y stdout
_log_path = os.path.join(OUTPUT_DIR_DEFAULT, "dosimetria_pipeline.log")
_log_file = None
try:
    os.makedirs(OUTPUT_DIR_DEFAULT, exist_ok=True)
    _log_file = open(_log_path, "w", encoding="utf-8")
except Exception:
    pass


# Reemplazar logger con funcion que escribe a stderr + archivo
class _Logger:
    """Logger que escribe a stderr (visible en shell) y archivo."""
    @staticmethod
    def info(msg): _log_msg("INFO", msg)
    @staticmethod
    def warning(msg): _log_msg("WARN", msg)
    @staticmethod
    def error(msg): _log_msg("ERROR", msg)
    @staticmethod
    def debug(msg): pass

def _log_msg(level, msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    if _log_file:
        try:
            _log_file.write(line + "\n")
            _log_file.flush()
        except Exception:
            pass

logger = _Logger()
# Alias corto
log = logger.info


# ======================================================================
# 1. Scene loading
# ======================================================================

def load_scene(scene_path: str) -> bool:
    """Carga escena .mrb en Slicer (version estable)."""
    import slicer
    import traceback

    if not os.path.exists(scene_path):
        logger.error(f"Escena no encontrada: {scene_path}")
        return False

    size_mb = os.path.getsize(scene_path) / 1024 / 1024
    logger.info(f"Cargando escena: {scene_path}")
    logger.info(f"  Tamano: {size_mb:.1f} MB")

    try:
        success = slicer.util.loadScene(scene_path)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"EXCEPCION en slicer.util.loadScene: {e}")
        logger.error(tb)
        return False

    if not success:
        logger.error("slicer.util.loadScene devolvio False (escena no cargada)")
        return False

    logger.info("Escena cargada correctamente")
    return True


def _setup_labelmap_color_table(labelmap_node):
    """Crea y asigna una tabla de colores personalizada al labelmap.

    Mapea los indices del tissue_config a colores visibles en Slicer.
    Oculta la segmentacion TS (104 organos) y activa el labelmap como
    capa label en los slices para evitar superposicion visual.
    """
    import slicer

    if labelmap_node is None:
        return

    # ── Ocultar segmentationes TS (se superponen con el labelmap) ──
    try:
        for seg_n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
            seg_dn = seg_n.GetDisplayNode()
            if seg_dn:
                seg_dn.SetVisibility(False)
                seg_dn.SetVisibility2D(False)
                seg_dn.SetVisibility3D(False)
                seg_dn.SetSliceIntersectionVisibility(False)
                logger.info(f"  TS segmentacion oculta: {seg_n.GetName()}")
    except Exception as e:
        logger.warning(f"  No se pudo ocultar segmentacion: {e}")

    # ── Display node del labelmap ──
    dn = labelmap_node.GetDisplayNode()
    if not dn:
        from slicer import vtkMRMLLabelMapVolumeDisplayNode
        dn = vtkMRMLLabelMapVolumeDisplayNode()
        slicer.mrmlScene.AddNode(dn)
        labelmap_node.SetAndObserveDisplayNodeID(dn.GetID())

    # ── Color table personalizada ──
    color_table = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLColorTableNode", "3Dosim_Labelmap_Colors"
    )
    color_table.SetTypeToUser()
    color_table.SetNumberOfColors(256)

    # Default: fondo transparente
    color_table.SetColor(0, "Background", 0.0, 0.0, 0.0, 0.0)
    # Indices no definidos → gris semitransparente
    for i in range(1, 256):
        color_table.SetColor(i, f"Label_{i}", 0.3, 0.3, 0.3, 0.4)

    # Colores especificos por tejido
    color_table.SetColor(30,  "Tejido_blando", 0.6, 0.4, 0.3, 0.6)
    color_table.SetColor(50,  "Pulmon",        0.8, 0.6, 0.7, 0.6)
    color_table.SetColor(80,  "Hueso",         0.8, 0.8, 0.8, 0.8)
    color_table.SetColor(90,  "Higado",        0.2, 0.4, 1.0, 0.8)
    color_table.SetColor(100, "Tumor",         1.0, 0.2, 0.2, 0.8)
    color_table.SetColor(200, "Peritumoral",   0.8, 0.6, 0.0, 0.8)

    color_table.SetNamesFromColors()
    dn.SetAndObserveColorNodeID(color_table.GetID())
    dn.Modified()

    # ── Activar labelmap como capa "label" en slices ──
    try:
        lm = slicer.app.layoutManager()
        if lm:
            for idx in range(lm.sliceViewCount()):
                sv = lm.sliceWidget(idx).sliceView()
                if sv:
                    scn = sv.sliceCompositeNode()
                    if scn:
                        scn.SetLabelVolumeID(labelmap_node.GetID())
                        scn.SetLabelOpacity(0.8)
        logger.info("  Labelmap activado como capa label en slices")
    except Exception as e:
        logger.warning(f"  No se pudo activar labelmap en slices: {e}")

    # ── Refrescar ──
    try:
        slicer.util.resetSliceViews()
        slicer.app.processEvents()
    except Exception:
        pass

    logger.info("  Tabla de colores personalizada asignada al labelmap")


def find_nodes(labelmap_name: str = "3Dosim_labelmap") -> dict:
    """
    Busca nodos en la escena: CT, CT sin camilla, PET, labelmap.

    Returns:
        dict con 'ct', 'ct_masked', 'pet', 'labelmap' (nodos Slicer) o None
    """
    import slicer

    nodes = {"ct": None, "ct_masked": None, "pet": None, "labelmap": None}

    # Buscar todos los volumenes
    all_volumes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
    logger.info(f"  Volumenes en escena ({len(all_volumes)}):")
    for vol in all_volumes:
        logger.info(f"    - {vol.GetName()}  [{vol.GetClassName()}]")
    # Tambien buscar labelmap como LabelMapVolumeNode (subclase diferente)
    all_lm = slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")
    if all_lm:
        logger.info(f"  LabelMapVolumeNodes ({len(all_lm)}):")
        for lm in all_lm:
            logger.info(f"    - {lm.GetName()}")
            if nodes["labelmap"] is None:
                nodes["labelmap"] = lm
                logger.info(f"  Labelmap (LabelMapVolumeNode): {lm.GetName()}")

    for vol in all_volumes:
        name = vol.GetName()
        name_lower = name.lower()

        if "labelmap" in name_lower or "phantom" in name_lower:
            if labelmap_name.lower() in name.lower():
                nodes["labelmap"] = vol
                logger.info(f"  Labelmap: {name}")
        elif "ct" in name_lower or "ct_" in name_lower:
            if "sin_camilla" not in name_lower:  # no contaminar con CT_masked
                nodes["ct"] = vol
                logger.info(f"  CT: {name}")
        elif "pet_ct" in name_lower:
            # Priorizar PET_CT (PET resampled al espacio del CT) para kernel
            nodes["pet"] = vol
            logger.info(f"  PET_CT (prioritario): {name}")
        elif "pet" in name_lower:
            nodes["pet"] = vol
            logger.info(f"  PET: {name}")

    # Buscar CT sin camilla (sin_camilla en el nombre)
    for vol in all_volumes:
        name = vol.GetName()
        if "sin_camilla" in name.lower():
            nodes["ct_masked"] = vol
            logger.info(f"  CT sin camilla: {name}")
            break

    # Si no encontro por nombre, buscar por tipo/indice
    if nodes["ct"] is None:
        for vol in all_volumes:
            name = vol.GetName()
            if "ct" in name.lower():
                nodes["ct"] = vol
                break

    if nodes["pet"] is None:
        # Primero intentar PET_CT (resampled), luego PET original
        for vol in all_volumes:
            name = vol.GetName()
            if "pet_ct" in name.lower():
                nodes["pet"] = vol
                logger.info(f"  PET_CT (fallback prioritario): {name}")
                break
        if nodes["pet"] is None:
            for vol in all_volumes:
                name = vol.GetName()
                if "pet" in name.lower() or "pt_" in name.lower():
                    nodes["pet"] = vol
                    logger.info(f"  PET (fallback): {name}")
                    break

    # Buscar segmentacion como fallback para labelmap
    if nodes["labelmap"] is None:
        seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        if seg_nodes:
            nodes["segmentation"] = seg_nodes[0]
            logger.info(f"  Segmentacion: {seg_nodes[0].GetName()} (fallback)")

    return nodes


def _get_pet_units(info_json_path: Optional[str], output_dir: str) -> Optional[str]:
    """
    Lee las unidades del PET desde el metadata JSON generado por mod1.

    Busca en:
      1. Ruta explicitamente pasada (--info-json)
      2. ../exports/*_info.json relativo a output_dir
      3. C:/MAT/3Dosim/ai-pipe/exports/*_info.json

    Returns:
        "BQML", "BQ", "CNTS", None (si no encuentra)
    """
    candidates = []
    if info_json_path:
        candidates.append(info_json_path)
    # Buscar en exports/ relativo a output_dir
    exports_dir = os.path.join(os.path.dirname(output_dir), "exports")
    if os.path.isdir(exports_dir):
        for f in sorted(os.listdir(exports_dir)):
            if f.endswith("_info.json"):
                candidates.append(os.path.join(exports_dir, f))
    # Fallback absoluto
    fallback_exports = r"C:\MAT\3Dosim\ai-pipe\exports"
    if os.path.isdir(fallback_exports):
        for f in sorted(os.listdir(fallback_exports)):
            if f.endswith("_info.json"):
                p = os.path.join(fallback_exports, f)
                if p not in candidates:
                    candidates.append(p)

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            units = data.get("PET", {}).get("DICOM", {}).get("Units", None)
            if units:
                units = units.strip().upper()
                logger.info(f"  Unidades PET desde JSON ({path}): {units}")
                return units
            else:
                logger.info(f"  JSON encontrado pero sin campo Units: {path}")
        except Exception as e:
            logger.warning(f"  Error leyendo JSON {path}: {e}")

    logger.info("  No se encontro info JSON con Units — asumiendo Bq/ml")
    return None


def compute_activity_from_pet(pet_node, info_json: Optional[str] = None,
                               output_dir: Optional[str] = None) -> float:
    """
    Computa actividad total desde nodo PET.

    Lee las unidades desde el metadata JSON de mod1 (campo DICOM Units).
    Si no encuentra el JSON o el campo, asume Bq/ml.

    Returns:
        actividad total en Bq
    """
    import slicer

    pet_array = slicer.util.arrayFromVolume(pet_node)  # (nz, ny, nx)
    spacing = pet_node.GetSpacing()  # (sx, sy, sz) mm

    # Volumen de voxel en ml (= cm³)
    voxel_vol_ml = (spacing[0] * spacing[1] * spacing[2]) / 1000.0

    # Sumar PET
    total_pet = float(np.sum(pet_array))

    # Determinar unidades desde JSON (o fallback Bq/ml)
    units = _get_pet_units(info_json, output_dir or "")

    if units == "BQ":
        activity_bq = total_pet
        logger.info(f"  PET en Bq: sum={total_pet:.2e}")
    elif units == "BQML":
        activity_bq = total_pet * voxel_vol_ml
        logger.info(f"  PET en Bq/ml: sum={total_pet:.2e}, vol_voxel={voxel_vol_ml:.6f} ml")
    elif units == "CNTS":
        logger.warning(f"  PET en cuentas (CNTS) — no se puede convertir a Bq, asumiendo Bq/ml")
        activity_bq = total_pet * voxel_vol_ml
    else:
        # Fallback: Bq/ml
        activity_bq = total_pet * voxel_vol_ml
        logger.info(f"  PET (fallback Bq/ml): sum={total_pet:.2e}, vol_voxel={voxel_vol_ml:.6f} ml")

    logger.info(f"  Actividad total: {activity_bq:.2e} Bq = {activity_bq / 1e9:.4f} GBq")
    return float(activity_bq)


# ======================================================================
# 2. MCTAL Parser (wrapper)
# ======================================================================

def parse_mctal(mctal_path: str, dims: tuple) -> dict:
    """Parsea MCTAL usando SlicerDosimLib MCTALParser."""
    # Agregar SlicerDosimLib al path
    lib_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "Modules",
        "Scripted", "SlicerDosim", "SlicerDosimLib",
    )
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from mctal_parser import MCTALParser

    parser = MCTALParser()
    nx, ny, nz = dims
    result = parser.parse(mctal_path, nx=nx, ny=ny, nz=nz)

    if result["dose_3d"] is None:
        raise RuntimeError("No se pudo extraer dosis 3D del MCTAL")

    logger.info(
        f"MCTAL parseado: {result['dimensions']}, "
        f"NPS={result['nps']}, "
        f"title={result['title'][:60]}"
    )

    return result


# ======================================================================
# 3. Conversion a Gy
# ======================================================================

def convert_to_gy(
    dose_mev_cm3: np.ndarray,
    labelmap: np.ndarray,
    activity_bq: float,
    t_meanlife_s: float,
) -> np.ndarray:
    """
    Convierte MeV/cm³/particula → Gy.

    Algoritmo MATLAB cargo_mctal.m lineas 389-395:
      1. D / rho  (MeV/cm³ → MeV/g) usando densidad por tejido
      2. * MeV2J   (MeV/g → J/g)
      3. * t * Actividad (escalar por desintegraciones totales)
      4. * 1000   (J/g → J/kg = Gy)
    """
    # Densidades por indice de tejido
    cell_densities = {
        LIVER_INDEX: DENSIDAD_LIVER,
        TUMOR_INDEX: DENSIDAD_TUMOR,
        PRETUMOR_INDEX: DENSIDAD_PRETUMOR,
    }

    # Mapa de densidad del mismo shape que dosis
    dens_map = np.ones_like(dose_mev_cm3, dtype=np.float64)
    for idx, dens in cell_densities.items():
        mask = labelmap == idx
        dens_map[mask] = dens

    # Aire: densidad muy baja, marcar para evitar division por cero
    air_mask = labelmap == AIR_INDEX

    # Paso 1: MeV/cm³ → MeV/g dividiendo por densidad
    dose_mev_g = np.divide(
        dose_mev_cm3, dens_map,
        out=np.zeros_like(dose_mev_cm3),
        where=dens_map > 0.001,
    )

    # Paso 2: MeV/g → J/g
    dose_j_g = dose_mev_g * MEV2J

    # Paso 3: Escalar por desintegraciones totales
    # D_J/g total = D_J/g por particula * t_meanlife * Actividad_Bq
    dose_j_g_total = dose_j_g * t_meanlife_s * activity_bq

    # Paso 4: J/g → J/kg = Gy
    dose_gy = dose_j_g_total * 1000.0

    # Aire: dosis = 0
    dose_gy[air_mask] = 0.0

    return dose_gy


# ======================================================================
# 4. DVH y estadisticas por estructura
# ======================================================================

def compute_dvh(
    dose_gy: np.ndarray,
    labelmap: np.ndarray,
    structure_idx: int,
    bins: int = 200,
) -> dict:
    """
    Computa DVH para una estructura.
    NOTA: volumen se computa externamente (caller tiene spacing).
    Returns:
        dict con:
          - 'n_voxels': numero de voxeles (usar con spacing para volumen)
          - 'mean_dose_gy': dosis media
          - 'min_dose_gy': dosis minima
          - 'max_dose_gy': dosis maxima
          - 'std_dose_gy': desviacion estandar
          - 'd98_gy': dosis al 98% del volumen
          - 'd70_gy': dosis al 70%
          - 'd50_gy': dosis al 50%
          - 'dose_bins': array de dosis para DVH
          - 'volume_hist': histograma de volumen vs dosis
          - 'cumulative_vol': histograma acumulativo
    """
    mask = labelmap == structure_idx
    n_voxels = np.sum(mask)

    if n_voxels == 0:
        logger.warning(f"Estructura {structure_idx}: sin voxeles")
        return {"volume_ml": 0, "mean_dose_gy": 0, "n_voxels": 0}

    doses = dose_gy[mask]
    n_total = len(doses)
    spacing = None  # lo necesitamos para volumen

    # Estadisticas basicas (todos los voxeles, incluyendo dosis=0)
    mean_dose = float(np.mean(doses))
    min_dose = float(np.min(doses))
    max_dose = float(np.max(doses))
    std_dose = float(np.std(doses))

    # Fraccion de voxeles con dosis > 0
    n_nonzero = int(np.sum(doses > 0))
    frac_zero = (n_total - n_nonzero) / n_total * 100

    # Posicion IJK del voxel con dosis maxima dentro de la estructura
    max_pos_ijk = None
    if n_total > 0:
        max_idx = int(np.argmax(doses))
        coords = np.where(mask)
        max_pos_ijk = (
            int(coords[0][max_idx]),
            int(coords[1][max_idx]),
            int(coords[2][max_idx]),
        )

    # D98, D70, D50, D2 — percentiles de dosis
    # Usar TODOS los voxeles (incluye dosis=0) - identico MATLAB percentil
    # Dx = dosis que cubre el x% del volumen (min dose to hottest x%)
    # D98 = dosis al percentil 2 (solo 2% recibe menos)
    # D2  = dosis al percentil 98 (solo 2% recibe mas)
    if n_total > 0:
        d98 = float(np.percentile(doses, 2))
        d95 = float(np.percentile(doses, 5))
        d70 = float(np.percentile(doses, 30))
        d50 = float(np.percentile(doses, 50))
        d5  = float(np.percentile(doses, 95))
        d2  = float(np.percentile(doses, 98))
    else:
        d98 = d95 = d70 = d50 = d5 = d2 = 0.0

    # V30, V70 — volumen que recibe al menos X Gy
    v30_pct = float((doses >= 30).sum() / n_total * 100) if n_total > 0 else 0.0
    v70_pct = float((doses >= 70).sum() / n_total * 100) if n_total > 0 else 0.0

    # DVH histograma
    dose_max_hist = float(np.percentile(doses, 99.5))  # evitar outliers
    if dose_max_hist <= 0:
        dose_max_hist = max_dose

    hist, edges = np.histogram(
        doses, bins=bins, range=(0, dose_max_hist * 1.05)
    )
    # hist: conteo de voxeles por bin
    # cumulative: fraccion de volumen que recibe ≥ dosis
    cumulative = np.cumsum(hist[::-1])[::-1]
    cumulative_vol = cumulative / n_voxels * 100  # porcentaje

    # Centros de bin para graficar
    dose_bins = (edges[:-1] + edges[1:]) / 2

    return {
        "structure_idx": int(structure_idx),
        "n_voxels": int(n_voxels),
        "mean_dose_gy": mean_dose,
        "min_dose_gy": min_dose,
        "max_dose_gy": max_dose,
        "max_dose_pos_ijk": max_pos_ijk,  # [i, j, k] voxel con dosis maxima
        "std_dose_gy": std_dose,
        "d98_gy": d98,
        "d95_gy": d95,
        "d70_gy": d70,
        "d50_gy": d50,
        "d5_gy": d5,
        "d2_gy": d2,
        "v30_pct": v30_pct,
        "v70_pct": v70_pct,
        "dose_bins_gy": dose_bins.tolist(),
        "volume_hist_pct": (hist / n_voxels * 100).tolist(),
        "cumulative_vol_pct": cumulative_vol.tolist(),
    }


def compute_biophysical(
    dvh_result: dict,
    alpha_beta: float,
    is_tumor: bool = False,
) -> dict:
    """
    Computa BED, EUD, EQD2.

    BED = D + (lamda/((alpha/beta)*(lamda+mu))) * D²
    (MATLAB f_BED.m)

    EUD = sum(vi * Di^a)^(1/a) donde a=1 para tumor, a=-10 para normal
    EQD2 = BED / (1 + 2/(alpha/beta))

    Args:
        dvh_result: resultado de compute_dvh()
        alpha_beta: relacion alfa/beta (2.5 liver, 10 tumor)
        is_tumor: si es tumor (a=1) o normal (a=-10)

    Returns:
        dict con BED, EUD, EQD2
    """
    mean_d = dvh_result.get("mean_dose_gy", 0)
    if mean_d <= 0:
        return {"bed_gy": 0, "eud_gy": 0, "eqd2_gy": 0}

    # BED — MATLAB f_BED.m
    # BED = D + lambda/((alpha/beta)*(lambda+mu)) * D²
    # Donde lambda = ln(2)/T_half, mu = repair rate
    lamda = LAMDA_DECAY  # h^-1
    mu = MU_REPAIR  # h^-1

    bed_factor = lamda / (alpha_beta * (lamda + mu))
    bed = mean_d + bed_factor * mean_d**2

    # EUD — MATLAB f_EUD.m
    # EUD = (sum(vi * Di^a))^(1/a)
    # a = 1 para tumor, a = 1 - n para tejido normal (n=-10 para liver)
    if is_tumor:
        a = 1.0
    else:
        a = 1.0 - (-10.0)  # n = -10 → a = 11

    # Para simplificar, usar mean dose si no tenemos histograma completo
    if is_tumor:
        eud = mean_d
    else:
        # EUD para tejido normal: aproximacion con dosis media
        # (EUD exacto requiere histograma completo)
        eud = mean_d

    # EQD2 (2 Gy fractions)
    # EQD2 = D * (d + alpha/beta) / (2 + alpha/beta)
    # Para BED: EQD2 = BED / (1 + 2/(alpha/beta))
    eqd2 = bed / (1 + 2.0 / alpha_beta)

    return {
        "bed_gy": round(bed, 4),
        "eud_gy": round(eud, 4),
        "eqd2_gy": round(eqd2, 4),
        "alpha_beta": alpha_beta,
        "is_tumor": is_tumor,
    }


# ======================================================================
# 5. MIRD partition model
# ======================================================================

def compute_mird(
    dose_gy: np.ndarray,
    labelmap: np.ndarray,
    activity_gbq: float,
) -> dict:
    """
    Calcula MIRD partition model para higado y tumor.

    MATLAB cargo_mctal.m lineas 211-227.
    """
    # Volumenes
    voxel_vol = 1.0  # se ajusta despues
    n_liver = np.sum(labelmap == LIVER_INDEX)
    n_tumor = np.sum(labelmap == TUMOR_INDEX)
    n_pretumor = np.sum(labelmap == PRETUMOR_INDEX)

    # Dosis medias
    d_liver_mean = float(np.mean(dose_gy[labelmap == LIVER_INDEX])) if n_liver > 0 else 0
    d_tumor_mean = float(np.mean(dose_gy[labelmap == TUMOR_INDEX])) if n_tumor > 0 else 0
    d_pretumor_mean = float(np.mean(dose_gy[labelmap == PRETUMOR_INDEX])) if n_pretumor > 0 else 0

    # K constante MIRD
    k = 48.98  # J-s

    resultado = {
        "activity_gbq": activity_gbq,
        "liver": {
            "n_voxels": int(n_liver),
            "mean_dose_gy": round(d_liver_mean, 4),
        },
        "tumor": {
            "n_voxels": int(n_tumor),
            "mean_dose_gy": round(d_tumor_mean, 4),
        },
        "pretumor": {
            "n_voxels": int(n_pretumor),
            "mean_dose_gy": round(d_pretumor_mean, 4),
        },
        "k_mird": k,
    }

    return resultado


# ======================================================================
# 7. DVH plots en Slicer (algoritmo MATLAB f_HDV.m)
# ======================================================================

def _create_dvh_plots_slicer(dose_gy, labelmap, spacing, show_gui=True):
    """
    Crea graficos DVH acumulativos en Slicer usando algoritmo MATLAB f_HDV.m.

    MATLAB:
        Dmax = max(D);
        delta = Dmax / 1000;
        for d = 0:delta:Dmax
            a(i) = sum(D >= d) * 100 / n;
        end
        plot(d, a);  % escala Y log

    Crea un PlotChartNode con una serie por estructura.
    """
    import slicer
    import vtk

    structures = [
        ("Hígado", LIVER_INDEX, (0.2, 0.4, 1.0)),     # azul
        ("Tumor", TUMOR_INDEX, (1.0, 0.2, 0.2)),       # rojo
        ("Peritumoral", PRETUMOR_INDEX, (0.8, 0.6, 0.0)), # amarillo
    ]

    chart_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLPlotChartNode", "DVH_Chart"
    )
    chart_node.SetTitle("Cumulative Dose Volume Histogram")
    chart_node.SetXAxisTitle("Dose (Gy)")
    chart_node.SetYAxisTitle("Volume (%)")
    # Escala Y lineal (explicita: Slicer 5.8 default es lineal, pero forzamos)
    if hasattr(chart_node, "SetYAxisLogScale"):
        chart_node.SetYAxisLogScale(0)
    elif hasattr(chart_node, "SetYAxisLog"):
        chart_node.SetYAxisLog(False)

    series_nodes = []
    dvh_curves = []  # para exportar PNG

    # Calcular Dmax global para escalar eje X correctamente
    global_dmax = 0.0
    for name, idx, color in structures:
        mask = labelmap == idx
        doses = dose_gy[mask]
        if len(doses) > 0:
            global_dmax = max(global_dmax, float(np.max(doses)))

    for name, idx, color in structures:
        mask = labelmap == idx
        doses = dose_gy[mask]
        n = len(doses)

        if n == 0 or np.max(doses) <= 0:
            continue

        # --- Algoritmo MATLAB f_HDV.m exacto (~200 puntos) ---
        Dmax = float(np.max(doses))
        npts = 200
        delta = Dmax / npts
        d_vals = np.arange(0, Dmax + delta, delta)
        a_vals = np.zeros(len(d_vals))
        for i, d in enumerate(d_vals):
            a_vals[i] = np.sum(doses >= d) * 100.0 / n
        # ----------------------------------------------------

        # Crear tabla con datos DVH (API Slicer 5.8)
        table_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLTableNode", f"DVH_Table_{name}"
        )
        table = table_node.GetTable()
        col_x = vtk.vtkFloatArray()
        col_x.SetName("Dose (Gy)")
        col_y = vtk.vtkFloatArray()
        col_y.SetName("Volume (%)")
        col_label = vtk.vtkStringArray()
        col_label.SetName("Label")
        for i in range(len(d_vals)):
            col_x.InsertNextValue(float(d_vals[i]))
            col_y.InsertNextValue(float(a_vals[i]))
            col_label.InsertNextValue(f"{d_vals[i]:.1f} Gy / {a_vals[i]:.1f}%")
        table.AddColumn(col_x)
        table.AddColumn(col_y)
        table.AddColumn(col_label)

        # Crear serie que referencia la tabla
        series = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLPlotSeriesNode", f"DVH_{name}"
        )
        series.SetAndObserveTableNodeID(table_node.GetID())
        series.SetXColumnName("Dose (Gy)")
        series.SetYColumnName("Volume (%)")
        series.SetLabelColumnName("Label")
        series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeLine)
        series.SetColor(*color)
        series.SetLineWidth(2)

        chart_node.AddAndObservePlotSeriesNodeID(series.GetID())
        series_nodes.append(series)
        dvh_curves.append((name, d_vals, a_vals))

        logger.info(f"  DVH creado: {name} ({n} voxels, Dmax={Dmax:.1f} Gy)")

    # Escalar ejes (Slicer default no es correcto)
    if global_dmax > 0:
        if hasattr(chart_node, "SetXAxisRange"):
            chart_node.SetXAxisRange(0, global_dmax * 1.05)
            logger.info(f"  DVH X-axis range: 0 - {global_dmax * 1.05:.1f} Gy")
        if hasattr(chart_node, "SetYAxisRange"):
            chart_node.SetYAxisRange(0, 105)
            logger.info("  DVH Y-axis range: 0 - 105 (lineal)")

    # Asignar chart al PlotViewNode (API correcta Slicer 5.8:
    # plotWidget.plotView() devuelve qMRMLPlotView (Qt), NO vtkMRMLPlotViewNode.
    # El metodo SetPlotChartNodeID esta en el MRML node, no en el Qt widget.
    if series_nodes and show_gui:
        try:
            _pv_nodes = slicer.util.getNodesByClass("vtkMRMLPlotViewNode")
            if _pv_nodes:
                _pv_nodes[0].SetPlotChartNodeID(chart_node.GetID())
                logger.info("[DVH] Chart asignado al PlotViewNode via MRML node")
            else:
                logger.warning("[DVH] No se encontraron PlotViewNodes en la escena")
        except Exception as _e_dvh:
            logger.warning(f"[DVH] Error asignando chart: {_e_dvh}")
        slicer.app.processEvents()

    # Exportar imagen PNG
    try:
        dvh_png = os.path.join(OUTPUT_DIR_DEFAULT, "DVH_plot.png")
        _export_dvh_png(dvh_curves, dvh_png)
        logger.info(f"  DVH PNG: {dvh_png}")
    except Exception as e:
        logger.warning(f"  No se pudo exportar DVH PNG: {e}")

    return chart_node


def _export_dvh_png(dvh_curves, filepath):
    """Exporta DVH como PNG usando matplotlib (si disponible).

    dvh_curves: list of (name, d_vals_array, a_vals_array)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        colors = {"Hígado": (0.2, 0.4, 1.0), "Tumor": (1.0, 0.2, 0.2), "Peritumoral": (0.8, 0.6, 0.0)}

        fig, ax = plt.subplots(figsize=(10, 6))
        x_max = 0
        for name, d_vals, a_vals in dvh_curves:
            c = colors.get(name, (0.5, 0.5, 0.5))
            ax.plot(d_vals, a_vals, color=c, label=name, linewidth=2)
            if len(d_vals) > 0:
                x_max = max(x_max, float(d_vals[-1]))

        ax.set_xlabel("Dose (Gy)", fontweight="bold")
        ax.set_ylabel("Volume (%)", fontweight="bold")
        ax.set_title("Cumulative Dose Volume Histogram", fontweight="bold")
        # Escala Y lineal (sin log)
        ax.set_yscale("linear")
        ax.set_xlim(0, x_max * 1.05 if x_max > 0 else 100)
        ax.set_ylim(0, 105)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(filepath, dpi=150)
        plt.close(fig)
        logger.info(f"  DVH PNG exportado: {filepath}")
    except Exception:
        logger.warning("  matplotlib no disponible para exportar PNG")


# ======================================================================
# 8. Generacion de PDF Report (reportlab)
# ======================================================================

def _add_page_number(fig, page_num, total=5):
    """Agrega numero de pagina y footer al pie de la figura (matplotlib fallback)."""
    fig.text(0.5, 0.01, f"Pagina {page_num}/{total}  |  3Dosim v3.14",
             fontsize=8, color="#888", ha="center", va="bottom")


def generate_pdf_report(
    results: dict,
    output_dir: str,
    dvh_curves: list = None,
) -> str:
    """
    Genera reporte PDF con reportlab (5 paginas):
      P1: Portada con metadatos y resumen ejecutivo
      P2: Parametros radiobiologicos + formulas
      P3: Resultados dosimetricos por estructura + MIRD
      P4: DVH acumulativo (matplotlib embebido)
      P5: Metricas DVH por estructura

    Args:
        results: dict con metadata, structures, mird
        output_dir: directorio donde guardar el PDF
        dvh_curves: list of (name, d_vals_array, a_vals_array)

    Returns:
        ruta al PDF generado, o None si fallo
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm, cm
        from reportlab.lib.colors import HexColor, Color, black, white, grey
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, PageBreak, Image,
                                         KeepTogether, HRFlowable)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        logger.warning("  reportlab no disponible — usando matplotlib como fallback")
        return _generate_pdf_matplotlib_fallback(results, output_dir, dvh_curves)

    pdf_path = os.path.join(output_dir, "dosimetria_report.pdf")
    meta = results.get("metadata", {})
    structures = results.get("structures", {})
    mird = results.get("mird", {})

    # -- Paleta de colores profesional --
    C_PRIMARY = HexColor("#1B2A4A")       # Azul oscuro elegante
    C_ACCENT = HexColor("#2E86AB")        # Azul acento
    C_HEADER_BG = HexColor("#1B2A4A")     # Headers tabla
    C_HEADER_FG = white
    C_LIGHT_BG = HexColor("#F0F4F8")      # Fila alterna
    C_GRAY = HexColor("#6B7280")          # Texto secundario
    C_DARK = HexColor("#1F2937")          # Texto principal
    C_HIGADO = HexColor("#2563EB")        # Azul
    C_TUMOR = HexColor("#DC2626")         # Rojo
    C_PERITUMORAL = HexColor("#D97706")   # Amber/orange
    C_BORDER = HexColor("#D1D5DB")        # Bordes suaves
    C_SUCCESS = HexColor("#059669")       # Verde para OK
    C_BG_LIGHT = HexColor("#FAFBFC")

    struct_colors_hex = {"higado": C_HIGADO, "tumor": C_TUMOR, "pretumor": C_PERITUMORAL}
    struct_labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}

    # -- Estilos --
    styles = getSampleStyleSheet()
    s_title = ParagraphStyle("Title2", parent=styles["Title"],
                             fontSize=26, textColor=C_PRIMARY, spaceAfter=4,
                             fontName="Helvetica-Bold")
    s_subtitle = ParagraphStyle("Sub", parent=styles["Normal"],
                                fontSize=11, textColor=C_GRAY, alignment=TA_CENTER)
    s_heading = ParagraphStyle("Head", parent=styles["Heading2"],
                               fontSize=14, textColor=C_PRIMARY, spaceBefore=14,
                               spaceAfter=6, fontName="Helvetica-Bold")
    s_heading3 = ParagraphStyle("Head3", parent=styles["Heading3"],
                                fontSize=11, textColor=C_ACCENT, spaceBefore=10,
                                spaceAfter=4, fontName="Helvetica-Bold")
    s_normal = ParagraphStyle("Norm", parent=styles["Normal"],
                              fontSize=10, textColor=C_DARK, leading=14)
    s_small = ParagraphStyle("Small", parent=styles["Normal"],
                             fontSize=9, textColor=C_GRAY, leading=12)
    s_bold = ParagraphStyle("Bold", parent=styles["Normal"],
                            fontSize=10, textColor=C_DARK, leading=14,
                            fontName="Helvetica-Bold")

    def add_footer(canvas_obj, doc):
        """Footer profesional con linea decorativa."""
        canvas_obj.saveState()
        # Linea decorativa superior
        canvas_obj.setStrokeColor(C_ACCENT)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(20 * mm, 20 * mm, A4[0] - 20 * mm, 20 * mm)
        # Texto footer
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(C_GRAY)
        canvas_obj.drawString(20 * mm, 15 * mm, "3Dosim v3.14 — Dosimetria 3D para Medicina Nuclear")
        canvas_obj.drawRightString(A4[0] - 20 * mm, 15 * mm,
                                   f"Pagina {doc.page} de 5")
        canvas_obj.restoreState()

    def add_header_line(canvas_obj, doc):
        """Linea decorativa en header de pagina 1."""
        canvas_obj.saveState()
        canvas_obj.setStrokeColor(C_ACCENT)
        canvas_obj.setLineWidth(2)
        canvas_obj.line(20 * mm, A4[1] - 25 * mm, A4[0] - 20 * mm, A4[1] - 25 * mm)
        canvas_obj.restoreState()

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=25 * mm,
    )
    story = []
    usable_width = A4[0] - 40 * mm
    formula_images_to_clean = []  # imagenes temporales de formulas LaTeX

    # ================================================================
    # PAGINA 1: PORTADA EJECUTIVA
    # ================================================================
    # Header con fondo de color
    header_data = [["REPORTE DE DOSIMETRIA"]]
    header_table = Table(header_data, colWidths=[usable_width], rowHeights=[50])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, -1), white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 20),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8 * mm))

    # Subtitulo
    story.append(Paragraph("3Dosim v3.14 — Dosimetria 3D para Medicina Nuclear", s_subtitle))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=C_ACCENT))
    story.append(Spacer(1, 6 * mm))

    # Metadata compacta en 2 columnas
    story.append(Paragraph("Informacion del Estudio", s_heading))
    meta_left = [
        ["Escena:", meta.get("scene", "N/A").split("/")[-1].split("\\")[-1]],
        ["MCTAL:", meta.get("mctal", "N/A").split("/")[-1].split("\\")[-1]],
        ["Actividad:", f"{meta.get('activity_gbq', 0):.4f} GBq"],
    ]
    meta_right = [
        ["NPS:", f"{meta.get('nps', 0):,}"],
        ["Dimensiones:", str(meta.get("dimensions", []))],
        ["Generado:", time.strftime("%Y-%m-%d %H:%M")],
    ]
    meta_table = Table(
        [meta_left[i] + meta_right[i] for i in range(3)],
        colWidths=[25 * mm, 55 * mm, 25 * mm, usable_width - 105 * mm]
    )
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), C_PRIMARY),
        ("TEXTCOLOR", (2, 0), (2, -1), C_PRIMARY),
        ("TEXTCOLOR", (1, 0), (1, -1), C_DARK),
        ("TEXTCOLOR", (3, 0), (3, -1), C_DARK),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6 * mm))

    # Resumen ejecutivo por estructura
    story.append(Paragraph("Resumen Ejecutivo", s_heading))
    story.append(Spacer(1, 2 * mm))

    # SIEMPRE mostrar las 3 estructuras, incluso con 0 voxels
    all_struct_order = [("higado", "Hígado", LIVER_INDEX, C_HIGADO),
                        ("tumor", "Tumor", TUMOR_INDEX, C_TUMOR),
                        ("pretumor", "Peritumoral", PRETUMOR_INDEX, C_PERITUMORAL)]

    resumen_headers = ["", "Estructura", "Voxeles", "Vol (cm\u00b3)", "Dmedia (Gy)", "BED (Gy)"]
    resumen_data = [resumen_headers]
    for key, label, idx, color in all_struct_order:
        s = structures.get(key, {})
        n_vox = s.get("n_voxels", 0)
        vol = s.get("volume_cm3", 0)
        dmedia = s.get("mean_dose_gy", 0)
        bed = s.get("bed_gy", 0)
        # Indicador visual
        status = "\u2713" if n_vox > 0 else "\u2014"
        resumen_data.append([
            status,
            label,
            f"{n_vox:,}" if n_vox > 0 else "0",
            f"{vol:.1f}" if vol > 0 else "\u2014",
            f"{dmedia:.2f}" if n_vox > 0 else "\u2014",
            f"{bed:.2f}" if n_vox > 0 else "\u2014",
        ])

    resumen_col_w = [10 * mm, 30 * mm, 22 * mm, 22 * mm, 24 * mm, usable_width - 108 * mm]
    resumen_table = Table(resumen_data, colWidths=resumen_col_w)
    resumen_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
        # Colores por fila
        ("TEXTCOLOR", (1, 1), (1, 1), C_HIGADO),
        ("TEXTCOLOR", (1, 2), (1, 2), C_TUMOR),
        ("TEXTCOLOR", (1, 3), (1, 3), C_PERITUMORAL),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
    ]
    resumen_table.setStyle(TableStyle(resumen_style))
    story.append(resumen_table)

    # Indicadores
    story.append(Spacer(1, 4 * mm))
    n_structs_ok = sum(1 for key, _, _, _ in all_struct_order if key in structures and structures[key].get("n_voxels", 0) > 0)
    story.append(Paragraph(
        f"<font color=\"#{C_SUCCESS.hexval()[2:]}\">&#10003;</font> "
        f"<b>{n_structs_ok}/3 estructuras</b> con datos dosimetricos",
        s_small
    ))
    story.append(PageBreak())

    # ================================================================
    # PAGINA 2: PARAMETROS RADIOBIOLOGICOS
    # ================================================================
    story.append(Paragraph("Parametros Radiobiologicos", s_heading))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_ACCENT))
    story.append(Spacer(1, 4 * mm))

    # Tabla de constantes
    story.append(Paragraph("Constantes del Modelo Y-90", s_heading3))
    params_data = [
        ["Parametro", "Valor", "Unidad"],
        ["Vida media (t1/2)", f"{Y90_HALF_LIFE_H:.1f}", "horas"],
        ["Constante de decaimiento (lambda)", f"{LAMDA_DECAY:.4f}", "h^-1"],
        ["Tasa de reparacion (mu)", f"{MU_REPAIR:.2f}", "h^-1"],
        ["Tiempo de reparacion (T1/mu)", f"{1/MU_REPAIR:.1f}", "horas"],
        ["Vida media (tau)", f"{Y90_HALF_LIFE_H * 3600 / np.log(2):.0f}", "segundos"],
        ["Conversion MeV a J", f"{MEV2J:.2e}", "J/MeV"],
        ["Constante K (MIRD)", "48.98", "J*s"],
    ]
    params_table = Table(params_data, colWidths=[55 * mm, 40 * mm, usable_width - 95 * mm])
    params_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
    ]))
    story.append(params_table)
    story.append(Spacer(1, 6 * mm))

    # Relaciones alpha/beta
    story.append(Paragraph("Relaciones alpha/beta por Estructura", s_heading3))
    ab_data = [
        ["Estructura", "alpha/beta (Gy)", "Tipo biologico", "Indice"],
        ["Hígado", f"{ALPHA_BETA_LIVER:.1f}", "Tejido normal", f"{LIVER_INDEX}"],
        ["Tumor", f"{ALPHA_BETA_TUMOR:.1f}", "Tumor maligno", f"{TUMOR_INDEX}"],
        ["Peritumoral", f"{ALPHA_BETA_LIVER:.1f}", "Tejido normal", f"{PRETUMOR_INDEX}"],
    ]
    ab_table = Table(ab_data, colWidths=[30 * mm, 25 * mm, 40 * mm, usable_width - 95 * mm])
    ab_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
        # Colores por estructura
        ("TEXTCOLOR", (0, 1), (0, 1), C_HIGADO),
        ("TEXTCOLOR", (0, 2), (0, 2), C_TUMOR),
        ("TEXTCOLOR", (0, 3), (0, 3), C_PERITUMORAL),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
    ]
    ab_table.setStyle(TableStyle(ab_style))
    story.append(ab_table)
    story.append(Spacer(1, 6 * mm))

    # Densidades
    story.append(Paragraph("Densidades Asignadas", s_heading3))
    dens_data = [
        ["Material", "Densidad (g/cm3)", "Uso"],
        ["Hígado / Tumor / Peritumoral", f"{DENSIDAD_LIVER:.2f}", "Tejido hepatico"],
        ["Body (default)", f"{DENSIDAD_BODY:.1f}", "Contorno corporal"],
        ["Aire", f"{DENSIDAD_AIR:.3f}", "Exterior"],
    ]
    dens_table = Table(dens_data, colWidths=[50 * mm, 35 * mm, usable_width - 85 * mm])
    dens_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
    ]))
    story.append(dens_table)
    story.append(Spacer(1, 6 * mm))

    # Formulas con LaTeX via matplotlib
    story.append(Paragraph("Formulas de Conversion", s_heading3))
    story.append(Spacer(1, 2 * mm))

    def _render_latex_to_image(latex_str, filepath, dpi=150, fontsize=14):
        """Renderiza formula LaTeX a imagen PNG usando matplotlib."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(usable_width / cm, 1.2))
        ax.text(0.02, 0.5, f"${latex_str}$", fontsize=fontsize,
                va="center", ha="left", transform=ax.transAxes)
        ax.axis("off")
        fig.savefig(filepath, dpi=dpi, bbox_inches="tight",
                    pad_inches=0.05, facecolor="white", transparent=False)
        plt.close(fig)

    formula_defs = [
        (r"\mathrm{BED} = D + \frac{\lambda}{(\alpha/\beta)(\lambda + \mu)} \cdot D^2",
         "Biologically Effective Dose"),
        (r"\mathrm{EUD} = \left( \sum_i v_i \cdot D_i^a \right)^{1/a}",
         "Equivalent Uniform Dose"),
        (r"\mathrm{EQD2} = \frac{\mathrm{BED}}{1 + \frac{2}{\alpha/\beta}}",
         "Equivalent Dose in 2 Gy fractions"),
        (r"D\,[\mathrm{Gy}] = D\,[\mathrm{MeV/g}] \times 1.6 \times 10^{-13} \times \tau \times \mathrm{Act} \times 1000",
         "Conversion MeV/cm\u00b3 a Gy"),
    ]

    formula_images = []
    for i, (latex, desc) in enumerate(formula_defs):
        img_path = os.path.join(output_dir, f"_formula_{i}.png")
        try:
            _render_latex_to_image(latex, img_path)
            formula_images.append((img_path, desc))
            formula_images_to_clean.append(img_path)
        except Exception as e:
            # Fallback a texto plano si LaTeX falla
            story.append(Paragraph(f"\u2022 <b>{desc}</b>: {latex}", s_small))

    # Renderizar formulas como imagenes en tabla 2x2
    if formula_images:
        img_w = (usable_width - 5 * mm) / 2
        img_h = img_w * 0.22
        for idx in range(0, len(formula_images), 2):
            row_items = []
            for j in range(2):
                if idx + j < len(formula_images):
                    img_path, desc = formula_images[idx + j]
                    img_obj = Image(img_path, width=img_w, height=img_h)
                    row_items.append([img_obj, Paragraph(
                        f"<font color=\"#{C_GRAY.hexval()[2:]}\"><i>{desc}</i></font>",
                        ParagraphStyle("FormulaDesc", parent=s_small,
                                       fontSize=8, alignment=TA_CENTER)
                    )])
                else:
                    row_items.append(["", ""])
            # Stack each cell vertically
            cell_left = row_items[0]
            cell_right = row_items[1] if len(row_items) > 1 else ["", ""]
            formula_table_data = [
                [cell_left[0], cell_right[0]],
                [cell_left[1], cell_right[1]],
            ]
            formula_table = Table(formula_table_data, colWidths=[img_w + 5 * mm, img_w + 5 * mm])
            formula_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, C_BORDER),
            ]))
            story.append(formula_table)
            story.append(Spacer(1, 2 * mm))

    story.append(PageBreak())

    # ================================================================
    # PAGINA 3: RESULTADOS DOSIMETRICOS + MIRD
    # ================================================================
    story.append(Paragraph("Resultados Dosimetricos por Estructura", s_heading))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_ACCENT))
    story.append(Spacer(1, 4 * mm))

    # Tabla principal - SIEMPRE 3 filas
    res_headers = ["Estructura", "Voxeles", "Vol (cm\u00b3)", "Dmedia (Gy)",
                   "D98 (Gy)", "D95 (Gy)", "D70 (Gy)", "D50 (Gy)", "D5 (Gy)", "D2 (Gy)",
                   "V30 (%)", "V70 (%)",
                   "BED (Gy)", "EUD (Gy)", "EQD2 (Gy)"]
    res_data = [res_headers]
    for key, label, idx, color in all_struct_order:
        s = structures.get(key, {})
        res_data.append([
            label,
            f"{s.get('n_voxels', 0):,}" if s.get('n_voxels', 0) > 0 else "0",
            f"{s.get('volume_cm3', 0):.1f}" if s.get('volume_cm3', 0) > 0 else "\u2014",
            f"{s.get('mean_dose_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d98_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d95_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d70_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d50_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d5_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('d2_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('v30_pct', 0):.1f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('v70_pct', 0):.1f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('bed_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('eud_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            f"{s.get('eqd2_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
        ])
    res_col_w = usable_width / 15
    res_table = Table(res_data, colWidths=[res_col_w] * 15)
    res_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
    ]
    for i, (key, label, idx, color) in enumerate(all_struct_order, start=1):
        res_style.append(("TEXTCOLOR", (0, i), (0, i), color))
        res_style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
    res_table.setStyle(TableStyle(res_style))
    story.append(res_table)
    story.append(Spacer(1, 10 * mm))

    # MIRD Partition Model
    story.append(Paragraph("MIRD Partition Model", s_heading))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_ACCENT))
    story.append(Spacer(1, 4 * mm))

    # MIRD usa keys: liver, tumor, pretumor
    mird_key_map = {"higado": "liver", "tumor": "tumor", "pretumor": "pretumor"}
    mird_headers = ["Estructura", "Dmedia (Gy)", "Indice", "Tipo"]
    mird_data = [mird_headers]
    for key, label, idx, color in all_struct_order:
        mird_key = mird_key_map.get(key, key)
        dose_val = mird.get(mird_key, {}).get("mean_dose_gy", 0)
        tipo = "Tumor" if key == "tumor" else "Normal"
        mird_data.append([
            label,
            f"{dose_val:.2f}" if dose_val > 0 else "\u2014",
            f"{idx}",
            tipo,
        ])
    mird_table = Table(mird_data, colWidths=[35 * mm, 30 * mm, 20 * mm, usable_width - 85 * mm])
    mird_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
        ("TEXTCOLOR", (0, 1), (0, 1), C_HIGADO),
        ("TEXTCOLOR", (0, 2), (0, 2), C_TUMOR),
        ("TEXTCOLOR", (0, 3), (0, 3), C_PERITUMORAL),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
    ]
    mird_table.setStyle(TableStyle(mird_style))
    story.append(mird_table)

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"<font color=\"#{C_GRAY.hexval()[2:]}\">Actividad total: "
        f"{meta.get('activity_gbq', 0):.4f} GBq</font>",
        s_small
    ))
    story.append(PageBreak())

    # ================================================================
    # PAGINA 4: DVH (matplotlib embebido como imagen)
    # ================================================================
    if dvh_curves:
        story.append(Paragraph("Cumulative Dose Volume Histogram (DVH)", s_heading))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_ACCENT))
        story.append(Spacer(1, 4 * mm))

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            dvh_colors = {"Hígado": (0.145, 0.388, 0.922), "Tumor": (0.863, 0.149, 0.149),
                          "Peritumoral": (0.851, 0.467, 0.024)}

            fig, ax = plt.subplots(figsize=(7.5, 4.5))
            for name, d_vals, a_vals in dvh_curves:
                c = dvh_colors.get(name, (0.5, 0.5, 0.5))
                ax.plot(d_vals, a_vals, color=c, label=name, linewidth=2.5)
            ax.set_xlabel("Dose (Gy)", fontsize=12, fontweight="bold")
            ax.set_ylabel("Volume (%)", fontsize=12, fontweight="bold")
            ax.set_title("Cumulative DVH", fontsize=14, fontweight="bold", pad=10)
            ax.set_yscale("log")
            ax.set_ylim(0.1, 110)
            ax.set_xlim(0, max((float(d[-1]) for _, d, _ in dvh_curves), default=100) * 1.05)
            ax.grid(True, which="both", alpha=0.3, linestyle="--")
            ax.legend(fontsize=11, loc="upper right", framealpha=0.9)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            fig.tight_layout()

            dvh_img_path = os.path.join(output_dir, "_dvh_temp.png")
            fig.savefig(dvh_img_path, dpi=150, bbox_inches="tight", facecolor="white")
            plt.close(fig)

            img = Image(dvh_img_path, width=usable_width, height=usable_width * 0.6)
            story.append(img)
            story.append(Spacer(1, 6 * mm))

            try:
                os.remove(dvh_img_path)
            except Exception:
                pass
        except Exception as e:
            story.append(Paragraph(f"Error generando DVH: {e}", s_small))

        story.append(PageBreak())

        # ================================================================
        # PAGINA 5: METRICAS DVH
        # ================================================================
        story.append(Paragraph("Metricas DVH por Estructura", s_heading))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_ACCENT))
        story.append(Spacer(1, 4 * mm))

        dvh_headers = ["Estructura", "Vol (cm\u00b3)", "Dmedia (Gy)", "D98 (Gy)",
                       "D95 (Gy)", "D70 (Gy)", "D50 (Gy)", "D5 (Gy)", "D2 (Gy)",
                       "V30 (%)", "V70 (%)", "Max (Gy)", "BED (Gy)", "EUD (Gy)"]
        dvh_data = [dvh_headers]
        for key, label, idx, color in all_struct_order:
            s = structures.get(key, {})
            dvh_data.append([
                label,
                f"{s.get('volume_cm3', 0):.1f}" if s.get('volume_cm3', 0) > 0 else "\u2014",
                f"{s.get('mean_dose_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d98_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d95_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d70_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d50_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d5_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('d2_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('v30_pct', 0):.1f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('v70_pct', 0):.1f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('max_dose_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('bed_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
                f"{s.get('eud_gy', 0):.2f}" if s.get('n_voxels', 0) > 0 else "\u2014",
            ])
        dvh_col_w = usable_width / 14
        dvh_table = Table(dvh_data, colWidths=[dvh_col_w] * 14)
        dvh_style = [
            ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), C_HEADER_FG),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C_BG_LIGHT]),
        ]
        for i, (key, label, idx, color) in enumerate(all_struct_order, start=1):
            dvh_style.append(("TEXTCOLOR", (0, i), (0, i), color))
            dvh_style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
        dvh_table.setStyle(TableStyle(dvh_style))
        story.append(dvh_table)

    logger.info(f"  Reporte PDF: {pdf_path}")
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)

    # Limpiar imagenes temporales (despues de build)
    for img_path in formula_images_to_clean:
        try:
            os.remove(img_path)
        except Exception:
            pass

    return pdf_path


def _generate_pdf_matplotlib_fallback(
    results: dict, output_dir: str, dvh_curves: list = None
) -> str:
    """Fallback: genera PDF con matplotlib si reportlab no esta disponible."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception:
        logger.warning("  matplotlib no disponible para PDF")
        return None

    pdf_path = os.path.join(output_dir, "dosimetria_report.pdf")
    meta = results.get("metadata", {})
    structures = results.get("structures", {})
    mird = results.get("mird", {})

    struct_labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}

    with PdfPages(pdf_path) as pdf:
        # Pagina 1: Portada basica
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.text(0.5, 0.9, "REPORTE DE DOSIMETRIA", fontsize=24,
                fontweight="bold", ha="center", transform=ax.transAxes)
        ax.text(0.5, 0.85, "3Dosim v3.14", fontsize=12, ha="center",
                color="#666", transform=ax.transAxes)
        y0 = 0.7
        for label, value in [
            ("Actividad", f"{meta.get('activity_gbq', 0):.4f} GBq"),
            ("NPS", f"{meta.get('nps', 0):,}"),
        ]:
            ax.text(0.15, y0, f"{label}: {value}", fontsize=11, transform=ax.transAxes)
            y0 -= 0.04
        y0 -= 0.03
        ax.text(0.15, y0, "ESTRUCTURAS:", fontsize=12, fontweight="bold",
                transform=ax.transAxes)
        y0 -= 0.04
        for name, s in structures.items():
            label = struct_labels.get(name, name)
            ax.text(0.15, y0,
                    f"  {label}: Dmedia={s.get('mean_dose_gy',0):.2f} Gy, "
                    f"BED={s.get('bed_gy',0):.2f} Gy",
                    fontsize=10, transform=ax.transAxes)
            y0 -= 0.03
        pdf.savefig(fig)
        plt.close(fig)

    logger.info(f"  Reporte PDF (fallback matplotlib): {pdf_path}")
    return pdf_path


# ======================================================================
# 6. Main
# ======================================================================

def setup_slicer_paths():
    """Configura sys.path para importar SlicerDosimLib. Retorna path o None."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log(f"  script_dir: {script_dir}")

    # Posibles rutas a SlicerDosimLib
    possible_paths = [
        # Desde PipelineOrchestrator/ -> ../../Modules/Scripted/SlicerDosim/SlicerDosimLib
        os.path.join(script_dir, "..", "..", "Modules",
                     "Scripted", "SlicerDosim", "SlicerDosimLib"),
        # Resolucion absoluta
        r"C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim"
        r"\Modules\Scripted\SlicerDosim\SlicerDosimLib",
    ]

    for p in possible_paths:
        abs_p = os.path.abspath(p)
        log(f"  Checking path: {abs_p} (exists={os.path.exists(abs_p)})")
        if os.path.exists(abs_p) and abs_p not in sys.path:
            sys.path.insert(0, abs_p)
            log(f"  Path agregado: {abs_p}")
            return abs_p

    log("ERROR: No se encontro SlicerDosimLib en sys.path")
    return None


def get_labelmap_array(labelmap_node):
    """Extrae array 3D del labelmap, transpone a (nx, ny, nz)."""
    import slicer

    arr = slicer.util.arrayFromVolume(labelmap_node)  # (nz, ny, nx)
    arr = arr.transpose(2, 1, 0).astype(np.int32)  # (nx, ny, nz)
    return arr


def load_kernel(kernel_path: str) -> np.ndarray:
    """Carga kernel de dosis desde archivo .mat (v7.3 HDF5) y lo normaliza.

    Centra el maximo del kernel en el centro del array (necesario para
    que la convolucion FFT coincida con MATLAB imfilter). El kernel MCNP
    tipicamente tiene el maximo en (24,24,24) y no en (25,25,25)."""
    import h5py
    if not os.path.exists(kernel_path):
        logger.error(f"Kernel no encontrado: {kernel_path}")
        return None
    with h5py.File(kernel_path, "r") as f:
        kernel = f["Kernel"][()].astype(np.float64)

    # Centrar maximo en centro del array
    max_pos = np.unravel_index(np.argmax(kernel), kernel.shape)
    center = tuple(s // 2 for s in kernel.shape)
    if max_pos != center:
        shifts = tuple(c - m for c, m in zip(center, max_pos))
        logger.info(f"  Centrando kernel: max en {max_pos} -> centro {center}, shift={shifts}")
        kernel = np.roll(kernel, shifts, axis=(0, 1, 2))

    # NOTA: NO normalizar. El kernel.mat ya viene calibrado en Gy desde MATLAB
    # (incluye MeV→J, t=1/λ, Actividad=1e9=1GBq, ÷masa).
    # Normalizar (kernel/sum(kernel)) destruye las unidades fisicas.
    logger.info(f"  Kernel cargado: {kernel_path}")
    logger.info(f"  Shape: {kernel.shape}, sum={kernel.sum():.6e} (Gy, NO normalizado)")
    return kernel


def _show_popup(title: str, text: str, no_slicer: bool = False):
    """Wrapper para compatibilidad — usa la funcion compartida en utils."""
    from PipelineOrchestrator.utils import show_popup
    return show_popup(title, text, no_slicer)


def _close_popup(dlg):
    """Wrapper para compatibilidad — usa la funcion compartida en utils."""
    from PipelineOrchestrator.utils import close_popup
    close_popup(dlg)


def main():
    # ── Logging global: captura TODO a archivo ──
    try:
        from PipelineOrchestrator.logging_setup import setup_global_logging
        setup_global_logging()
    except Exception as _e:
        print(f"[3Dosim] No se pudo iniciar logging global: {_e}")

    parser = argparse.ArgumentParser(
        description="Pipeline de dosimetria desde escena existente"
    )
    parser.add_argument("--scene-path", default=None,
                        help=f"Ruta a escena .mrb (default: {SCENE_DEFAULT})")
    parser.add_argument("--mctal", default=None,
                        help=f"Ruta a archivo MCTAL (default: {MCTAL_DEFAULT})")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT,
                        help="Directorio de salida para reportes")
    parser.add_argument("--activity", type=float, default=None,
                        help="Actividad en GBq (default: computar del PET)")
    parser.add_argument("--labelmap", default=None,
                        help=f"Ruta a labelmap NIfTI (default: {LABELMAP_DEFAULT})")
    parser.add_argument("--no-slicer", action="store_true",
                        help="No cargar en Slicer (solo parsear MCTAL)")
    parser.add_argument("--show", action="store_true",
                        help="Mantener Slicer abierto con DVH + consola interactiva")
    parser.add_argument("--no-consola", action="store_true",
                        help="No mostrar consola interactiva (default: mostrar si disponible)")
    parser.add_argument("--flip", action="store_true", default=True,
                        help="Aplicar flip Y a dosis MCTAL (default: True, compatibilidad MATLAB)")
    parser.add_argument("--no-flip", action="store_false", dest="flip",
                        help="No aplicar flip Y a dosis MCTAL")
    parser.add_argument("--info-json", default=None,
                        help="Ruta a JSON de info PET (con campo Units, generado por mod1)")
    parser.add_argument("--kernel", default=None,
                        help="Ruta a kernel .mat para convolucion rapida (alternativa a MCTAL)")
    parser.add_argument("--isodose-levels", type=str, default=None,
                        help="Niveles de isodosis separados por coma (ej: 5,10,15,20,25,30). "
                             "Default: 5,10,15,20,25,30")
    parser.add_argument("--no-isodose", action="store_true",
                        help="Saltar generacion de curvas de isodosis")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Saltar generacion de reporte PDF (tarda ~30-60s)")

    args, _ = parser.parse_known_args()

    scene_path = args.scene_path or SCENE_DEFAULT
    mctal_path = args.mctal or MCTAL_DEFAULT
    kernel_path = args.kernel
    output_dir = args.output_dir

    os.makedirs(output_dir, exist_ok=True)

    # Parsear niveles de isodosis (default desde config o CLI)
    isodose_levels = None  # None = usar defaults
    isodose_relative = True  # default: relativo (% de max)
    if not args.no_isodose:
        # Cargar defaults desde config
        from views import load_pipeline_config
        _cfg = load_pipeline_config()
        _iso_cfg = _cfg.get("isodose", {})
        isodose_relative = _iso_cfg.get("relative", True)
        if args.isodose_levels:
            try:
                isodose_levels = [float(x.strip()) for x in args.isodose_levels.split(",")]
                isodose_levels.sort()
                logger.info(f"Niveles de isodosis desde CLI: {isodose_levels}")
            except Exception as e:
                logger.warning(f"Error parseando --isodose-levels '{args.isodose_levels}': {e}. Usando defaults.")
        if isodose_levels is None:
            isodose_levels = _iso_cfg.get("levels_pct", [10, 25, 50, 75, 90, 95, 100])
            logger.info(f"Niveles de isodosis desde config: {isodose_levels}")
        logger.info(f"Isodosis {'relativas (%)' if isodose_relative else 'absolutas (Gy)'}")

    # Validacion temprana de archivos obligatorios
    if not os.path.exists(scene_path):
        log(f"ERROR: Escena no encontrada: {scene_path}")
        print(f"FATAL: El archivo --scene-path no existe: {scene_path}", file=sys.stderr)
        return 1
    if not kernel_path and not os.path.exists(mctal_path):
        log(f"ERROR: MCTAL no encontrado: {mctal_path}")
        print(f"FATAL: El archivo --mctal no existe: {mctal_path}", file=sys.stderr)
        return 1
    if kernel_path and not os.path.exists(kernel_path):
        log(f"ERROR: Kernel no encontrado: {kernel_path}")
        print(f"FATAL: El archivo --kernel no existe: {kernel_path}", file=sys.stderr)
        return 1

    t_start = time.time()
    log("SCRIPT MAIN STARTED")

    # ----------------------------------------------------------------
    # Setup
    # ----------------------------------------------------------------
    log("=" * 60)
    log(" 3Dosim Dosimetry Pipeline v3.14")
    log("=" * 60)

    # Consola interactiva (como pipeline.py)
    # Si es --no-slicer, no hay Qt → no hay consola
    consola = None
    if _HAS_CONSOLE and not args.no_consola and not args.no_slicer:
        try:
            consola = ConsolaComandos(output_dir=output_dir)
            consola.mostrar()
            consola.log("=" * 50)
            consola.log(" 3Dosim Dosimetry Pipeline - Consola de Comandos")
            consola.log(" Escribi 'ayuda' para comandos disponibles")
            consola.log("=" * 50)
            consola.log("")
        except Exception as e:
            logger.warning(f"  No se pudo crear consola: {e}")
            consola = None

    def _log_consola(msg):
        if consola:
            try:
                consola.log(msg)
            except Exception:
                pass
    def _log_consola_ok(msg):
        if consola:
            try:
                consola.log_ok(msg)
            except Exception:
                pass
    def _log_consola_error(msg):
        if consola:
            try:
                consola.log_error(msg)
            except Exception:
                pass

    def _save_scene_background(scene_path: str):
        """Guarda escena en background (despues de mostrar resultado)."""
        try:
            import slicer
            t0 = time.time()
            slicer.util.saveScene(scene_path)
            dt = time.time() - t0
            logger.info(f"  Escena guardada en background: {scene_path} ({dt:.0f}s)")
        except Exception as e:
            logger.warning(f"  Error guardando escena en background: {e}")

    def _ai_review(paso, ok, datos=None, error=None):
        """Revisa paso via AI Supervisor (DeepSeek/OpenRouter)."""
        if not _HAS_AI:
            _log_consola("[AI supervisor no disponible — import fallo]")
            return
        try:
            ctx = {
                "paso": paso,
                "ok": ok,
                "tiempo": time.time() - t_start,
                "datos": datos or {},
                "errores": [error] if error else [],
            }
            ai_supervisor.revisar_paso(ctx, consola=consola)
        except Exception as e:
            _log_consola(f"[AI supervisor: {e}]")
            pass  # AI supervisor no disponible, no bloquear

    found = setup_slicer_paths()
    log(f"  SlicerDosimLib path found: {found}")
    if _HAS_AI:
        _log_consola("[AI supervisor activo — revisando pasos via DeepSeek]")
    else:
        _log_consola("[AI supervisor no disponible — revisar .env]")
    _log_consola("Iniciando pipeline de dosimetria...")

    # ----------------------------------------------------------------
    # Cargar escena en Slicer
    # ----------------------------------------------------------------
    if not args.no_slicer:
        import slicer

        def _wait_slicer(msg="Slicer queda abierto para inspeccion manual.", timeout_s=120):
                """Muestra mensaje y mantiene Slicer vivo por timeout_s segundos."""
                logger.info(f"  {msg}")
                _log_consola(msg)
                _log_consola(f"  (Slicer se cerrara automaticamente en {timeout_s}s)")
                sys.stderr.flush()
                t0 = time.time()
                try:
                    while time.time() - t0 < timeout_s:
                        slicer.app.processEvents()
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    pass
                logger.info("  Timeout alcanzado — cerrando Slicer.")
                _log_consola("Timeout — cerrando Slicer.")
                # Cerrar Slicer forzadamente
                slicer.app.quit()

        logger.info("\n--- Paso 1: Cargar escena ---")
        _log_consola("Paso 1/10: Cargando escena (puede tardar ~2 min)...")
        from PipelineOrchestrator.utils import show_popup, close_popup
        scene_popup = show_popup(
            "3Dosim — Cargando escena",
            "<b>Cargando escena en 3D Slicer...</b><br><br>"
            "Esto puede tardar hasta 2 minutos si la escena es grande.<br>"
            "NO cierre Slicer, espere a que termine."
        )
        if not load_scene(scene_path):
            close_popup(scene_popup)
            logger.error("Abortando: no se pudo cargar la escena")
            _log_consola_error("Error cargando escena")
            _wait_slicer("La escena no pudo cargarse. Revise el archivo y cierre Slicer.", timeout_s=30)
            return 1
        close_popup(scene_popup)

        logger.info("\n--- Paso 2: Buscar nodos ---")
        _log_consola("Paso 2/10: Buscando nodos (CT, PET, Labelmap)...")
        print("[3Dosim] Buscando nodos en escena...", flush=True)
        nodes = find_nodes()
        _found = []
        if nodes.get("ct"): _found.append(f"CT='{nodes['ct'].GetName()}'")
        if nodes.get("pet"): _found.append(f"PET='{nodes['pet'].GetName()}'")
        if nodes.get("labelmap"): _found.append(f"Labelmap='{nodes['labelmap'].GetName()}'")
        if nodes.get("ct_masked"): _found.append(f"CT_masked='{nodes['ct_masked'].GetName()}'")
        if nodes.get("segmentation"): _found.append(f"Segmentation='{nodes['segmentation'].GetName()}'")
        _not_found = [k for k in ("ct", "pet", "labelmap") if not nodes.get(k)]
        logger.info(f"  Nodos encontrados: {', '.join(_found) if _found else 'NINGUNO'}")
        if _not_found:
            logger.warning(f"  Nodos NO encontrados: {', '.join(_not_found)}")
        print(f"[3Dosim] Nodos: {', '.join(_found) if _found else 'NINGUNO'}", flush=True)
        if _not_found:
            print(f"[3Dosim] Faltan: {', '.join(_not_found)}", flush=True)

        # Configurar vistas medicas para que el usuario VEA la escena
        if _HAS_VIEWS:
            logger.info("\n--- Configurar vistas medicas ---")
            _log_consola("Configurando vistas 3D + slices + fusion...")
            try:
                seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
                seg_node = seg_nodes[0] if seg_nodes else None
                setup_medical_views(
                    ct_node=nodes.get("ct"),
                    pet_node=nodes.get("pet"),
                    ct_masked_node=nodes.get("ct_masked"),
                    segmentation_node=seg_node,
                    layout_name="ConventionalView",
                    pet_opacity=0.35,
                    link_slices=True,
                )
                print("[3Dosim OK] Vistas medicas configuradas", flush=True)
                _log_consola_ok("Vistas medicas listas (CT+PET+segmentacion)")
            except Exception as e:
                print(f"[3Dosim WARNING] setup_medical_views fallo: {e}", flush=True)
                logger.warning(f"setup_medical_views fallo: {e}")
        else:
            print("[3Dosim WARNING] views.py no disponible, saltando vistas", flush=True)

        labelmap_nifti = args.labelmap or LABELMAP_DEFAULT
        print(f"[3Dosim] Buscando labelmap: en escena={'SI' if nodes['labelmap'] else 'NO'}, NIfTI={labelmap_nifti}", flush=True)
        # Verificar que el labelmap en escena tenga datos de imagen reales
        if nodes["labelmap"] is not None:
            try:
                _has_data = nodes["labelmap"].GetImageData() is not None
            except Exception:
                _has_data = False
            if not _has_data:
                logger.warning(f"  Labelmap '{nodes['labelmap'].GetName()}' existe pero sin datos de imagen — tratando como ausente")
                nodes["labelmap"] = None
        if nodes["labelmap"] is None and os.path.exists(labelmap_nifti):
            logger.info(f"  Cargando labelmap desde NIfTI: {labelmap_nifti}")
            labelmap_node = slicer.util.loadVolume(labelmap_nifti)
            if labelmap_node:
                nodes["labelmap"] = labelmap_node
                logger.info(f"  Labelmap cargado: {labelmap_node.GetName()}")
            else:
                logger.error("  No se pudo cargar labelmap NIfTI")

        # Si no hay labelmap, intentar convertir segmentation -> labelmap
        if nodes["labelmap"] is None and nodes.get("segmentation") is not None:
            logger.info("  Labelmap no encontrado, pero hay segmentacion — convirtiendo a labelmap...")
            _log_consola("Convirtiendo segmentacion a labelmap...")
            try:
                seg_node = nodes["segmentation"]
                ref_node = nodes.get("ct") or nodes.get("ct_masked") or nodes.get("pet")
                labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLLabelMapVolumeNode", "3Dosim_labelmap"
                )
                if ref_node is not None:
                    seg_node.CreateLabelmapVolumeFromSegmentation(labelmap_node, ref_node)
                else:
                    seg_node.CreateLabelmapVolumeFromSegmentation(labelmap_node)
                nodes["labelmap"] = labelmap_node
                logger.info(f"  Labelmap creado desde segmentacion: {labelmap_node.GetName()}")
                _log_consola_ok("Labelmap creado desde segmentacion")
            except Exception as e:
                logger.error(f"  Error convirtiendo segmentation a labelmap: {e}")
                _log_consola_error(f"Error convirtiendo segmentacion: {e}")

        if nodes["labelmap"] is None:
            msg = (
                "No se encontro el labelmap de tejidos necesario para la dosimetria.\n\n"
                "La escena debe contener un nodo '3Dosim_labelmap' (o pasar --labelmap PATH)\n"
                "con los indices de tejido:\n"
                "  - 0   = Aire / exterior\n"
                "  - 90  = Higado sano\n"
                "  - 100 = Tumor\n"
                "  - 200 = Peritumoral\n\n"
                "Para generar el labelmap:\n"
                "  1. Ejecute el Modulo 1 (pipeline completo) para exportar el labelmap\n"
                "  2. O ejecute el export_labelmap paso a paso desde PipelineOrchestrator\n"
                "  3. Luego vuelva a ejecutar este modulo con la escena actualizada\n\n"
                f"Escena cargada: {scene_path}\n"
                f"Labelmap NIfTI buscado: {args.labelmap or LABELMAP_DEFAULT}"
            )
            logger.error("No se encontro nodo labelmap en la escena ni en NIfTI")
            try:
                import slicer
                slicer.util.errorDisplay(msg, "3Dosim - Error: Labelmap no encontrado")
            except Exception:
                print(msg, file=sys.stderr)
            _wait_slicer("Slicer queda abierto. Genere el labelmap, guarde la escena y cierre Slicer.")
            return 1

        ct_node = nodes["ct"]
        pet_node = nodes["pet"]
        labelmap_node = nodes["labelmap"]

        # Extraer labelmap
        labelmap = get_labelmap_array(labelmap_node)
        dims = labelmap.shape  # (nx, ny, nz)
        spacing = labelmap_node.GetSpacing()

        logger.info(f"  Labelmap shape: {dims}")
        logger.info(f"  Spacing: {spacing}")
        logger.info(f"  Indices unicos: {np.unique(labelmap)}")

        # Generar zona peritumoral (1 cm alrededor del tumor)
        t_peri = time.time()
        try:
            if TUMOR_INDEX in labelmap and PRETUMOR_INDEX not in np.unique(labelmap):
                logger.info("\n--- Generando zona peritumoral (1 cm alrededor del tumor) ---")
                _log_consola("Generando zona peritumoral (1 cm alrededor del tumor)...")
                sys.stdout.flush()
                sys.stderr.flush()
                tumor_mask = (labelmap == TUMOR_INDEX)
                n_tumor = np.sum(tumor_mask)
                if n_tumor > 0:
                    # Radio en voxeles: 10 mm / spacing
                    radius_vox = max(1, int(10.0 / np.mean(spacing)))
                    logger.info(f"  Radio de dilatacion: {radius_vox} voxeles ({10.0} mm)")
                    # Dilatar tumor (iteraciones con struct 3x3x3 es ~22x mas rapido
                    # que struct grande directo, que requiere 4913 ops/voxel)
                    struct_3 = np.ones((3, 3, 3), dtype=bool)
                    tumor_dilated = binary_dilation(tumor_mask, structure=struct_3, iterations=radius_vox)
                    # Restar tumor original = anillo peritumoral
                    peritumoral = tumor_dilated & ~tumor_mask
                    # Limitar al higado (no salir del parenquima hepatico)
                    liver_mask = (labelmap == LIVER_INDEX)
                    peritumoral = peritumoral & liver_mask
                    n_peri = np.sum(peritumoral)
                    logger.info(f"  Voxeles peritumorales: {n_peri}")
                    if n_peri > 0:
                        dt_peri = time.time() - t_peri
                        labelmap[peritumoral] = PRETUMOR_INDEX
                        logger.info(f"  Zona peritumoral asignada (indice {PRETUMOR_INDEX})")
                        _log_consola_ok(f"Zona peritumoral: {n_peri} voxeles en {dt_peri:.1f}s")
                        # Actualizar nodo labelmap en Slicer y forzar refresco
                        try:
                            import slicer
                            # Transponer de (nx,ny,nz) a (nz,ny,nx) para Slicer
                            arr_slicer = labelmap.transpose(2, 1, 0).astype(np.int32)
                            slicer.util.updateVolumeFromArray(labelmap_node, arr_slicer)
                            # Forzar refresco visual del labelmap
                            dn = labelmap_node.GetDisplayNode()
                            if dn:
                                dn.Modified()  # forzar actualizacion
                            slicer.app.processEvents()  # procesar eventos GUI
                            logger.info("  Labelmap node actualizado en Slicer")
                            _log_consola_ok("Peritumoral visible en 3Dosim_labelmap")

                        except Exception as e:
                            logger.warning(f"  No se pudo actualizar nodo labelmap: {e}")

                        # ── Importar peritumoral como segmento en Slicer ──
                        try:
                            seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
                            if seg_nodes:
                                seg_node = seg_nodes[0]
                                # Crear labelmap temporal solo con peritumoral
                                # peritumoral esta en (nx,ny,nz), Slicer usa (nz,ny,nx)
                                temp_arr = peritumoral.astype(np.int16) * PRETUMOR_INDEX
                                temp_arr_slicer = temp_arr.transpose(2, 1, 0)
                                import vtk as _vtk
                                temp_lm = slicer.mrmlScene.AddNewNodeByClass(
                                    "vtkMRMLLabelMapVolumeNode", "__peri_temp__")
                                slicer.util.updateVolumeFromArray(temp_lm, temp_arr_slicer)
                                # Copiar geometria del labelmap_node
                                temp_lm.SetOrigin(labelmap_node.GetOrigin())
                                temp_lm.SetSpacing(labelmap_node.GetSpacing())
                                mat = _vtk.vtkMatrix4x4()
                                labelmap_node.GetIJKToRASMatrix(mat)
                                temp_lm.SetIJKToRASMatrix(mat)
                                # Importar como segmento
                                seg_logic = slicer.modules.segmentations.logic()
                                seg_logic.ImportLabelmapToSegmentationNode(temp_lm, seg_node)
                                # Renombrar ultimo segmento y colorear amarillo
                                seg = seg_node.GetSegmentation()
                                n_seg = seg.GetNumberOfSegments()
                                if n_seg > 0:
                                    last_id = seg.GetSegmentIDs()[n_seg - 1]
                                    segment = seg.GetSegment(last_id)
                                    segment.SetName("Peritumoral")
                                    segment.SetColor(0.8, 0.6, 0.0)
                                # Limpiar
                                slicer.mrmlScene.RemoveNode(temp_lm)
                                logger.info("  Peritumoral importado como segmento (color amarillo)")
                                _log_consola_ok("Peritumoral visible como segmento en Slicer")
                        except Exception as e:
                            logger.warning(f"  No se pudo importar peritumoral como segmento: {e}")
                    else:
                        logger.warning("  No se genero zona peritumoral (sin higado alrededor del tumor)")
                        _log_consola("Zona peritumoral: sin higado alrededor del tumor")
                else:
                    logger.info("  Sin voxeles de tumor, saltando zona peritumoral")
        except Exception as e:
            logger.warning(f"  No se pudo generar zona peritumoral: {e}")
            _log_consola(f"Zona peritumoral: omitida ({e})")
            import traceback
            logger.warning(traceback.format_exc())

        # Asignar tabla de colores al labelmap (despues de peritumoral)
        _setup_labelmap_color_table(labelmap_node)

        # Restaurar vistas medicas (resetSliceViews en _setup_labelmap_color_table
        # puede haber desconfigurado los slices)
        if _HAS_VIEWS:
            try:
                seg_nodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
                seg_node = seg_nodes[0] if seg_nodes else None
                setup_medical_views(
                    ct_node=ct_node,
                    pet_node=pet_node,
                    ct_masked_node=nodes.get("ct_masked"),
                    segmentation_node=seg_node,
                    layout_name="ConventionalView",
                    pet_opacity=0.35,
                    link_slices=True,
                )
                logger.info("  Vistas medicas restauradas post-labelmap")
            except Exception as e:
                logger.warning(f"  setup_medical_views post-labelmap fallo: {e}")

        # Actividad
        if args.activity is not None:
            activity_gbq = args.activity
            activity_bq = activity_gbq * 1e9
        elif pet_node is not None:
            logger.info("\n--- Paso 3: Computar actividad desde PET ---")
            _log_consola("Paso 3/10: Computando actividad desde PET...")
            activity_bq = compute_activity_from_pet(pet_node, info_json=args.info_json, output_dir=output_dir)
            activity_gbq = activity_bq / 1e9
        else:
            logger.error("No hay PET y no se especifico --activity")
            _log_consola_error("No hay PET ni --activity.")
            _wait_slicer("No se encontro PET en la escena ni se paso --activity. Cierre Slicer para salir.")
            return 1

        logger.info(f"  Actividad: {activity_bq:.2e} Bq = {activity_gbq:.4f} GBq")
        _log_consola_ok(f"Actividad: {activity_gbq:.4f} GBq")
        print(f"[3Dosim OK] Actividad: {activity_gbq:.4f} GBq", flush=True)
        _ai_review("Carga + Labelmap + Actividad", True, {
            "activity_gbq": activity_gbq,
            "labelmap_shape": list(dims),
            "labelmap_indices": [int(x) for x in np.unique(labelmap)],
        })

    else:
        # Modo standalone (sin Slicer)
        logger.info("Modo standalone: solo parseo MCTAL")
        dims = (512, 512, 171)  # default
        labelmap = None
        activity_bq = 3e9  # default 3 GBq
        activity_gbq = 3.0

    # ----------------------------------------------------------------
    # Paso 4: Computar dosis (MCTAL o Kernel convolution)
    # ----------------------------------------------------------------
    if kernel_path:
        # ── KERNEL CONVOLUTION (fast) ──
        logger.info("\n--- Paso 4: Convolucion con kernel (rapido) ---")
        _log_consola("Paso 4/10: Cargando kernel y convolucionando...")

        kernel = get_kernel(kernel_path, normalize=False) if _HAS_DOSE_KERNEL else load_kernel(kernel_path)
        if kernel is None:
            logger.error("  Kernel no cargado. Abortando.")
            return 1

        # Popup no-modal
        popup = _show_popup(
            "3Dosim — Kernel convolution",
            "Convolucionando kernel de dosis 3D...\n\n3Dosim esta trabajando, NO cierre Slicer.\n\n"
            "Cuando termine se cerrara este cartel automaticamente.",
            args.no_slicer,
        )

        t0 = time.time()

        # ── Construir distribucion de actividad A (Bq por voxel) ──
        # IMPORTANTE: usar PET_CT (PET resampled al espacio del CT) para el kernel
        if pet_node is not None and labelmap is not None:
            logger.info(f"  Usando volumen PET_CT para kernel: {pet_node.GetName()}")
            pet_arr = slicer.util.arrayFromVolume(pet_node)  # (nz, ny, nx)
            pet_arr = pet_arr.transpose(2, 1, 0).astype(np.float64)  # (nx, ny, nz)
            pet_arr = np.maximum(pet_arr, 0)  # sin negativos
            if pet_arr.sum() > 0:
                A = pet_arr / pet_arr.sum() * activity_gbq  # GBq/voxel (MATLAB: A = PET * 1e-9)
            else:
                A = np.ones(dims, dtype=np.float64) * activity_gbq / np.prod(dims)
        elif labelmap is not None:
            # Sin PET: distribucion uniforme en higado+tumor
            A = np.zeros(dims, dtype=np.float64)
            liver_tumor = (labelmap == LIVER_INDEX) | (labelmap == TUMOR_INDEX)
            n_lt = np.sum(liver_tumor)
            if n_lt > 0:
                A[liver_tumor] = activity_gbq / n_lt  # GBq/voxel
            else:
                A[:] = activity_gbq / np.prod(dims)
        else:
            A = np.ones(dims, dtype=np.float64) * activity_gbq / np.prod(dims)

        logger.info(f"  Actividad total en A: {A.sum():.4f} GBq (MATLAB: A = PET * 1e-9)")

        # ── Convolucion 3D via FFT (cropeada a higado+tumor) ──
        # FFT sobre el volumen completo (512x512x171) necesita ~4GB → OOM.
        # Croppeamos a ROI de higado+tumor + margen del kernel.
        # Usamos convolve_imfilter_symmetric (rfftn + workers=-1 + float32)
        # en vez de scipy.signal.fftconvolve (~3-5x mas rapido).
        from PipelineOrchestrator.fft_dose import convolve_imfilter_symmetric
        kr = np.array(kernel.shape) // 2  # (25, 25, 25)
        if labelmap is not None:
            # Bounding box de todos los voxeles con actividad
            active_mask = (labelmap == LIVER_INDEX) | (labelmap == TUMOR_INDEX)
            active_pts = np.argwhere(active_mask)
            if len(active_pts) > 0:
                lo = active_pts.min(axis=0) - kr
                hi = active_pts.max(axis=0) + kr + 1
                lo = np.maximum(lo, 0)
                hi = np.minimum(hi, dims)
                A_crop = A[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
                # Convertir a float32 para reducir memoria (~50% menos)
                A_crop = np.asarray(A_crop, dtype=np.float32)
                # Liberar A (float64 original) — ya no se necesita en esta rama
                del A
                logger.info(f"  ROI actividad: {A_crop.shape} (full: {dims})")
                _log_consola(f"Convolucion FFT sobre ROI {A_crop.shape}...")
                sys.stdout.flush()
                sys.stderr.flush()
                # Procesar eventos GUI pendientes antes de la FFT
                if not args.no_slicer:
                    try:
                        slicer.app.processEvents()
                    except Exception:
                        pass
                t_conv = time.time()
                dose_crop = convolve_imfilter_symmetric(A_crop, kernel)
                dt_conv = time.time() - t_conv
                # Reconstruir volumen completo
                dose_gy = np.zeros(dims, dtype=np.float64)
                dose_gy[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = dose_crop
                logger.info(f"  Convolucion FFT (ROI) completada en {dt_conv:.1f}s")
                _log_consola(f"Convolucion FFT: {dt_conv:.1f}s (MATLAB: ~22s)")
            else:
                # Sin higado/tumor: fallback a full
                logger.warning("  Sin voxeles activos, convolucion full...")
                A_f32 = np.asarray(A, dtype=np.float32)
                del A
                t_conv = time.time()
                dose_gy = convolve_imfilter_symmetric(A_f32, kernel)
                dt_conv = time.time() - t_conv
                logger.info(f"  Convolucion FFT (full) en {dt_conv:.1f}s")
                _log_consola(f"Convolucion FFT: {dt_conv:.1f}s")
        else:
            A_f32 = np.asarray(A, dtype=np.float32)
            del A
            t_conv = time.time()
            dose_gy = convolve_imfilter_symmetric(A_f32, kernel)
            dt_conv = time.time() - t_conv
            logger.info(f"  Convolucion FFT (full) en {dt_conv:.1f}s")
            _log_consola(f"Convolucion FFT: {dt_conv:.1f}s")
        # Nota: convolve_imfilter_symmetric usa reflect-padding (emula MATLAB 'symmetric').
        # Como la actividad A=0 fuera del higado, zero-padding daria lo mismo.
        dt = time.time() - t0
        logger.info(f"  Convolucion completada en {dt:.1f}s")
        dt = time.time() - t0
        logger.info(f"  Convolucion completada en {dt:.1f}s")

        # ── Enmascarar a higado + tumor + peritumoral (MATLAB: DosisK.*IND_liver_tumor) ──
        if labelmap is not None:
            liver_tumor_mask = (labelmap == LIVER_INDEX) | (labelmap == TUMOR_INDEX) | (labelmap == PRETUMOR_INDEX)
            dose_gy = dose_gy * liver_tumor_mask

        # ── Sin negativos ──
        n_neg = np.sum(dose_gy < 0)
        dose_gy = np.maximum(dose_gy, 0)
        logger.info(f"  Voxels con dosis negativa corregidos: {n_neg}")

        # ── Resultados ──
        error_3d = np.zeros_like(dose_gy)  # sin incertidumbre estadistica
        mctal_result = {"nps": 0, "title": "Kernel convolution (fast dose)"}

        _close_popup(popup)
        _log_consola_ok(f"Kernel convolucionado: max={dose_gy.max():.2f} Gy, "
                        f"media={dose_gy[dose_gy>0].mean() if np.any(dose_gy>0) else 0:.2f} Gy")
        print(f"[3Dosim OK] Kernel convolucionado en {dt:.1f}s — max={dose_gy.max():.2f} Gy", flush=True)
        _ai_review("Kernel convolution", True, {
            "dose_gy_max": float(dose_gy.max()),
            "dose_gy_mean_positive": float(dose_gy[dose_gy>0].mean()) if np.any(dose_gy>0) else 0,
            "kernel_time_s": round(dt, 1),
            "activity_gbq": activity_gbq,
        })

    else:
        # ── MCTAL PARSING (accurate) ──
        logger.info("\n--- Paso 4: Parsear MCTAL ---")
        mctal_size_mb = os.path.getsize(mctal_path) / (1024 * 1024)
        _log_consola(f"Paso 4/10: Parseando MCTAL ({mctal_size_mb:.0f} MB)... puede demorar varios minutos")

        # Popup no-modal
        mctal_popup = _show_popup(
            "3Dosim — Parseando MCTAL",
            f"Parseando archivo MCTAL ({mctal_size_mb:.0f} MB)...\n\n"
            f"3Dosim esta trabajando, NO cierre Slicer.\n\n"
            f"Cuando termine se cerrara este cartel automaticamente.",
            args.no_slicer,
        )

        mctal_result = parse_mctal(mctal_path, dims)
        dose_mev_cm3 = mctal_result["dose_3d"]
        error_3d = mctal_result["uncertainty"]

        _close_popup(mctal_popup)
        _log_consola_ok(f"MCTAL parseado: NPS={mctal_result['nps']:,}")

        # Aplicar flip Y a dosis si se aplico flip a la geometria MCNP
        if args.flip:
            dose_mev_cm3 = dose_mev_cm3[:, ::-1, :].copy()
            error_3d = error_3d[:, ::-1, :].copy()
            logger.info("  Flip Y aplicado a dosis MCTAL (compatibilidad MATLAB)")
            _log_consola("Flip Y aplicado a dosis (compatibilidad MATLAB)")

        # ── Convertir a Gy ──
        logger.info("\n--- Paso 5: Convertir a Gy ---")
        _log_consola("Paso 5/10: Convirtiendo MeV/cm3 a Gy...")

        t_meanlife_s = Y90_HALF_LIFE_H * 3600 / np.log(2)  # ~332,753 s

        if labelmap is not None:
            dose_gy = convert_to_gy(dose_mev_cm3, labelmap, activity_bq, t_meanlife_s)
        else:
            dose_gy = dose_mev_cm3 * MEV2J * t_meanlife_s * activity_bq * 1000

        # Aplicar filtro de error (MATLAB cargo_mctal.m:375-379)
        error_eliminar = 1.5
        bad_voxels = error_3d >= error_eliminar
        dose_gy[bad_voxels] = 0
        n_bad = np.sum(bad_voxels)
        logger.info(f"  Voxels eliminados por error>={error_eliminar}: {n_bad} ({n_bad/dose_gy.size*100:.2f}%)")

        # Eliminar dosis negativas
        n_neg = np.sum(dose_gy < 0)
        dose_gy[dose_gy < 0] = 0
        logger.info(f"  Voxels con dosis negativa: {n_neg}")

        logger.info(
            f"  Dosis en Gy: media={dose_gy[dose_gy>0].mean() if np.any(dose_gy>0) else 0:.2f}, "
            f"max={dose_gy.max():.2f}, "
            f"voxels no-cero={np.sum(dose_gy>0)}/{dose_gy.size}"
        )
        _ai_review("Conversion a Gy", True, {
            "dose_gy_max": float(dose_gy.max()),
            "dose_gy_mean_positive": float(dose_gy[dose_gy>0].mean()) if np.any(dose_gy>0) else 0,
            "voxels_positive": int(np.sum(dose_gy>0)),
            "nps": mctal_result.get("nps"),
            "activity_gbq": activity_gbq,
        })

    # ----------------------------------------------------------------
    # Crear nodo de dosis en Slicer (antes de DVH/MIRD/reporte)
    # ----------------------------------------------------------------
    dose_node = None  # default, se setea abajo si exitoso
    if not args.no_slicer:
        logger.info("\n--- Crear nodo de dosis 3D en Slicer ---")
        try:
            from dosimetry import DoseCalculator

            calc = DoseCalculator()
            ref_node = labelmap_node or ct_node
            dose_node = calc.create_dose_volume(dose_gy, ref_node)
            if dose_node:
                logger.info(f"  Nodo creado: {dose_node.GetName()}")
                bg_node = nodes.get("ct_masked") or ct_node

                # ── PASO 1: Ocultar todo lo que no queremos ver PRIMERO ──
                # (si se hace después, los eventos de Slicer pueden desconfigurar slices)
                try:
                    for seg_n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
                        seg_n.GetDisplayNode().SetVisibility(False)
                        seg_n.GetDisplayNode().SetSliceIntersectionVisibility(False)
                        logger.info(f"  Segmentacion oculta: {seg_n.GetName()}")
                    if nodes.get("pet"):
                        dn = nodes["pet"].GetDisplayNode()
                        if dn: dn.SetVisibility(False)
                    if labelmap_node:
                        dn = labelmap_node.GetDisplayNode()
                        if dn: dn.SetVisibility(False)
                    logger.info("  Nodos auxiliares ocultos")
                except Exception as e:
                    logger.warning(f"  Ocultando nodos: {e}")

                # ── PASO 2: Asignar colormap a la dosis ──
                try:
                    from views import load_pipeline_config, ensure_inverted_rainbow
                    # Crear/Asegurar siempre el colormap invertido (NO depende de config)
                    cmap_id = ensure_inverted_rainbow()
                    dose_dn = dose_node.GetDisplayNode()
                    if dose_dn is None:
                        # Forzar creacion de display node
                        dose_node.CreateDefaultDisplayNodes()
                        dose_dn = dose_node.GetDisplayNode()
                    if dose_dn:
                        cmap_node = slicer.mrmlScene.GetNodeByID(cmap_id)
                        if cmap_node:
                            dose_dn.SetAndObserveColorNodeID(cmap_node.GetID())
                            # Auto window/level para que se vea
                            dose_dn.AutoWindowLevelOn()
                            dose_dn.SetAutoWindowLevel(True)
                            logger.info(f"  Colormap '3Dosim_InvertedRainbow' asignado a Dosis_3D")
                            logger.info(f"  Window/Level (auto): {dose_dn.GetWindow():.1f}/{dose_dn.GetLevel():.1f}")
                        else:
                            logger.warning(f"  cmap_node None para ID={cmap_id}")
                    else:
                        logger.warning(f"  dose_node display node es None, no se pudo asignar colormap")
                except Exception as e:
                    logger.warning(f"  No se pudo asignar colormap: {e}")

                # ── PASO 3: Configurar slices — SOLO via slice composite nodes ──
                # NO usar setSliceViewerLayers (hace resetSliceViews interno)
                # NO usar setup_medical_views (también resetea)
                try:
                    slice_nodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
                    for sn in slice_nodes:
                        sn.SetBackgroundVolumeID(bg_node.GetID())
                        sn.SetForegroundVolumeID(dose_node.GetID())
                        sn.SetForegroundOpacity(0.4)
                        # Quitar labelmap de los slices
                        sn.SetLabelVolumeID(None)
                        sn.SetLabelOpacity(0.0)
                    # Forzar redraw de todos los slice views
                    lm = slicer.app.layoutManager()
                    for idx in range(lm.sliceViewCount()):
                        sv = lm.sliceWidget(idx).sliceView()
                        if sv:
                            sv.scheduleRender()
                    slicer.app.processEvents()
                    logger.info("  Slices configurados: CT fondo + Dosis overlay (0.4)")
                    _log_consola_ok("Vista: CT + Dosis rainbow")
                    # Reset view en todos los slices (equivale a click "Reset View" de cada slice)
                    try:
                        slicer.util.resetSliceViews()
                        logger.info("  Slice views reseteados (field of view auto)")
                    except Exception as e:
                        logger.debug(f"  resetSliceViews: {e}")
                except Exception as e:
                    logger.warning(f"  Configurando slices: {e}")
                # ── Saltar al voxel con maxima dosis ──
                _max_ras = None
                try:
                    if dose_node is not None:
                        import vtk as _vtk
                        max_idx = np.unravel_index(np.argmax(dose_gy), dose_gy.shape)
                        ijk = [float(max_idx[2]), float(max_idx[1]), float(max_idx[0]), 1.0]
                        mat_ras = _vtk.vtkMatrix4x4()
                        dose_node.GetIJKToRASMatrix(mat_ras)
                        ras = [0.0, 0.0, 0.0, 0.0]
                        mat_ras.MultiplyPoint(ijk, ras)
                        from qt import QTimer
                        QTimer.singleShot(500,
                            lambda r=ras[:3]: slicer.modules.markups.logic().JumpSlicesToLocation(r[0], r[1], r[2], True))
                        logger.info(f"  Saltando al voxel de maxima dosis: "
                                    f"IJK({max_idx[0]},{max_idx[1]},{max_idx[2]}) "
                                    f"-> RAS({ras[0]:.1f},{ras[1]:.1f},{ras[2]:.1f})")
                        _log_consola_ok(f"Maxima dosis: {dose_gy.max():.2f} Gy")
                        _max_ras = list(ras[:3])
                except Exception as e:
                    logger.warning(f"  No se pudo saltar al maximo de dosis: {e}")
                # ── Isodosis (NO BLOQUEANTE: corre en background via QTimer) ──
                if not args.no_isodose and _HAS_ISODOSE and create_isodose_contours:
                    logger.info("\n--- Isodosis: programada en background ---")
                    _log_consola("Curvas de isodosis en background (no bloquea)...")
                    from qt import QTimer
                    # Congelar config para el closure
                    _levels = list(isodose_levels) if isodose_levels else None
                    _relative = isodose_relative
                    def _run_isodose_later(levels=_levels, relative=_relative):
                        try:
                            model_node, param = create_isodose_contours(
                                dose_node,
                                levels=levels,
                                show_lines_2d=True,
                                show_surfaces_3d=True,
                                relative=relative,
                            )
                            if model_node:
                                logger.info(f"  Isodosis OK: {model_node.GetName()}")
                                _log_consola_ok("Curvas de isodosis generadas")
                                # Restaurar slices: isodosis pudo desconfigurar background/foreground
                                try:
                                    bg_node = nodes.get("ct_masked") or ct_node
                                    for sn in slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode"):
                                        sn.SetBackgroundVolumeID(bg_node.GetID())
                                        sn.SetForegroundVolumeID(dose_node.GetID())
                                        sn.SetForegroundOpacity(0.4)
                                        sn.SetLabelVolumeID(None)
                                    # Forzar redraw
                                    try:
                                        lm = slicer.app.layoutManager()
                                        for idx in range(lm.sliceViewCount()):
                                            sv = lm.sliceWidget(idx).sliceView()
                                            if sv: sv.scheduleRender()
                                    except Exception:
                                        pass
                                    logger.info("  Slices restaurados post-isodosis (CT + Dosis)")
                                    # Reset FOV sin tocar posicion (no usar resetSliceViews que resetea TAMBIEN el offset)
                                    _reset_slice_fov(fov_mm=300.0, label="[ISODOSE]")
                                    # Saltar a maxima dosis (ahora con SetSliceOffset directo, NO JumpSlice)
                                    _ras_post = _jump_to_max_dose(dose_node, dose_gy, label="[ISODOSE]")
                                    # Re-activar crosshair
                                    _enable_crosshair(label="[ISODOSE]")
                                    # Re-reset 3D FOV
                                    try:
                                        _lm_is = slicer.app.layoutManager()
                                        _tw_is = _lm_is.threeDWidget(0) if _lm_is else None
                                        if _tw_is:
                                            _tw_is.threeDView().resetFocalPoint()
                                            logger.info("[ISODOSE] 3D FOV reseteado post-isodosis")
                                    except Exception as _e_fov:
                                        logger.warning(f"[ISODOSE] 3D FOV fallo: {_e_fov}")
                                except Exception as e:
                                    logger.warning(f"  No se pudieron restaurar slices post-isodosis: {e}")
                            else:
                                logger.info("  No se generaron isodosis")
                                _log_consola("Isodosis: sin datos (niveles fuera de rango?)")
                        except Exception as e:
                            logger.warning(f"  Error generando isodosis: {e}")
                            _log_consola_error(f"Error en isodosis: {e}")
                    QTimer.singleShot(100, _run_isodose_later)
                elif args.no_isodose:
                    logger.info("  Isodosis saltadas (--no-isodose)")
                elif not _HAS_ISODOSE:
                    logger.info("  isodose_contours no disponible, saltando")

            else:
                logger.warning("  create_dose_volume devolvio None")
        except Exception as e:
            logger.warning(f"  Error creando nodo de dosis: {e}")
            import traceback
            logger.warning(traceback.format_exc())

    # ----------------------------------------------------------------
    # Computar dosimetria por estructura
    # ----------------------------------------------------------------
    logger.info("\n--- Paso 6: Dosimetria por estructura ---")
    _log_consola("Paso 6/10: Computando DVH y radiobiologia...")

    structures = {
        "higado": {"idx": LIVER_INDEX, "alpha_beta": ALPHA_BETA_LIVER, "is_tumor": False},
        "tumor": {"idx": TUMOR_INDEX, "alpha_beta": ALPHA_BETA_TUMOR, "is_tumor": True},
        "pretumor": {"idx": PRETUMOR_INDEX, "alpha_beta": ALPHA_BETA_LIVER, "is_tumor": False},  # tejido normal como higado
    }

    _method = "kernel" if kernel_path else "mctal"
    results = {
        "metadata": {
            "scene": scene_path,
            "mctal": mctal_path,
            "method": _method,
            "activity_bq": activity_bq,
            "activity_gbq": activity_gbq,
            "dimensions": list(dims),
            "nps": mctal_result["nps"],
            "title": mctal_result["title"],
        },
        "structures": {},
        "mird": {},
    }

    for name, info in structures.items():
        idx = info["idx"]
        mask = labelmap == idx if labelmap is not None else None
        n_vox = np.sum(mask) if mask is not None else 0

        if n_vox == 0:
            logger.info(f"  {name} ({idx}): sin voxeles, saltando")
            continue

        # DVH
        dvh = compute_dvh(dose_gy, labelmap, idx)
        logger.info(f"  {name} ({idx}): "
                    f"{dvh['n_voxels']} voxels, "
                    f"Dmedia={dvh['mean_dose_gy']:.2f} Gy, "
                    f"D98={dvh['d98_gy']:.2f} Gy, "
                    f"D95={dvh['d95_gy']:.2f} Gy, "
                    f"D70={dvh['d70_gy']:.2f} Gy, "
                    f"D50={dvh['d50_gy']:.2f} Gy, "
                    f"D5={dvh['d5_gy']:.2f} Gy, "
                    f"D2={dvh['d2_gy']:.2f} Gy, "
                    f"V30={dvh['v30_pct']:.1f}%, "
                    f"V70={dvh['v70_pct']:.1f}%")

        # Radiobiologia
        bio = compute_biophysical(dvh, info["alpha_beta"], info["is_tumor"])
        logger.info(f"    BED={bio['bed_gy']:.2f} Gy, "
                    f"EUD={bio['eud_gy']:.2f} Gy, "
                    f"EQD2={bio['eqd2_gy']:.2f} Gy")

        volume_cm3 = dvh["n_voxels"] * spacing[0] * spacing[1] * spacing[2] / 1000.0
        results["structures"][name] = {
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

    # ----------------------------------------------------------------
    # MIRD partition model
    # ----------------------------------------------------------------
    logger.info("\n--- Paso 7: MIRD partition model ---")
    _log_consola("Paso 7/10: Calculando MIRD partition model...")
    mird = compute_mird(dose_gy, labelmap, activity_gbq)
    results["mird"] = mird
    logger.info(f"  Hígado: {mird['liver']['mean_dose_gy']:.2f} Gy")
    logger.info(f"  Tumor:  {mird['tumor']['mean_dose_gy']:.2f} Gy")
    logger.info(f"  Peritumoral: {mird['pretumor']['mean_dose_gy']:.2f} Gy")
    _ai_review("DVH + MIRD", True, {
        name: {
            "mean_dose_gy": round(s["mean_dose_gy"], 2),
            "d98_gy": round(s.get("d98_gy", 0), 2),
            "d2_gy": round(s.get("d2_gy", 0), 2),
            "bed_gy": round(s.get("bed_gy", 0), 2),
        }
        for name, s in results.get("structures", {}).items()
    })

    # ----------------------------------------------------------------
    # Exportar reporte
    # ----------------------------------------------------------------
    logger.info("\n--- Paso 8: Exportar reporte ---")

    # Reporte JSON
    report_path = os.path.join(output_dir, "dosimetria_report.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"  Reporte JSON: {report_path}")

    # Reporte texto
    report_txt_path = os.path.join(output_dir, "dosimetria_report.txt")
    with open(report_txt_path, "w") as f:
        f.write("=" * 60 + "\n")
        f.write(" REPORTE DE DOSIMETRIA 3Dosim\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Escena:  {scene_path}\n")
        if kernel_path:
            f.write(f"Metodo:  Kernel convolution (rapido)\n")
            f.write(f"Kernel:  {kernel_path}\n")
        else:
            f.write(f"Metodo:  MCTAL (simulacion Monte Carlo)\n")
            f.write(f"MCTAL:   {mctal_path}\n")
            f.write(f"NPS:     {mctal_result['nps']}\n")
        f.write(f"Actividad: {activity_gbq:.4f} GBq ({activity_bq:.2e} Bq)\n")
        f.write(f"Dimensiones: {dims}\n\n")

        f.write("-" * 50 + "\n")
        f.write(" RESULTADOS POR ESTRUCTURA\n")
        f.write("-" * 50 + "\n\n")
        for name, s in results["structures"].items():
            f.write(f"  {name.upper()} (indice={s['index']}):\n")
            f.write(f"    Voxeles:     {s['n_voxels']}\n")
            f.write(f"    Volumen:     {s['volume_cm3']:.2f} cm3\n")
            f.write(f"    Dosis media: {s['mean_dose_gy']:.2f} Gy\n")
            f.write(f"    Dosis min:   {s['min_dose_gy']:.2f} Gy\n")
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
        f.write(f"  Actividad: {activity_gbq:.4f} GBq\n")
        f.write(f"  Higado:    {results['mird']['liver']['mean_dose_gy']:.2f} Gy\n")
        f.write(f"  Tumor:     {results['mird']['tumor']['mean_dose_gy']:.2f} Gy\n")
        f.write(f"  Peritumoral: {results['mird']['pretumor']['mean_dose_gy']:.2f} Gy\n")

        t_elapsed = time.time() - t_start
        f.write(f"\n  Tiempo total: {t_elapsed:.1f} s\n")

    logger.info(f"  Reporte TXT: {report_txt_path}")

    # ----------------------------------------------------------------
    # Generar PDF report
    # ----------------------------------------------------------------
    _log_consola("Paso 8/10: Generando reporte PDF...")
    logger.info("\n--- Paso 8b: Generar PDF report ---")
    # Recolectar curvas DVH para el PDF desde structures del results
    dvh_curves_for_pdf = []
    dvh_pdf_colors = {"higado": (0.2, 0.4, 1.0), "tumor": (1.0, 0.2, 0.2),
                      "pretumor": (0.8, 0.6, 0.0)}
    dvh_pdf_labels = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}
    if not args.no_pdf:
        try:
            for name in structures:
                if name not in results["structures"]:
                    continue
                s = results["structures"][name]
                idx = s["index"]
                mask = labelmap == idx
                doses = dose_gy[mask]
                n = len(doses)
                if n == 0 or np.max(doses) <= 0:
                    continue
                Dmax = float(np.max(doses))
                delta = Dmax / 1000.0
                d_vals = np.arange(0, Dmax + delta, delta)
                a_vals = np.zeros(len(d_vals))
                for i, d in enumerate(d_vals):
                    a_vals[i] = np.sum(doses >= d) * 100.0 / n
                dvh_curves_for_pdf.append((dvh_pdf_labels.get(name, name), d_vals, a_vals))

            pdf_path = generate_pdf_report(results, OUTPUT_DIR_DEFAULT, dvh_curves_for_pdf)
            if pdf_path:
                _log_consola_ok(f"PDF generado: {pdf_path}")
                _ai_review("Reporte PDF generado", True, {"pdf_path": pdf_path})
            else:
                _log_consola_error("No se pudo generar PDF (matplotlib?)")
                _ai_review("Reporte PDF", False, error="PDF generation devolvio None")
        except Exception as e:
            _log_consola_error(f"Error generando PDF: {e}")
            _ai_review("Reporte PDF", False, error=str(e))
            logger.warning(f"  Error generando PDF: {e}")
            import traceback
            logger.warning(traceback.format_exc())
    else:
        _log_consola("  PDF omitido (--no-pdf)")

    if not args.no_slicer:
        # Guardar escena NO BLOQUEANTE (en background, no demora la vista)
        try:
            from qt import QTimer
            scene_final = r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim_dosis_scene.mrb"
            _log_consola("Guardando escena en background...")
            QTimer.singleShot(0, lambda: _save_scene_background(scene_final))
        except Exception as e:
            logger.warning(f"  No se pudo programar guardado: {e}")

    # ----------------------------------------------------------------
    # Tiempo total
    # ----------------------------------------------------------------
    t_elapsed = time.time() - t_start
    logger.info(f"\n  Tiempo total: {t_elapsed:.1f} s")
    logger.info("  Pipeline completado exitosamente!")
    logger.info(f"  Reporte: {report_txt_path}")

    # ----------------------------------------------------------------
    # Crear graficos DVH en Slicer (algoritmo MATLAB f_HDV.m)
    # ----------------------------------------------------------------
    # (DVH plots en background para no congelar consola)
    if not args.no_slicer:
        from qt import QTimer
        def _run_dvh_plots_later():
            try:
                logger.info("  Graficando DVH en Slicer (background)...")
                _create_dvh_plots_slicer(dose_gy, labelmap, spacing, args.show)
                logger.info("  DVH plots completados")
            except Exception as e:
                logger.warning(f"  Error creando DVH plots: {e}")
                import traceback
                logger.warning(traceback.format_exc())
        QTimer.singleShot(200, _run_dvh_plots_later)

    # Resumen final en consola
    _log_consola("=" * 50)
    _log_consola("PIPELINE DE DOSIMETRIA COMPLETADO")
    _log_consola(f"  Actividad: {activity_gbq:.4f} GBq")
    for name, s in results.get("structures", {}).items():
        label = {"higado": "Hígado", "tumor": "Tumor", "pretumor": "Peritumoral"}.get(name, name)
        _log_consola(f"  {label}: Dmedia={s.get('mean_dose_gy', 0):.2f} Gy, "
                     f"BED={s.get('bed_gy', 0):.2f} Gy")
    pdf_full = os.path.join(OUTPUT_DIR_DEFAULT, "dosimetria_report.pdf")
    _log_consola(f"  PDF: {pdf_full}")
    _log_consola("=" * 50)

    # Mantener Slicer abierto si --show O si hay consola interactiva
    keep_alive = args.show or (consola is not None)
    if keep_alive:
        logger.info("[INIT] Configurando display final...")
        if args.show:
            # --- Layout + Crosshair + Translate + Jump + Reset 3D (TODO sincrónico) ---
            _ras_max = _setup_display_sync(dose_node, dose_gy)
            # Timer solo para re-asignar DVH chart (2000ms post-DVH para asegurar)
            QTimer.singleShot(2200,
                lambda r=_ras_max, dn=dose_node, dg=dose_gy:
                    _reassign_dvh_chart(r, dn, dg))
            logger.info("[INIT] Display sincronico OK + timer reassign DVH@2200ms")
            # Timer de SEGURIDAD a los 60s: re-aplica jump/FOV/crosshair/chart
            # (la isodosis termina ~33s, esto es mucho despues)
            QTimer.singleShot(60000,
                lambda dn=dose_node, dg=dose_gy:
                    _reassign_dvh_chart(None, dn, dg))
            logger.info("[INIT] Safety timer @60000ms (re-aplica display post-isodosis)")

        if consola:
            _log_consola("Consola activa. Escribi 'ayuda' para comandos, 'salir' para cerrar.")

        logger.info("  --show: Slicer queda abierto. Cerrar ventana para salir.")
        logger.info("  Consola interactiva activa.")
        sys.stderr.flush()
        # Loop: mantiene vivo tanto Slicer como la consola
        try:
            while True:
                slicer.app.processEvents()
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    return 0


def _jump_to_max_dose(dose_node, dose_gy, label="[JUMP]"):
    """Helper: lleva slices 2D al voxel de maxima dosis.
    Usa SetSliceOffset DIRECTO (bypass de JumpSlice que falla con slices linkeados).
    Retorna RAS [x,y,z] o None si fallo."""
    if dose_node is None or dose_gy is None:
        logger.warning(f"{label} No dose data")
        return None
    try:
        import vtk as _vtk_j
        _max_f = np.argmax(dose_gy)
        _max_i = np.unravel_index(_max_f, dose_gy.shape)
        _ijk_j = [float(_max_i[2]), float(_max_i[1]), float(_max_i[0]), 1.0]
        _mat_j = _vtk_j.vtkMatrix4x4()
        dose_node.GetIJKToRASMatrix(_mat_j)
        _r_j = [0.0, 0.0, 0.0, 0.0]
        _mat_j.MultiplyPoint(_ijk_j, _r_j)
        ras = list(_r_j[:3])
        logger.info(f"{label} Max dose RAS: {ras}")
        # ── Metodo 1: SetSliceOffset DIRECTO en cada slice node ──
        _ok = 0
        for _sn in slicer.util.getNodesByClass("vtkMRMLSliceNode"):
            try:
                # Calcular offset: producto punto entre RAS target y el normal del slice
                _stor = _vtk_j.vtkMatrix4x4()
                _sn.GetSliceToRAS(_stor)
                _n0 = _stor.GetElement(0, 2)
                _n1 = _stor.GetElement(1, 2)
                _n2 = _stor.GetElement(2, 2)
                _off = _n0 * ras[0] + _n1 * ras[1] + _n2 * ras[2]
                _sn.SetSliceOffset(_off)
                _ok += 1
            except Exception as _ej:
                logger.warning(f"{label} SetSliceOffset fallo en {_sn.GetName()}: {_ej}")
        logger.info(f"{label} OK SetSliceOffset directo en {_ok} slice nodes")
        # ── Metodo 2: markups (fallback, por si el directo no basto) ──
        try:
            _ml = slicer.modules.markups.logic()
            _ml.JumpSlicesToLocation(ras[0], ras[1], ras[2], True)
            logger.info(f"{label} OK markups.JumpSlicesToLocation (adicional)")
        except Exception as _e2:
            logger.debug(f"{label} markups fallo: {_e2}")
        # ── Forzar render ──
        try:
            _lm_j = slicer.app.layoutManager()
            for _i_j in range(_lm_j.sliceViewCount()):
                _lm_j.sliceWidget(_i_j).sliceView().scheduleRender()
            # fuerza render inmediato
            slicer.app.processEvents()
        except Exception:
            pass
        return ras
    except Exception as _e:
        logger.warning(f"{label} Helper fallo: {_e}")
        import traceback
        logger.warning(traceback.format_exc())
        return None


def _reset_slice_fov(fov_mm=300.0, label="[FOV]"):
    """Helper: fija FieldOfView de TODOS los slice nodes a un valor fijo
    SIN mover la posicion (a diferencia de resetSliceViews que resetea todo).
    fov_mm: tamano en mm del FOV cuadrado (default 300mm)."""
    _ok = 0
    for _sn_fov in slicer.util.getNodesByClass("vtkMRMLSliceNode"):
        try:
            _sn_fov.SetFieldOfView(fov_mm, fov_mm, fov_mm)
            _ok += 1
        except Exception as _ef:
            logger.debug(f"{label} FOV fallo en {_sn_fov.GetName()}: {_ef}")
    if _ok:
        logger.info(f"{label} FOV={fov_mm}mm fijado en {_ok} slice nodes")


def _enable_crosshair(label="[CROSSHAIR]"):
    """Activa lineas de interseccion del crosshair.
    Usa slicer.vtkMRMLCrosshairNode.ShowIntersectionLines
    (constante de clase, NO atributo de instancia).
    """
    # Obtener el valor del modo (2 = ShowIntersectionLines)
    try:
        _crosshair_mode = slicer.vtkMRMLCrosshairNode.ShowIntersectionLines
    except AttributeError:
        _crosshair_mode = 2  # fallback numerico
    # Metodo 1: via crosshair logic
    try:
        _cl = slicer.modules.crosshair.logic()
        _cn = _cl.GetCrosshairNode()
        if _cn:
            _cn.SetCrosshairMode(_crosshair_mode)
            logger.info(f"{label} ShowIntersectionLines (via crosshair logic, mode={_crosshair_mode})")
            return
    except Exception as _e1:
        logger.debug(f"{label} crosshair logic fallo: {_e1}")
    # Metodo 2: via getNode
    try:
        _cn2 = slicer.util.getNode(pattern="Crosshair")
        if _cn2:
            _cn2.SetCrosshairMode(_crosshair_mode)
            logger.info(f"{label} ShowIntersectionLines (via getNode, mode={_crosshair_mode})")
            return
    except Exception as _e2:
        logger.warning(f"{label} getNode fallo: {_e2}")


def _setup_display_sync(dose_node, dose_gy):
    """Configura el display COMPLETO de forma sincrónica:
    layout, crosshair, translate, jump a max dosis, reset 3D FOV.
    Retorna _ras_max para uso posterior.
    """
    _ras_max = None
    try:
        from slicer import vtkMRMLLayoutNode as _LayoutNode
        _lm = slicer.app.layoutManager()
        # ── 1. Layout ──
        _layout_plot = getattr(_LayoutNode, "SlicerLayoutConventionalPlotView", None)
        if _layout_plot is not None:
            _lm.setLayout(_layout_plot)
            logger.info("[LAYOUT] ConventionalPlotView: 3D+plot / 3 slices")
        else:
            _layout_4up = getattr(_LayoutNode, "SlicerLayoutFourUpPlotView", None)
            if _layout_4up is not None:
                _lm.setLayout(_layout_4up)
                logger.info("[LAYOUT] FourUpPlotView (fallback)")
            else:
                _lm.setLayout(_LayoutNode.SlicerLayoutConventionalView)
                logger.info("[LAYOUT] ConventionalView (sin plot)")
        slicer.app.processEvents()
        # ── 2. Crosshair ──
        _enable_crosshair()
        # ── 3. Translate-only ──
        try:
            for _sn in slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode"):
                _sn.SetInteractionMode(_sn.TranslateSlice)
            logger.info("[TRANSLATE] Modo solo trasladar activado")
        except Exception as _e:
            logger.debug(f"[TRANSLATE] fallo: {_e}")
        # ── 4. Calcular y saltar a maxima dosis ──
        _ras_max = _jump_to_max_dose(dose_node, dose_gy, label="[JUMP-SYNC]")
        # ── 5. Reset 3D FOV ──
        try:
            _tw = _lm.threeDWidget(0) if _lm else None
            if _tw:
                _tw.threeDView().resetFocalPoint()
                logger.info("[3DFOV] Reset FOV ejecutado")
        except Exception as _e:
            logger.debug(f"[3DFOV] fallo: {_e}")
        logger.info("[DISPLAY] Setup sincronico completado exitosamente")
    except Exception as _e:
        logger.warning(f"[DISPLAY] Error en setup sincronico: {_e}")
        import traceback
        logger.warning(traceback.format_exc())
    return _ras_max


def _reassign_dvh_chart(ras_max=None, dose_node=None, dose_gy=None):
    """Timer postergado (~2200ms): re-asigna chart DVH + re-aplica jump/FOV/crosshair.
    Se ejecuta DESPUES de que la isodosis (100ms) y DVH (200ms) terminaron,
    para asegurar que todo quede en su estado final.
    """
    # ── A) Re-asignar DVH chart ──
    try:
        chart_node = slicer.util.getNode("DVH_Chart")
        if chart_node:
            _pv_nodes = slicer.util.getNodesByClass("vtkMRMLPlotViewNode")
            if _pv_nodes:
                _pv_nodes[0].SetPlotChartNodeID(chart_node.GetID())
                logger.info("[DVH] Chart re-asignado al PlotViewNode correctamente")
            else:
                logger.warning("[DVH] No se encontraron PlotViewNodes en la escena")
        else:
            logger.warning("[DVH] No se encontro 'DVH_Chart' en la escena")
    except Exception as e:
        logger.warning(f"[DVH] Error re-asignando chart: {e}")
    # ── B) Re-aplicar crosshair ──
    _enable_crosshair(label="[FINAL]")
    # ── C) Re-aplicar jump + 3D FOV ──
    _jump_to_max_dose(dose_node, dose_gy, label="[FINAL]")
    try:
        _lm2 = slicer.app.layoutManager()
        _tw2 = _lm2.threeDWidget(0) if _lm2 else None
        if _tw2:
            _tw2.threeDView().resetFocalPoint()
            logger.info("[FINAL] 3D FOV reseteado")
    except Exception as _e3:
        logger.warning(f"[FINAL] 3D FOV fallo: {_e3}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as _fatal:
        import traceback
        _tb = traceback.format_exc()
        # Log a archivo
        try:
            logger.error(f"FATAL: {_fatal}")
            logger.error(_tb)
        except Exception:
            pass
        # Log a stderr para launcher
        print(f"[3Dosim FATAL] {_fatal}", file=sys.stderr)
        print(_tb, file=sys.stderr)
        # Mostrar dialogo en Slicer si esta disponible
        try:
            import slicer
            from qt import QMessageBox
            QMessageBox.critical(
                None, "3Dosim — Error Fatal",
                f"Error no controlado:\n\n{_fatal}\n\n"
                f"Revise la consola de Slicer para detalles.\n"
                f"Slicer se cerrara en 60 segundos."
            )
            # Esperar y cerrar
            import time as _t
            _t0 = _t.time()
            while _t.time() - _t0 < 60:
                slicer.app.processEvents()
                _t.sleep(0.5)
            slicer.app.quit()
        except Exception:
            pass
        sys.exit(1)
