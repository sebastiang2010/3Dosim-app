"""
isodose_contours.py - Generacion de curvas/superficies de isodosis.

Usa el modulo Isodose de SlicerRT (vtkSlicerIsodoseModuleLogic) si esta disponible.
Si no, usa vtkImageMarchingCubes como fallback (siempre disponible en Slicer).

Isodosis relativas (% del maximo), identico MATLAB:
  D31 = smooth3(D3);
  D31 = floor(D31 .* 100 ./ maximo);
  v = 10:10:100;  % 10 niveles
  ncolor = 10; map = colormap(jet);
"""

import logging
import numpy as np
logger = logging.getLogger(__name__)

# Niveles de isodosis default (% del maximo) - identico MATLAB v=10:10:100
DEFAULT_ISODOSE_LEVELS_PCT = list(range(10, 101, 10))  # [10, 20, ..., 100], 10 niveles

# Colores jet con 10 muestras (MATLAB: colormap(jet), ncolor=10)
_JET_COLORS = None
def _get_jet_colors(n=10):
    global _JET_COLORS
    if _JET_COLORS is None or len(_JET_COLORS) != n:
        # Jet colormap: n muestras uniformes (idem MATLAB)
        # jet = [(0,0,0.5) -> (0,0,1) -> (0,1,1) -> (1,1,0) -> (1,0,0) -> (0.5,0,0)]
        # Muestrear n colores del jet
        cmap = np.array([
            [0.000, 0.000, 0.516],
            [0.000, 0.000, 1.000],
            [0.000, 0.379, 1.000],
            [0.000, 0.757, 1.000],
            [0.000, 0.937, 0.937],
            [0.379, 1.000, 0.379],
            [0.757, 1.000, 0.000],
            [1.000, 0.937, 0.000],
            [1.000, 0.379, 0.000],
            [0.500, 0.000, 0.000],
        ])
        # Interpolar si n != 10
        if n != len(cmap):
            x_old = np.linspace(0, 1, len(cmap))
            x_new = np.linspace(0, 1, n)
            _JET_COLORS = list(zip(np.interp(x_new, x_old, cmap[:, 0]), np.interp(x_new, x_old, cmap[:, 1]), np.interp(x_new, x_old, cmap[:, 2])))
        else:
            _JET_COLORS = [tuple(c) for c in cmap]
    return _JET_COLORS

_HAS_SLICERRT = None


def _check_slicerrt():
    """Verifica si SlicerRT con modulo Isodose esta disponible."""
    global _HAS_SLICERRT
    if _HAS_SLICERRT is not None:
        return _HAS_SLICERRT
    try:
        import slicer
        if hasattr(slicer.modules, 'isodose'):
            logic = slicer.modules.isodose.logic()
            _HAS_SLICERRT = logic is not None
        else:
            _HAS_SLICERRT = False
    except Exception:
        _HAS_SLICERRT = False
    return _HAS_SLICERRT


def create_isodose_contours(dose_node, levels=None,
                            show_lines_2d=True, show_surfaces_3d=True,
                            relative=True):
    """
    Genera curvas/superficies de isodosis.

    Prioriza SlicerRT Isodose module. Si no disponible, usa VTK marching cubes.

    Args:
        dose_node: vtkMRMLScalarVolumeNode con dosis en Gy.
        levels: Lista de niveles en % (0-100). Default: [10,20,...,100].
        show_lines_2d: Mostrar interseccion en slices 2D.
        show_surfaces_3d: Mostrar superficies en vista 3D.
        relative: Si True (default), niveles son % del maximo.

    Returns:
        tuple: (model_node, param_node_or_None)
    """
    import slicer

    if levels is None:
        levels = DEFAULT_ISODOSE_LEVELS_PCT

    # Convertir % a Gy absolutos
    import numpy as np
    arr = slicer.util.arrayFromVolume(dose_node)
    max_dose = float(np.max(arr))
    if max_dose > 0:
        levels_gy = [float(l) * max_dose / 100.0 for l in levels]
        logger.info(f"  Isodosis relativas: niveles %={levels} → Gy={[f'{v:.1f}' for v in levels_gy]}, "
                    f"max_dose={max_dose:.1f} Gy")
    else:
        logger.warning("  Dosis maxima es 0, usando niveles por defecto")
        levels_gy = list(levels)
        relative = False

    if _check_slicerrt():
        model_node, param = _create_via_slicerrt(
            dose_node, levels_gy, show_lines_2d, show_surfaces_3d,
            relative=relative, levels_pct=levels if relative else None
        )
        if model_node:
            return model_node, param
        logger.info("Fallback a VTK marching cubes...")

    return _create_via_vtk(dose_node, levels_gy, show_lines_2d, show_surfaces_3d)


