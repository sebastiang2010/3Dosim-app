# Pipeline Completo — Módulo 1

> **Resumen**: El pipeline del Módulo 1 transforma imágenes DICOM crudas (CT + PET) en una **labelmap dosimétrica** lista para el Módulo 2 (generación de entrada MCNP). Consta de 16 pasos secuenciales con checkpoint persistente, guardado de escena médica `.mrb` tras cada paso, validación por AI Supervisor, y aprobación médica obligatoria en dos puntos críticos. Cada paso puede reanudarse desde el último checkpoint en caso de interrupción.

**Acrónimos usados en este documento**: TS=TotalSegmentator, HU=Hounsfield Units, PET=Positron Emission Tomography, CT=Computed Tomography, DICOM=Digital Imaging and Communications in Medicine, MCNP=Monte Carlo N-Particle, NIfTI=Neuroimaging Informatics Technology Initiative, NRRD=Nearly Raw Raster Data, MRB=Medical Reality Bundle, NCC=Normalized Cross-Correlation, BED=Biologically Effective Dose, DVH=Dose-Volume Histogram, MIP=Maximum Intensity Projection, IJKToRAS=matriz de transformación de índices de voxel a coordenadas anatómicas (Right-Anterior-Superior)

## Diagrama de Flujo General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             MÓDULO 1                                        │
│              Segmentación + Registro + Fusión + Tumor                        │
│                                                                              │
│  DICOM ──► Calibración ──► Camilla ──► Registro ──► Fusión                  │
│   CT       PET (per-slice)   removal    PET→CT      CT+PET                  │
│    │          │                │          │           │                      │
│    └──────────┴────────────────┴──────────┴───────────┘                      │
│                            │                                                 │
│                            ▼                                                 │
│  Anonimización ──► TotalSegmentator ──► Validación IA ──► Validación Médica  │
│       │                  │                        │              │           │
│       └──────────────────┴────────────────────────┴──────────────┘           │
│                            │                                                 │
│                            ▼                                                 │
│  Creación Tumor ──► Validación Tumor ──► Hígado Sano ──► Body ──► Labelmap   │
│   4 modos               Médica              (hígado -    seg.     NIfTI+NRRD │
│                                             tumor)                           │
│                                                                              │
│                              ↓                                               │
│              Labelmap Dosimétrica (entrada Módulo 2)                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Los 16 Pasos del Pipeline

### Paso 1: `check_slicer` — Verificación de Entorno

**Archivo**: `pipeline_mod1.py` → `_check_slicer()`

Verifica que 3D Slicer esté corriendo, que los módulos necesarios estén disponibles (BRAINSResample, TotalSegmentator), y que los directorios de entrada/salida existan. Si `--reset` está activo, elimina todos los checkpoints previos.

### Paso 2: `load_dicom` — Carga DICOM CT + PET

**Archivo**: `pipeline_mod1.py` → `_load_dicom()`, ver [`carga_dicom.md`](carga_dicom.md)

- Abre base de datos DICOM temporal con `DICOMUtils.openTemporaryDatabase()`
- Indexa directorios `CT/` y `PET/` con `DICOMUtils.importDicom()`
- Carga volúmenes con `DICOMUtils.loadSeriesByUID()`
- Identifica CT vs PET por nombre (contiene "CT", "PET", "PT_" o "NM")
- Renombra nodos a "CT" y "PET" para consistencia entre checkpoints

| Parámetro | CT típico | PET típico |
|-----------|-----------|------------|
| Dimensiones | $512 \times 512 \times N_s$ | $200 \times 200 \times N_s$ |
| Espaciado | $0.976 \times 0.976 \times 3.0$ mm | $4.07 \times 4.07 \times 2.0$ mm |
| Tipo de dato | int16 | float32 |
| Rango HU | -1024 a 3000+ | — |
| Valor | Unidades Hounsfield | Bq/mL (tras calibración) |

### Paso 3: `remove_couch_air` — Eliminar Camilla y Aire

