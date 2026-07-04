# Visión General del Módulo 1

> **Arquitectura, stack tecnológico e índices del phantom 3Dosim.** Este documento describe la estructura general del módulo de preparación: qué tecnologías lo componen, cómo se relacionan sus partes, y cuál es el sistema de identificación de tejidos que conecta la segmentación anatómica con la simulación Monte Carlo.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| 3Dosim | Pipeline de dosimetría interna 3D para radioembolización hepática |
| CT | Computed Tomography |
| DICOM | Digital Imaging and Communications in Medicine |
| ICRP-110 | Publicación 110 de la Comisión Internacional de Protección Radiológica |
| ICRU-44 | Reporte 44 de la Comisión Internacional de Unidades y Medidas Radiológicas |
| MCNP | Monte Carlo N-Particle |
| NIfTI | Neuroimaging Informatics Technology Initiative |
| NRRD | Nearly Raw Raster Data |
| PET | Positron Emission Tomography |
| TS | TotalSegmentator |

---

## 1. Objetivo Arquitectónico

El Módulo 1 es la **capa de acondicionamiento y segmentación** del pipeline 3Dosim. Su función es transformar imágenes médicas crudas (CT + PET) en una representación volumétrica discreta donde cada voxel tenga asignado un identificador numérico de tejido. Esta representación — la labelmap dosimétrica — es el único requisito de entrada del Módulo 2 (generación de geometría y materiales MCNP).

La arquitectura sigue un diseño **orientado a pasos** (step-oriented): cada paso del pipeline es independiente, tiene una entrada y salida bien definidas, y puede ejecutarse, verificarse y reiniciarse de forma individual gracias al sistema de checkpoints.

---

## 2. Stack Tecnológico

| Capa | Tecnología | Versión | Propósito |
|------|-----------|:-------:|-----------|
| Plataforma de visualización | 3D Slicer | 5.8.1 | GUI médica, renderización, validación |
| Lenguaje de orquestación | Python | 3.9.10 | Lógica del pipeline, integración Slicer |
| Segmentación por IA | TotalSegmentator | 2.13.0 | Segmentación automática de 104 clases anatómicas |
| Backend de segmentación | nnU-Net | (incluido en TS) | Red convolucional para segmentación 3D |
| Registro de imágenes | Elastix (extensión Slicer) | — | Registro rígido/afín/BSpline PET→CT |
| Interpolación alternativa | NumPy / SciPy | — | `map_coordinates` con conservación de actividad |
| Interfaz de usuario | Qt (PyQt) | (incluido en Slicer) | Diálogos de validación médica, barras de progreso |
| Configuración | JSONC | — | Archivos de configuración con comentarios |
| Persistencia | JSON | — | Checkpoints, resultados, metadata |
| Tabla de tejidos | `tissue_config.json` | — | 53+ materiales ICRP-110 con composiciones MCNP |

---

## 3. Sistema de Índices del Phantom 3Dosim

Cada tejido en el phantom 3Dosim tiene un **índice numérico único** que sirve como identificador en todos los módulos del pipeline. Este índice es el valor que tendrá cada voxel en la labelmap final.

### 3.1 Índices Principales

| Índice | Tejido | Densidad [g/cm³] | Rango HU | Material MCNP |
|:------:|--------|:----------------:|:--------:|:-------------:|
| 1 | Aire (exterior) | 0.001205 | -1024 a -900 | M1 |
| 30 | Tejido blando (genérico) | 1.06 | -200 a 150 | M2 |
| 50 | Pulmón | 0.382 | -900 a -200 | M3 |
| 80 | Hueso (cortical) | 1.92 | 150 a 2000 | M4 |
| 90 | Hígado | 1.05 | 40 a 150 | M5 |
| 100 | Tumor | — | — | M6 |
| 101-153 | ICRP-110 (53 materiales) | varios | varios | M7-M59 |
| 200 | Peritumoral | — | — | M60 |

### 3.2 Materiales ICRP-110 (índices 101-153)