# ── SlicerRT Isodose module ──────────────────────────────────────────────

def _create_via_slicerrt(dose_node, levels, show_lines_2d, show_surfaces_3d,
                         relative=False, levels_pct=None):
    """Genera isodosis via SlicerRT Isodose module."""
    import slicer

    # Aplicar smooth3 (Gaussian) a la dosis antes de contornear - identico MATLAB smooth3(D3)
    try:
        dose_arr = slicer.util.arrayFromVolume(dose_node)
        from scipy.ndimage import gaussian_filter
        dose_smooth = gaussian_filter(dose_arr.astype(np.float64), sigma=1.0)
        # Crear volumen temporal para isodosis
        smooth_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeNode", f"{dose_node.GetName()}_Smoothed")
        slicer.util.updateVolumeFromArray(smooth_node, dose_smooth)
        smooth_node.SetSpacing(dose_node.GetSpacing())
        smooth_node.SetOrigin(dose_node.GetOrigin())
        smooth_node.SetIJKToRASMatrix(dose_node.GetIJKToRASMatrix())
        logger.info("  Smooth3 (Gaussian sigma=1) aplicado para isodosis")
    except Exception as e:
        logger.warning(f"  Smooth3 fallo, usando dosis original: {e}")
        smooth_node = dose_node

    units_str = "%" if relative else "Gy"
    logger.info(f"Generando isodosis via SlicerRT: {len(levels)} niveles "
                f"({min(levels):.1f}-{max(levels):.1f} {units_str})")

    try:
        isodose_logic = slicer.modules.isodose.logic()

        # Nodo de parametros Isodose
        param_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLIsodoseNode")
        param_node.SetDoseVolumeNode(smooth_node)
        param_node.SetDoseUnits(0)  # 0 = Gy (el volumen esta en Gy)

        # ── Isolevels relativos (% de la dosis maxima) ──
        try:
            param_node.SetIsodoseRelativeDose(1 if relative else 0)
            logger.info(f"  Isodosis {'relativas (%)' if relative else 'absolutas (Gy)'}")
        except AttributeError:
            logger.warning("  SetIsodoseRelativeDose no disponible en esta version de SlicerRT")

        # Tabla de colores
        isodose_logic.SetupColorTableNodeForDoseVolumeNode(smooth_node)
        color_table_node = param_node.GetColorTableNode()
        if not color_table_node:
            logger.error("  No se pudo crear tabla de colores")
            return None, None

        # Cantidad de niveles
        isodose_logic.SetNumberOfIsodoseLevels(param_node, len(levels))

        # Asignar colores jet a cada nivel (MATLAB: colormap(jet), ncolor=10)
        jet_colors = _get_jet_colors(len(levels))
        for i, level in enumerate(levels):
            color = jet_colors[i]
            label = f"{level:.0f}%" if relative else f"{level:.1f} Gy"
            color_table_node.SetColor(i, label,
                                      color[0], color[1], color[2], 1.0)

        # Generar
        ok = isodose_logic.CreateIsodoseSurfaces(param_node)
        if not ok:
            logger.error("  CreateIsodoseSurfaces devolvio False")
            return None, None

        model_node = param_node.GetIsosurfacesModelNode()
        if not model_node:
            logger.warning("  No se genero modelo de isodosis")
            return None, None

        logger.info(f"  Superficies creadas: {model_node.GetName()}")

        # Display
        disp = model_node.GetModelDisplayNode()
        if disp:
            disp.SetSliceIntersectionVisibility(show_lines_2d)
            disp.SetVisibility(show_surfaces_3d)
            if show_lines_2d:
                disp.SetSliceIntersectionThickness(2)

        try:
            isodose_logic.SetColorLegendDefaults(param_node)
        except Exception:
            pass

        return model_node, param_node

    except Exception as e:
        logger.warning(f"  SlicerRT Isodose fallo: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None, None


# ── VTK fallback (sin dependencia SlicerRT) ─────────────────────────────

def _create_via_vtk(dose_node, levels, show_lines_2d, show_surfaces_3d):
    """Genera isodosis usando vtkImageMarchingCubes (siempre disponible)."""
    import slicer
    import vtk

    logger.info(f"Generando isodosis via VTK: {len(levels)} niveles")

    try:
        dose_img = dose_node.GetImageData()
        if not dose_img:
            logger.error("  El nodo de dosis no tiene ImageData")
            return None, None

        # Aplicar smooth3 (Gaussian) a la dosis - identico MATLAB smooth3(D3)
        try:
            dose_arr = slicer.util.arrayFromVolume(dose_node)
            from scipy.ndimage import gaussian_filter
            dose_smooth = gaussian_filter(dose_arr.astype(np.float64), sigma=1.0)
            smooth_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeNode", f"{dose_node.GetName()}_Smoothed_VTK")
            slicer.util.updateVolumeFromArray(smooth_node, dose_smooth)
            smooth_node.SetSpacing(dose_node.GetSpacing())
            smooth_node.SetOrigin(dose_node.GetOrigin())
            smooth_node.SetIJKToRASMatrix(dose_node.GetIJKToRASMatrix())
            dose_img = smooth_node.GetImageData()
            logger.info("  Smooth3 (Gaussian sigma=1) aplicado para isodosis VTK")
        except Exception as e:
            logger.warning(f"  Smooth3 fallo, usando dosis original VTK: {e}")

        # Nodo modelo
        base = f"{dose_node.GetName()}_IsodoseLevels"
        model_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLModelNode",
            slicer.mrmlScene.GenerateUniqueName(base)
        )
        model_node.CreateDefaultDisplayNodes()

        # Matriz IJK->RAS
        ijk2ras = vtk.vtkMatrix4x4()
        dose_node.GetIJKToRASMatrix(ijk2ras)

        append = vtk.vtkAppendPolyData()
        colors_array = vtk.vtkFloatArray()
        colors_array.SetNumberOfComponents(1)
        colors_array.SetName("isolevels")

        for level in levels:
            mc = vtk.vtkImageMarchingCubes()
            mc.SetInputData(dose_img)
            mc.SetNumberOfContours(1)
            mc.SetValue(0, float(level))
            mc.SetComputeScalars(False)
            mc.SetComputeGradients(False)
            mc.SetComputeNormals(False)
            mc.Update()

            poly = mc.GetOutput()
            if poly.GetNumberOfPoints() < 1:
                continue

            # IJK -> RAS
            t = vtk.vtkTransform()
            t.SetMatrix(ijk2ras)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetInputData(poly)
            tf.SetTransform(t)
            tf.Update()

            transformed = tf.GetOutput()
            for _ in range(transformed.GetNumberOfPoints()):
                colors_array.InsertNextTuple1(float(level))

            append.AddInputData(transformed)

        append.Update()
        final_poly = append.GetOutput()

        if final_poly.GetNumberOfPoints() == 0:
            logger.warning("  Ningun nivel genero puntos de isodosis")
            return None, None

        final_poly.GetPointData().SetScalars(colors_array)
        model_node.SetAndObservePolyData(final_poly)

        # Tabla de colores jet (MATLAB: colormap(jet), ncolor=10)
        jet_colors = _get_jet_colors(len(levels))
        ctbl = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLColorTableNode",
            f"{model_node.GetName()}_ColorTable"
        )
        ctbl.SetTypeToUser()
        ctbl.SetNumberOfColors(len(levels))
        ctbl.GetLookupTable().SetTableRange(0, len(levels) - 1)
        for i, level in enumerate(levels):
            c = jet_colors[i]
            ctbl.AddColor(str(level), c[0], c[1], c[2], 1.0)
        ctbl.SaveWithSceneOff()

        # Display
        disp = model_node.GetModelDisplayNode()
        if disp:
            disp.SetActiveScalarName("isolevels")
            disp.SetAndObserveColorNodeID(ctbl.GetID())
            disp.SetScalarVisibility(True)
            disp.SetAutoScalarRange(True)
            disp.SetBackfaceCulling(0)
            disp.SetSliceIntersectionVisibility(show_lines_2d)
            disp.SetVisibility(show_surfaces_3d)
            if show_lines_2d:
                disp.SetSliceIntersectionThickness(2)

        logger.info(f"  {len(levels)} niveles generados via VTK fallback")
        return model_node, None

    except Exception as e:
        logger.error(f"  VTK fallback fallo: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None, None
