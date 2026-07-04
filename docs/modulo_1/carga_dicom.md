# Carga DICOM CT+PET

> **El CT y el PET vienen en archivos separados, con geometrías distintas y metadatos específicos.** Este paso los indexa en una base de datos temporal de Slicer, construye los volúmenes 3D a partir de los slices individuales, y renombra los nodos con nombres canónicos para que el resto del pipeline pueda encontrarlos.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| CT | Computed Tomography |
| DICOM | Digital Imaging and Communications in Medicine |
| DB | Database (base de datos) |
| FOV | Field of View |
| HU | Hounsfield Unit |
| PET | Positron Emission Tomography |
| UID | Unique Identifier |
| MRB | Medical Reality Bundle (escena Slicer) |

---

## 1. El Problema Geométrico

Un estudio DICOM típico para radioembolización con $^{90}$Y consta de:

- **CT**: $512 \times 512 \times N_s$ voxels con espaciado $\approx 0.976 \times 0.976 \times 3.0$ mm. Valores en Hounsfield Units (HU), tipo int16. Rango típico: $-1024$ HU (aire) a $+3000$ HU (hueso denso).
- **PET**: $200 \times 200 \times N_s$ voxels con espaciado $\approx 4.07 \times 4.07 \times 2.0$ mm. Valores raw DICOM (pre-calibración), tipo float32.

La diferencia de resolución es de aproximadamente $4\times$ en el plano axial. El pipeline debe manejar ambas geometrías y eventualmente unificarlas (paso 4: registro).

---

## 2. Algoritmo de Carga

### Paso 1: Verificación de directorios

Se verifica que existan los directorios `CT/` y `PET/` dentro del directorio de datos del paciente. Si alguno falta, el pipeline se detiene con error.

### Paso 2: Apertura de base de datos temporal

```python
original_db_dir = DICOMUtils.openTemporaryDatabase()
```

Se abre una base de datos DICOM temporal (no la permanente de Slicer) para no contaminar el índice global del usuario.

### Paso 3: Indexación de archivos

```python
DICOMUtils.importDicom(ct_dir)   # indexa todos los .dcm del CT
DICOMUtils.importDicom(pet_dir)  # indexa todos los .dcm del PET
```

Esta función parsea cada archivo `.dcm`, extrae metadados (PatientID, StudyDate, Modality, SeriesUID, SOPInstanceUID, etc.) y los almacena en la base temporal.

### Paso 4: Carga de volúmenes

```python
series_uids = DICOMUtils.allSeriesUIDsInDatabase()
loaded_node_ids = DICOMUtils.loadSeriesByUID(series_uids)
```

Slicer agrupa los slices individuales por SeriesUID y construye automáticamente un volumen 3D con la geometría correcta (espaciado, origen, orientación).

### Paso 5: Identificación de modalidades

```python
for node_id in loaded_node_ids:
    node = slicer.mrmlScene.GetNodeByID(node_id)
    name = node.GetName().upper()
    if "CT" in name:
        ct_node = node
    elif "PET" in name or "PT" in name or "NM" in name:
        pet_node = node
```

La identificación se hace por nombre del nodo (no por modalidad DICOM). Si no se encuentra PET, se asume que el segundo nodo cargado es el PET.

### Paso 6: Renombrado canónico

Los nodos se renombran a `"CT"` y `"PET"` para que todos los pasos posteriores puedan referenciarlos por nombre, independientemente del nombre original del estudio.

---

## 3. Parámetros Típicos de las Imágenes

| Parámetro | CT | PET |
|-----------|:--:|:---:|
| Modalidad DICOM | CT | PT |
| Dimensiones ($N_x \times N_y \times N_z$) | $512 \times 512 \times N_s$ | $200 \times 200 \times N_s$ |
| Espaciado ($s_x, s_y, s_z$) [mm] | $0.976 \times 0.976 \times 3.0$ | $4.07 \times 4.07 \times 2.0$ |
| Tipo de dato | int16 (enteros con signo) | float32 |
| Rango de valores | $-1024$ a $+3000$ HU | $0$ a $10^5$ (raw) |
| Bits por pixel | 16 | 16 o 32 |
| Campo de visión (FOV) | ~500 mm | ~814 mm |

**Notación:**

