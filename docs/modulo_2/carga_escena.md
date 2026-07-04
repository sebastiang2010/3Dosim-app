# Carga de Escena 3D Slicer

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| .mrb | Medical Reality Bundle (escena comprimida de 3D Slicer) |
| RAS | Right-Anterior-Superior (sistema de coordenadas Slicer) |
| IJK | Índices de voxel (columna, fila, slice) |
| LPS | Left-Posterior-Superior (sistema MCNP) |
| VOI | Volume of Interest |
| MRML | Medical Reality Markup Language (formato interno de Slicer) |
| NRRD | Nearly Raw Raster Data (formato de volumen) |

## Contexto clínico

El Módulo 1 produce una escena de 3D Slicer guardada como archivo .mrb.
Este archivo contiene:

- El volumen de TC original (en HU)
- El labelmap con segmentación anatómica (TotalSegmentator + refinamiento
  médico)
- Volúmenes ROI (contornos de hígado, tumor, riñones, etc.)
- Transformaciones espaciales que vinculan coordenadas RAS del mundo real
  con coordenadas IJK de voxel

Cargar correctamente esta escena es el paso inicial del Módulo 2 y
condiciona toda la generación posterior.

## Archivo .mrb

El formato .mrb es un ZIP que contiene:

```
escena.mrb/
├── scene.mrml          # Árbol de nodos (volúmenes, modelos, transforms)
├── volumen_tc.nrrd     # TC en formato NRRD (espaciado, origen, datos)
├── labelmap.nrrd       # Segmentación (índices de material por voxel)
├── higado.vtk          # Malla del contorno hepático
├── tumor.vtk           # Malla del contorno tumoral
└── ...                 # Otros VOIs
```

## Carga desde pipeline_mod2.py

La función `load_scene(mrb_path)` en `pipeline_mod2.py` usa la API de
3D Slicer para cargar el archivo:

```python
# Pseudocódigo del flujo real
def load_scene(mrb_path):
    slicer.util.loadScene(mrb_path)
    # El scene MRML ahora contiene todos los nodos
    return {"status": "loaded", "path": mrb_path}
```

El escenario de uso real es desde 3D Slicer via `SlicerDosim`, donde la
escena ya está cargada en memoria. El pipeline asume que Slicer está
activo y la escena es accesible.

## scan_nodes() — Identificar nodos relevantes

Una vez cargada la escena, `scan_nodes()` recorre el árbol MRML y
extrae referencias a los nodos que necesita el generador MCNP.

### Nodos buscados

| Nodo | Tipo MRML | Propósito |
|------|-----------|-----------|
| `volume_node` | `vtkMRMLScalarVolumeNode` | TC original (referencia espacial) |
| `labelmap_node` | `vtkMRMLLabelMapVolumeNode` | Segmentación con materiales |
| `voi_nodes[]` | `vtkMRMLModelNode[]` | Mallas de VOIs |

### Obtención de parámetros espaciales

Desde el `volume_node` se extraen:

```
  origen_ras = volume_node.GetOrigin()        # (x, y, z) en mm
  espaciado  = volume_node.GetSpacing()       # (dx, dy, dz) en mm
  dims       = volume_node.GetImageData().GetDimensions()  # (nx, ny, nz)
```

### Coordenadas IJK a RAS

La matriz de transformación IJK→RAS se obtiene con:

```python
ijk_to_ras = vtk.vtkMatrix4x4()
volume_node.GetIJKToRASMatrix(ijk_to_ras)
```

Esta matriz de 4×4 permite convertir cualquier índice de voxel (i,j,k) a
coordenadas RAS en mm:

$$ \begin{bmatrix} x_{RAS} \\ y_{RAS} \\ z_{RAS} \\ 1 \end{bmatrix} =
\mathbf{M}_{IJK \to RAS} \cdot \begin{bmatrix} i \\ j \\ k \\ 1 \end{bmatrix} $$

### Nomenclatura de ejes

| Sistema | Eje 1 | Eje 2 | Eje 3 |
|---------|-------|-------|-------|
| Slicer (RAS) | R (Right) +izq | A (Anterior) +atrás | S (Superior) +arriba |
| MCNP (LPS) | L—R (Left→Right) | P—A (Post→Ant) | S—I (Sup→Inf) |
| Voxel (IJK) | i (columna) | j (fila) | k (slice) |

La conversión de RAS a LPS requiere:

$$ x_{LPS} = -x_{RAS}, \quad y_{LPS} = -y_{RAS}, \quad z_{LPS} = z_{RAS} $$

Los flags `flip_rows` y `flip_z` del generador MCNP manejan la
reorientación de ejes entre ambos sistemas.

## Validación de prerequisitos

`validate_prereqs()` ejecuta 4 verificaciones antes de proceder:

### Verificación 1: Volumen de TC presente