**Archivo**: `couch_remover.py` → `remove_couch_and_air()`, ver [`eliminar_camilla.md`](eliminar_camilla.md)

- Crea **nuevo nodo** `CT_sin_camilla` (NO modifica el CT original)
- Threshold > -200 HU, cierre morfológico 3×3×3, componente conectada más grande por slice
- Recorte inferior (camilla) y lateral (brazos)

### Paso 4: `calibrate_pet_bqml` — Calibración PET a Bq/mL

**Archivo**: `pet_dicom_reader.py` → `read_pet_dicom_activity()`, ver [`calibracion_pet.md`](calibracion_pet.md)

- Lee cada slice DICOM PET con `pydicom`
- Aplica `RescaleSlope` y `RescaleIntercept` por slice (solo si `RescaleType == 'BQML'`)
- Calcula actividad total para el diálogo de fusión
- NO reemplaza el nodo PET de Slicer (Slicer ya aplica Bq/mL correctos)

### Paso 5: `resample_pet_to_ct` — Registro PET → CT

**Archivo**: `pipeline_mod1.py` → `_resample_pet_to_ct()`, ver [`registro_pet.md`](registro_pet.md)

- Re-muestrea PET a la grilla del CT usando **BRAINSResample** con interpolación `NearestNeighbor`
- Clipea valores negativos a 0 (artefactos de interpolación)
- **Conservación de actividad**: escala el PET registrado para que la suma total de actividad coincida con la calibración pre-resample

$$
A_{\text{post}}(i,j,k) = A_{\text{interp}}(i,j,k) \cdot \frac{A_{\text{orig}}}{A_{\text{interp}}}
$$

| Variable | Descripción | Unidades |
|----------|-------------|----------|
| $A_{\text{post}}(i,j,k)$ | Actividad corregida en el voxel $(i,j,k)$ tras registro | Bq |
| $A_{\text{interp}}(i,j,k)$ | Actividad interpolada por BRAINSResample | Bq |
| $A_{\text{orig}}$ | Actividad total pre-resample (desde DICOM raw) | Bq |
| $A_{\text{interp}}$ | Suma de actividad de todo el volumen interpolado | Bq |

### Paso 6: `show_fusion` — Fusión CT+PET y Diálogo

**Archivo**: `fusion_dialog.py` → `show_fusion_info_dialog()`, ver [`fusion_ct_pet.md`](fusion_ct_pet.md)

- Configura layout `ConventionalView` (axial/sagital/coronal + 3D)
- Fondo: CT (o `CT_sin_camilla`) con window/level 400/40 HU
- Overlay: PET como foreground con opacidad 0.35 y colormap rainbow invertido (azul=bajo, rojo=alto)
- Muestra diálogo **modal** con: datos paciente, dimensiones CT/PET, actividad total (Bq, GBq, mCi, Bq/mL), verificaciones de consistencia

### Paso 7: `anonymize` — Anonimización

**Archivo**: `anonymize.py`

- Limpia metadatos DICOM (PatientName, PatientID, etc.)
- Copia imágenes a directorio `.anon/` con prefijo `ANON_`
- Renombra nodos en escena Slicer

### Paso 8: `export_dicom_info` — Exportar Metadatos DICOM

**Archivo**: `pipeline_mod1.py` → `_export_dicom_info()`

- Exporta metadatos relevantes de CT y PET a un archivo CSV en `resultados_test/`

### Paso 9: `segment_phantom` — TotalSegmentator

**Archivo**: `segmentation.py` → `run_segmentation()`

- Ejecuta **TotalSegmentator v2.13.0** con task='total' (104 clases anatómicas)
- Barra de progreso QProgressDialog con mensaje "TotalSegmentator está funcionando..."
- Tiempo estimado: ~20–60 min (dependiendo de CPU/GPU)
- Parámetros: `fast=True`, `force_cpu=True` (configurable en `totalsegmentator_config.jsonc`)
- Usa `TotalSegmentatorLogic.process()` (API directa, NO `slicer.cli.run()`)

### Paso 10: `validate_segmentation_auto` — Verificación IA Automática