| Variable | Descripción | Unidades |
|----------|-------------|:--------:|
| $N_s$ | Número de slices (cortes axiales) | — |
| $N_x, N_y, N_z$ | Dimensiones del volumen 3D en voxels | vox |
| $s_x, s_y, s_z$ | Espaciado entre voxels | mm |
| $I_{CT}(x,y,z)$ | Valor del CT en la coordenada voxel $(x,y,z)$ | HU |
| $I_{PET}(x,y,z)$ | Valor raw del PET en la coordenada $(x,y,z)$ | raw |

---

## 4. Formato DICOM — Estructura Interna

Cada archivo DICOM representa un slice individual y contiene:

```
Archivo .dcm
├── Metadatos (tags)
│   ├── (0010,0010) PatientName
│   ├── (0010,0020) PatientID
│   ├── (0008,0020) StudyDate
│   ├── (0008,0060) Modality        ← "CT" o "PT"
│   ├── (0020,000E) SeriesUID       ← agrupa slices del mismo estudio
│   ├── (0008,0018) SOPInstanceUID  ← único por slice
│   ├── (0028,0030) PixelSpacing    ← (s_x, s_y) [mm]
│   ├── (0018,0050) SliceThickness  ← s_z [mm]
│   ├── (0020,0032) ImagePositionPatient  ← origen del slice [mm]
│   ├── (0020,0037) ImageOrientationPatient  ← cosenos directores
│   ├── (0028,1052) RescaleSlope     ← m_k (pendiente de calibración)
│   ├── (0028,1053) RescaleIntercept ← b_k (intercepto)
│   └── (0028,1054) RescaleType      ← "BQML" para PET calibrado
└── Datos de imagen
    └── pixel_array (matriz 2D: N_x × N_y)
```

---

## 5. Post-carga

Inmediatamente después de la carga exitosa:

1. Se llama a `setup_medical_views()` para mostrar CT y PET en layout 4-up
2. Se guarda la escena como `3Dosim_scene.mrb` en el directorio de escenas
3. Se guarda checkpoint con metadata (`ct_file`, `pet_file`, `ct_dimensions`, `pet_dimensions`)
4. El AI Supervisor verifica que ambas modalidades estén presentes

---

## 6. Diagrama de Flujo

```
┌─────────────┐    ┌─────────────┐
│ CT/ directorio│   │ PET/ directorio│
│ (archivos .dcm)│   │ (archivos .dcm)│
└──────┬──────┘    └──────┬──────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────┐
│ DICOMUtils.openTemporaryDatabase │
│ (base de datos temporal)         │
└──────────────┬───────────────────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────┐
│ DICOMUtils.importDicom(dir)      │
│ (indexa metadatos + geometría)   │
└──────────────┬───────────────────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────┐
│ DICOMUtils.loadSeriesByUID(uids) │
│ (construye volumen 3D)           │
└──────────────┬───────────────────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────┐
│ Identificar por nombre:          │
│ "CT" → ct_node                   │
│ "PET" / "PT" / "NM" → pet_node   │
└──────────────┬───────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
┌──────────────┐ ┌──────────────┐
│ CT node      │ │ PET node     │
│ 512×512×N    │ │ 200×200×N    │
│ 0.976 mm     │ │ 4.07 mm      │
│ HU (int16)   │ │ raw (float32)│
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
  setup_medical_views()  │
  guardar escena .mrb    │
  checkpoint.save()     │
       │                │
       ▼                ▼
    (siguiente paso: calibración PET)
```

---

## 7. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo | Acción |
|-------------|:------------------:|:------:|
| CT detectado | No hay nodo con "CT" en nombre | Error → detener pipeline |
| PET detectado | No hay nodo con "PET"/"PT"/"NM" | Error → detener pipeline |
| Dimensiones CT | $N_x \neq 512$ o $N_y \neq 512$ | Warning (puede ser CT no abdominal) |
| Dimensiones PET | $N_x < 100$ o $N_y < 100$ | Warning (poco común pero posible) |
| Escena guardada | Error al escribir .mrb | Warning (continúa sin escena) |

---

## 8. Notas Técnicas

- La base de datos temporal se cierra automáticamente al terminar el pipeline, pero los nodos cargados persisten en la escena de Slicer.
- Si hay múltiples series en el directorio CT, se carga la primera que contenga "CT" en el nombre.
- Si el PET no se identifica por nombre, se asigna al segundo nodo cargado (primer nodo = CT, segundo = PET).
- Tras la carga, se recomienda verificar visualmente con `setup_medical_views()` que las imágenes sean correctas antes de continuar.