```python
assert volume_node is not None, "No se encontró volumen de TC"
```

### Verificación 2: Labelmap cargado

```python
assert labelmap_node is not None, "No se encontró labelmap"
```

### Verificación 3: Dimensiones compatibles

```python
tc_dims = volume_node.GetImageData().GetDimensions()
lm_dims = labelmap_node.GetImageData().GetDimensions()
assert tc_dims == lm_dims, (
    f"Dimensiones no coinciden: TC {tc_dims} vs Labelmap {lm_dims}"
)
```

### Verificación 4: VOIs requeridos

```python
# Lista de nombres esperados
voi_names = [n.GetName() for n in voi_nodes]
required = ["Liver", "Tumor", "Kidney_L", "Kidney_R"]
for req in required:
    assert req in voi_names, f"VOI {req} no encontrado"
```

## Ejemplo práctico de extracción de parámetros

Para un volumen típico de TC abdominal:

```python
# Parámetros simulados de un paciente real
origin_ras = (-120.5, -150.3, -245.0)   # mm
spacing    = (0.98, 0.98, 2.50)          # mm/voxel
dims       = (512, 512, 180)             # voxels

# Calcular RPP en LPS (para MCNP)
x_min = -(-120.5) - 0.98 * 512 / 2 = 120.5 - 250.88 = -130.38
x_max = -(-120.5) + 0.98 * 512 / 2 = 120.5 + 250.88 = 371.38
y_min = -(-150.3) - 0.98 * 512 / 2 = 150.3 - 250.88 = -100.58
y_max = -(-150.3) + 0.98 * 512 / 2 = 150.3 + 250.88 = 401.18
z_min = -245.0 - 2.50 * 180 / 2 = -245.0 - 225.0 = -470.0
z_max = -245.0 + 2.50 * 180 / 2 = -245.0 + 225.0 = -20.0

# RPP resultante: -130.38 371.38 -100.58 401.18 -470.0 -20.0
```

## Estructura interna del nodo de volumen

Cada `vtkMRMLScalarVolumeNode` contiene:

```
VolumeNode
├── ImageData (vtkImageData)
│   ├── Dimensions (nx, ny, nz)
│   ├── Spacing (dx, dy, dz)
│   ├── Origin (x0, y0, z0) — en IJK, no RAS
│   └── Scalars (array de valores HU de 16-bit signed)
├── IJKToRASMatrix (vtkMatrix4x4)
│   ├── M_00 .. M_03  (0,0) (0,1) (0,2) (0,3)
│   ├── M_10 .. M_13
│   ├── M_20 .. M_23
│   └── M_30 .. M_33  → [0, 0, 0, 1]
├── RASToIJKMatrix (inversa de la anterior)
├── DisplayNode
│   ├── Window/Level
│   ├── Threshold
│   └── ColorNode
└── StorageNode
    ├── FileName (ruta al .nrrd)
    └── ReadState (idle, inprogress, complete)
```

### La matriz IJK→RAS en detalle

$$ \mathbf{M}_{IJK \to RAS} = \begin{bmatrix}
S_x R_{00} & S_y R_{01} & S_z R_{02} & O_x \\
S_x R_{10} & S_y R_{11} & S_z R_{12} & O_y \\
S_x R_{20} & S_y R_{21} & S_z R_{22} & O_z \\
0 & 0 & 0 & 1
\end{bmatrix} $$

Donde $S_x, S_y, S_z$ son el espaciado, $R$ es la matriz de rotación
(3×3), y $O$ es el origen en RAS del voxel (0,0,0) en IJK.

El labelmap comparte la misma matriz IJK→RAS que la TC, garantizando
que ambos volúmenes estén alineados espacialmente.

## Manejo de errores

| Error | Causa | Acción |
|-------|-------|--------|
| `FileNotFoundError` | Ruta .mrb inválida | Verificar selector de archivos |
| `ValueError` | Nodos incompatibles | Revisar versión de Slicer |
| `AssertionError` | Labelmap sin materiales | Ejecutar Módulo 1 primero |
| `RuntimeError` | Slicer no disponible | Iniciar SlicerDosim |

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| Escena cargada exitosamente | Error en `loadScene()` |
| TC y labelmap tienen mismas dimensiones | `tc_dims ≠ lm_dims` |
| VOIs requeridos presentes | Falta Liver/Tumor/Kidney |
| Matriz IJK→RAS es invertible | Determinante cero |
| Espaciado isotrópico o anisótropo válido | `dx ≤ 0` o `dy ≤ 0` o `dz ≤ 0` |

## Referencias

- 3D Slicer MRML Documentation, mrml.vtk.org
- Fedorov et al., "3D Slicer as an Image Computing Platform for the
  Quantitative Imaging Network", Magnetic Resonance Imaging 30(9), 2012
- .mrb File Format Specification, Slicer Documentation