**Archivo**: `ai_supervisor.py`

El AI Supervisor (DeepSeek vía OpenRouter) verifica la segmentación:

| Regla | Qué detecta | Acción |
|-------|-------------|--------|
| Método simple (threshold) | Segmentación insuficiente | Warning |
| Pocos segmentos (< 50) | Threshold sin etiquetado de órganos | Warning + recomendación |
| Voxels fuera del cuerpo | Segmentación incluye aire/camilla | Alerta |

### Paso 11: `validate_segmentation` — Validación Médica Obligatoria

**Archivo**: `validation.py`

Diálogo **NO modal** que permite al médico:

- Navegar slices axial/sagital/coronal
- Ocultar PET (slider de opacidad)
- Rotar vista 3D con segmentación
- Examinar cada segmento anatómico
- Hacer clic en **APROBAR** o **RECHAZAR**

El pipeline NO continúa sin aprobación médica explícita.

### Paso 12: `add_tumor` — Creación de Tumor (4 modos)

**Archivo**: `tumor_creator.py` → `create_tumor()`

| Modo | Descripción | Configuración clave |
|------|-------------|---------------------|
| `synthetic` (default) | Esfera de N mm radio en el centroide del hígado | `synthetic_radius_mm`, `liver_segment_name` |
| `load_file` | Carga tumor desde archivo NIfTI | `load_file_path`, `load_segment_name` |
| `manual` | Médico dibuja tumor en Segment Editor de Slicer | `manual_segment_name` |
| `ts_liver_lesions` | TS task='liver_lesions' para detección automática | `ts_liver_lesions_segment_name`, `min_volume_cc` |

Configuración desde `pipeline_config.jsonc`:

```jsonc
"tumor": {
    "mode": "synthetic",
    "synthetic_radius_mm": 10.0,
    "liver_segment_name": "liver",
    "create_healthy_liver": true,
    "ts_liver_lesions_segment_name": "Tumor_TS",
    "ts_liver_lesions_min_volume_cc": 1.0
}
```

### Paso 13: `validate_tumor` — Validación del Tumor

**Archivo**: `tumor_validation.py`

Diálogo contextual según modo de creación. El médico revisa que el tumor sea anatómicamente correcto antes de continuar.

### Paso 14: `create_healthy_liver` — Hígado Sano

**Archivo**: `tumor_creator.py` → `_add_healthy_liver_segment()`

- Crea segmento "hígado_sano" (verde) = hígado - tumor
- Máscara calculada como diferencia booleana de las segmentaciones

### Paso 15: `segment_body` — Segmentación Corporal

**Archivo**: `pipeline_mod1.py` → `_segment_body()`

- Segundo TotalSegmentator con task='body' (config en `totalsegmentator_config_body.jsonc`)
- Crea nodo `Body_Segmentation` separado
- Si falla, emite warning y continúa sin body

### Paso 16: `export_labelmap` — Exportar Labelmap Dosimétrica

**Archivo**: `labelmap_exporter.py`

- Carga `tissue_config.json` desde `SlicerDosim/Resources/Config/`
- Asigna índices phantom a cada segmento (30=Tejido_blando, 50=Pulmón, 80=Hueso, 90=Hígado, 100=Tumor)
- **Resuelve solapamientos**: ganador = índice más alto
- Incorpora body_node como contorno externo si está disponible
- Exporta `3Dosim_labelmap.nii` (NIfTI) y `3Dosim_labelmap.nrrd` (NRRD) en `output_dir/labelmaps/`

## Modos de Ejecución del Pipeline

| Modo | Comando | Comportamiento |
|------|---------|----------------|
| Normal | `python pipeline_mod1.py --config paciente.jsonc` | 16 pasos secuenciales con checkpoint |
| Debug | `python pipeline_mod1.py --config paciente.jsonc --debug` | Pausa tras cada paso |
| Resume | `python pipeline_mod1.py --config paciente.jsonc --resume` | Reanuda desde último checkpoint |
| Reset | `python pipeline_mod1.py --config paciente.jsonc --reset` | Elimina checkpoints, ejecuta desde cero |
| Stop after fusion | `--stop-after-fusion` | Solo pasos 1–6 (test rápido) |
| Stop before segment | `--stop-before-segment` | Detiene antes de TotalSegmentator (segmentación manual) |

