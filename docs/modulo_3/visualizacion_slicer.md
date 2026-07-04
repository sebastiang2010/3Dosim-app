# Visualización en 3D Slicer

> **Del mapa de dosis numérico a contornos clínicos interpretables.** Este documento describe cómo se renderiza el mapa de dosis 3D en 3D Slicer, la generación de contornos de isodosis, y la visualización interactiva del DVH, siguiendo la implementación del MATLAB legacy y utilizando las capacidades nativas de Slicer.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| VTK | Visualization Toolkit (motor gráfico de Slicer) |
| MRML | Medical Reality Markup Language (árbol de Slicer) |
| CLUT | Color Look-Up Table |
| ROI | Region of Interest |
| RAS | Right-Anterior-Superior (sistema de coordenadas Slicer) |
| IJK | Índices de voxel (i, j, k) |
| IJKToRAS | Matriz de transformación voxel → coordenadas anatómicas |
| FPE | Focal Point Elevation (ángulo de cámara 3D) |
| GPU | Graphics Processing Unit |
| FPS | Frames Per Second |
| Fog | Efecto de niebla para profundidad en 3D |

---

## 1. Nodo de Dosis 3D en Slicer

### 1.1 Creación del Nodo

El mapa de dosis se carga en Slicer como un `vtkMRMLScalarVolumeNode` con overlay rainbow invertido:

```python
import slicer
import numpy as np

def create_dose_volume(dose_gy: np.ndarray,
                       reference_volume: slicer.vtkMRMLScalarVolumeNode,
                       node_name: str = "Dosis_Y90_Gy") -> slicer.vtkMRMLScalarVolumeNode:
    """
    Crear nodo de dosis en Slicer.

    Parameters
    ----------
    dose_gy : np.ndarray
        Mapa de dosis 3D en Gy, shape [nx, ny, nz].
    reference_volume : vtkMRMLScalarVolumeNode
        Volumen de referencia (CT) para heredar IJKToRAS.
    node_name : str
        Nombre del nodo en la escena.

    Returns
    -------
    dose_node : vtkMRMLScalarVolumeNode
        Nodo de dosis listo para visualizar.
    """

    # Crear nodo
    dose_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLScalarVolumeNode", node_name)

    # Copiar geometría del CT de referencia
    dose_node.CopyOrientation(reference_volume)
    dose_node.SetSpacing(reference_volume.GetSpacing())
    dose_node.SetOrigin(reference_volume.GetOrigin())

    # Asignar datos
    import vtk
    vtk_array = vtk.vtkFloatArray()
    vtk_array.SetNumberOfComponents(1)
    dose_flat = dose_gy.ravel(order='F').astype(np.float32)
    vtk_array.SetVoidArray(dose_flat, len(dose_flat), 1)

    vtk_data = vtk.vtkImageData()
    vtk_data.SetDimensions(dose_gy.shape)
    vtk_data.GetPointData().SetScalars(vtk_array)

    dose_node.SetAndObserveImageData(vtk_data)

    return dose_node
```

### 1.2 Overlay Rainbow Invertido

El overlay de dosis se configura con una Look-Up Table (LUT) rainbow invertida:

```python
def configure_dose_display(dose_node, dmax_gy: float):
    """Configurar overlay rainbow invertido para dosis."""

    dn = dose_node.GetDisplayNode()
    if dn is None:
        dn = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLScalarVolumeDisplayNode", f"{dose_node.GetName()}_Display")
        dose_node.SetAndObserveDisplayNodeID(dn.GetID())

    # Crear LUT rainbow invertida
    lut = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLColorTableNode", f"{dose_node.GetName()}_LUT")
    lut.SetTypeToUser()

    # Mapeo: 0 Gy → negro, 1→azul, 2→cyan, ..., 10→rojo
    colors = [
        (0.0, 0.0, 0.0, 0.0),    # 0%: transparente
        (0.0, 0.0, 0.5, 0.3),    # 10%: azul oscuro
        (0.0, 0.0, 1.0, 0.4),    # 20%: azul
        (0.0, 0.5, 1.0, 0.5),    # 30%: cyan
        (0.0, 1.0, 1.0, 0.6),    # 40%: verde
        (0.5, 1.0, 0.0, 0.7),    # 50%: amarillo-verde
        (1.0, 1.0, 0.0, 0.8),    # 60%: amarillo
        (1.0, 0.5, 0.0, 0.9),    # 80%: naranja
        (1.0, 0.0, 0.0, 1.0),    # 100%: rojo
    ]

    lut.SetNumberOfColors(len(colors))
    for i, (r, g, b, a) in enumerate(colors):
        lut.SetColor(i, r, g, b, a)

    dn.SetAndObserveColorNodeID(lut.GetID())
    dn.SetWindowLevel(dmax_gy, dmax_gy / 2)
```