Los índices 101-153 corresponden a los 53 tejidos de referencia del phantom ICRP-110. Cada uno tiene:

- **Densidad** en g/cm³
- **Composición elemental** para MCNP (fracciones atómicas de H, C, N, O, Na, P, S, Cl, K, etc.)
- **Rango de HU** para verificación cruzada con el CT
- **Color RGBA** para visualización en Slicer

Ejemplo de composición MCNP para el hígado (índice 90, material M5):

| Elemento | Z (MCNP) | Fracción atómica |
|:--------:|:--------:|:----------------:|
| Hidrógeno (H) | 1000 | 0.105 |
| Carbono (C) | 6000 | 0.143 |
| Nitrógeno (N) | 7000 | 0.034 |
| Oxígeno (O) | 8000 | 0.708 |
| Sodio (Na) | 11000 | 0.003 |
| Fósforo (P) | 15000 | 0.003 |
| Azufre (S) | 16000 | 0.003 |
| Cloro (Cl) | 17000 | 0.002 |
| Potasio (K) | 19000 | 0.002 |

Notación MCNP: `1000` = $^{1}$H, `6000` = $^{12}$C, etc.

---

## 4. Relación con los Otros Módulos

```
Módulo 1 (PREPARACIÓN)        Módulo 2 (MCNP)              Módulo 3 (DOSIMETRÍA)
─────────────────────         ──────────────               ─────────────────────
                              ┌─────────────────┐
CT + PET ───► Módulo 1 ───►  │ Labelmap .nii    │──► Módulo 2 ──► Módulo 3 ──► Reporte PDF
   ▲                         │ Actividad .nii   │       ▲              ▲
   │                         │ PET registrado   │       │              │
Paciente                     └─────────────────┘       MCNP input     Dosis, DVH,
(estudio DICOM)                                        (materiales,   isodosis, BED,
                                                       fuente,        NTCP, TCP
                                                       geometría,
                                                       tallies)
```

---

## 5. Archivos de Configuración Clave

| Archivo | Ruta relativa | Contenido principal |
|---------|---------------|---------------------|
| `pipeline_config.jsonc` | `PipelineOrchestrator/` | `scene_output_dir: "C:/MAT/3Dosim/ai-pipe/imagenes"`, `tumor.mode`, `ai_supervisor`, `patient_weight_kg` |
| `totalsegmentator_config.jsonc` | `PipelineOrchestrator/` | `task: "total"`, `fast: true`, `force_cpu: true`, `subset: null` |
| `totalsegmentator_config_body.jsonc` | `PipelineOrchestrator/` | `task: "body"`, `fast: true`, `force_cpu: true` |
| `tissue_config.json` | `SlicerDosim/Resources/Config/` | `ts_label_to_phantom` (mapeo TS→índice), `tissues` (53+ materiales) |

---

## 6. Modos de Ejecución

| Modo | Flag | Pasos ejecutados | Cuándo usarlo |
|------|------|:----------------:|---------------|
| Completo | (ninguno) | 12 | Ejecución estándar: todo el pipeline |
| Hasta fusión | `--stop-after-fusion` | 5 | Test rápido sin segmentación |
| Antes de segmentar | `--stop-before-segment` | 6 | El médico segmenta manualmente |
| Reset | `--reset` | 12 (desde cero) | Elimina checkpoints previos y reinicia |

---

## 7. Control de Calidad Global

El pipeline integra dos capas de verificación:

1. **AI Supervisor** (automático, post-paso): verifica métricas cuantitativas como NCC, volumen eliminado, número de segmentos, volumen del tumor. Si detecta anomalías, emite warning (no bloquea) o error (bloquea).

2. **Validación Médica** (manual, obligatoria): dos puntos de control donde un médico debe aprobar explícitamente la segmentación y el tumor. No existe "auto-approve".

Ambas capas son complementarias: el AI Supervisor detecta fallos numéricos evidentes; la validación médica captura errores anatómicos que ningún algoritmo puede detectar.