## Estructura de Salida

```
output_dir/ (resultados_test/)
├── anon/                          # Imágenes anonimizadas
│   ├── ANON_CT.nrrd
│   └── ANON_PET.nii
├── .checkpoints/
│   └── pipeline_checkpoint.json   # Checkpoint persistente
├── labelmaps/
│   ├── 3Dosim_labelmap.nii        # Labelmap en NIfTI
│   └── 3Dosim_labelmap.nrrd       # Labelmap en NRRD
├── scenes/
│   └── 3Dosim_scene.mrb           # Escena Slicer (sobrescrita)
├── screenshots/                   # PNG por paso (6+ capturas)
├── logs/
│   └── pipeline_mod1.log
├── pipeline_results.json          # Historial completo de ejecuciones
└── fusion_summary.txt             # Resumen de fusión CT+PET
```

## Dependencias entre Pasos

```
 1: check_slicer
       │
 2: load_dicom (CT + PET)
       │
       ├──> 3: remove_couch_air (CT → CT_sin_camilla)
       │
       ├──> 4: calibrate_pet_bqml (PET_DICOM_raw → actividad)
       │         │
       │         ▼
       └──> 5: resample_pet_to_ct (PET → grilla CT + conservación)
                │
                ▼
         6: show_fusion (layout 4-up + diálogo modal)
                │
         7: anonymize + 8: export_dicom_info
                │
         9: segment_phantom (TS total, 104 clases)
                │
         10: validate_segmentation_auto (AI Supervisor)
                │
         11: validate_segmentation (médico, NO modal)
                │
         12: add_tumor (4 modos) ──► 13: validate_tumor
                                           │
                                           ▼
                                    14: create_healthy_liver (hígado - tumor)
                                           │
                                    15: segment_body (TS body)
                                           │
                                    16: export_labelmap (NIfTI + NRRD)
```

## Integración con Módulo 2

La labelmap generada en el paso 16 se pasa al Módulo 2 (`pipeline_mod2.py`) para:

1. Asignar materiales MCNP según `tissue_config.json` (53 materiales ICRP-110)
2. Generar archivo de entrada MCNP con geometría voxelizada (LIKE n BUT, RPP, lattice fill)
3. Configurar fuente Y-90 (SDEF) con actividad del PET
4. Configurar detectores (FMESH4, F6)
5. Ejecutar simulación MCNP (o kernel convolution vía FFT como alternativa rápida)
6. Post-procesar dosis, DVH, isodosis, BED, EUD, NTCP, TCP (Módulo 3)

## Verificaciones y Control de Calidad

### Pre-verificaciones Inmediatas (AI Supervisor)

Se ejecutan después de cada paso, sin consultar a la IA (reglas duras):

| Regla | Detecta | Acción |
|-------|---------|--------|
| `num_segments <= 2` | Threshold sin etiquetado de órganos | Warning naranja |
| `body_voxels / total_voxels < 0.3` | Segmentación incluye aire/camilla | Alerta roja |
| `total_bq == 0` | Calibración PET fallida | Error, no continúa |
| `pet_activity_range` fuera de [0.1, 50] GBq | Actividad inusualmente baja/alta | Warning |
| `NCC < 0.6` | Mala alineación PET→CT | Alerta |

### Verificaciones Manuales (Médico)

| Paso | Verificación | Criterio |
|------|-------------|----------|
| validate_segmentation | APROBAR explícito | Botón clickeado |
| validate_tumor | Tumor visible y correcto | Botón clickeado |
| fusion dialog | Unidades BQML, actividad en rango | 0.1–50 GBq |
| fusion dialog | Dimensiones CT/PET similares | Diferencia < 10 pixeles |
| fusion dialog | Voxeles activos | > 100 voxeles con actividad > 0 |