---

## 2. Isodosis

### 2.1 Niveles

Se generan **10 niveles** de isodosis desde 10% hasta 100% de la dosis máxima:

```python
import numpy as np
from scipy.ndimage import gaussian_filter

DEFAULT_ISODOSE_LEVELS_PCT = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
```

### 2.2 Smoothing

Antes de generar contornos, se aplica un filtro Gaussiano 3D (equivalente a `smooth3` de MATLAB):

```python
dose_smooth = gaussian_filter(dose_gy, sigma=1.0)
```

### 2.3 Colormap Jet (10 muestras)

```python
import matplotlib.cm as mpl_cm

def _get_jet_colors(n_levels: int = 10):
    """Obtener colores jet para n niveles de isodosis."""
    jet = mpl_cm.get_cmap('jet')
    return [jet(i / (n_levels - 1)) for i in range(n_levels)]
```

### 2.4 Generación de Contornos (VTK Marching Cubes)

```python
def create_isodose_contours(dose_smooth: np.ndarray,
                             dose_node, dmax_gy: float,
                             levels_pct: list = None):
    """
    Generar contornos de isodosis usando VTK Marching Cubes.

    Parameters
    ----------
    dose_smooth : np.ndarray
        Dosis suavizada con gaussian_filter.
    dose_node : vtkMRMLScalarVolumeNode
        Nodo de volumen de dosis en Slicer.
    dmax_gy : float
        Dosis máxima para escalar niveles.
    levels_pct : list
        Porcentajes de isodosis (default: 10 niveles 10-100%).
    """

    if levels_pct is None:
        levels_pct = DEFAULT_ISODOSE_LEVELS_PCT

    colors = _get_jet_colors(len(levels_pct))

    for i, pct in enumerate(levels_pct):
        d_level = dmax_gy * pct / 100.0

        # Marching Cubes via vtk
        import vtk
        mc = vtk.vtkDiscreteMarchingCubes()
        mc.SetInputData(dose_node.GetImageData())
        mc.SetValue(0, d_level)
        mc.Update()

        # Crear nodo de modelo en Slicer
        model_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLModelNode", f"Isodosis_{pct}pct")

        model_node.SetAndObserveMesh(mc.GetOutput())

        # Asignar color
        r, g, b, a = colors[i]
        display_node = model_node.GetDisplayNode()
        if display_node is None:
            display_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLModelDisplayNode",
                f"{model_node.GetName()}_Display")
            model_node.SetAndObserveDisplayNodeID(display_node.GetID())

        display_node.SetColor(r, g, b)
        display_node.SetOpacity(0.3 + 0.5 * (pct / 100.0))
```

### 2.5 Fallback: SlicerRT Isodose Module

Si el módulo **SlicerRT** está disponible, se usa su generación nativa de isodosis:

```python
def create_isodoses_slicerrt(dose_node, dmax_gy):
    """Usar SlicerRT Isodose module si está disponible."""
    try:
        from SlicerRT import IsodoseModule
        logic = IsodoseModule.IsodoseLogic()
        logic.createIsodoses(dose_node, [dmax_gy * p / 100
                                         for p in DEFAULT_ISODOSE_LEVELS_PCT])
    except ImportError:
        # Fallback a VTK Marching Cubes
        create_isodose_contours(dose_node, dmax_gy)
```

---

## 3. DVH Interactivo en Slicer

### 3.1 Módulo Plots

El DVH se visualiza usando el módulo nativo **Plots** de Slicer:

```python
def create_dvh_plot(dvh_data: dict, rois: list, dose_node):
    """Crear DVH interactivo en módulo Plots de Slicer."""

    plot_chart = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLPlotChartNode", "DVH")

    colors = {
        'Hígado': (0.0, 0.0, 1.0),
        'Tumor': (1.0, 0.0, 0.0),
        'Peritumoral': (1.0, 1.0, 0.0),
        'Body': (0.0, 0.5, 0.0),
    }

    for roi_name in rois:
        if roi_name not in dvh_data:
            continue

        series = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLPlotSeriesNode", f"DVH_{roi_name}")

        thresholds = dvh_data[roi_name]['dose_threshold']
        volumes = dvh_data[roi_name]['volume_pct']

        # Crear arrays VTK
        import vtk
        arr_x = vtk.vtkFloatArray()
        arr_y = vtk.vtkFloatArray()
        for t, v in zip(thresholds, volumes):
            arr_x.InsertNextValue(t)
            arr_y.InsertNextValue(v)

        arr_x.SetName("Dosis [Gy]")
        arr_y.SetName("Volumen [%]")

        # Asignar arrays
        obarray = vtk.vtkFloatArray()
        obarray.SetNumberOfComponents(2)
        for i in range(len(thresholds)):
            obarray.InsertNextTuple2(thresholds[i], volumes[i])

        series.SetAndObserveData(obarray)
        series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeLine)
        series.SetColor(*colors.get(roi_name, (0.5, 0.5, 0.5)))

        # Agregar al chart
        plot_chart.AddAndObservePlotSeriesNodeID(series.GetID())

    # Configurar ejes
    plot_chart.SetXAxisTitle("Dosis [Gy]")
    plot_chart.SetYAxisTitle("Volumen [%]")
    plot_chart.SetYAxisTypeToLog()
    plot_chart.SetXAxisRange(0, dvh_data[rois[0]]['dose_threshold'][-1])
```

### 3.2 Selección del Módulo Plots

```python
# Activar el módulo Plots en Slicer
slicer.util.selectModule("Plots")
```

---

## 4. Guardado de Escena Final

Al finalizar, se guarda la escena completa con todos los nodos:

```python
def save_final_scene(output_dir: str):
    """
    Guardar escena final con dosis, isodosis y DVH.

    Archivos generados:
    - 3Dosim_dosis_final.mrb — Escena completa
    - dose_gy.nrrd — Mapa de dosis en formato NRRD
    - dose_gy.nii — Mapa de dosis en formato NIfTI
    """
    scene_path = os.path.join(output_dir, "scenes", "3Dosim_dosis_final.mrb")
    slicer.util.saveScene(scene_path)

    dose_path_nrrd = os.path.join(output_dir, "dose", "dose_gy.nrrd")
    slicer.util.saveNode(dose_node, dose_path_nrrd)
```

---

## 5. Layout de Visualización

```
┌────────────────────────────────────────────────────────────┐
│              3D Slicer — 3Dosim Dosis Final                │
├────────────┬────────────┬────────────┬─────────────────────┤
│            │            │            │                     │
│   Axial    │  Sagital   │  Coronal   │      Vista 3D       │
│   CT +     │   CT +     │   CT +     │  (Volume Rendering  │
│  dosis     │  dosis     │  dosis     │   + isodosis)       │
│  overlay   │  overlay   │  overlay   │                     │
│            │            │            │                     │
│            │            │            │                     │
├────────────┴────────────┴────────────┴─────────────────────┤
│                    DVH Plot (abajo)                        │
│      ┌─────────────────────────────────────────┐           │
│      │  % Vol vs Dosis [Gy] (log Y)            │           │
│      │  4 curvas: Híg, Tum, Peri, Body         │           │
│      └─────────────────────────────────────────┘           │
└────────────────────────────────────────────────────────────┘
```

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| Nodo de dosis creado | No existe nodo dosis en la escena |
| Overlay visible | Dosis display node mal configurado |
| Isodosis generadas | Número de contornos < 10 |
| Isodosis cubren el hígado+tumor | Contornos fuera de las ROIs |
| DVH con 4 curvas | Faltan ROIs principales |
| Escena final guardada | Archivo .mrb no se creó |
| Coordenadas consistentes | Nodo dosis fuera de alineación con CT |

---

## 7. Referencias

- 3D Slicer Documentation: "Data Visualization with Volume Rendering"
- SlicerRT: "Isodose Contour Generation" (slicerrt.org)
- VTK User's Guide: "Marching Cubes" (vtk.org)
- MATLAB `f_Isodosis.m` de 3Dosim v3.14 (`modulo_3/`)
- `isodose_contours.py` en `PipelineOrchestrator/`
- `SlicerDosimMod3.py` en `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/`
