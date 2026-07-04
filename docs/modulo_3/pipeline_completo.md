# Pipeline Completo — Módulo 3: Dosimetría

> **De la escena segmentada al reporte clínico.** El pipeline del Módulo 3 transforma la escena generada por el Módulo 1 (con CT, PET, labelmap y ROIs) en un mapa de dosis 3D en Gray, histogramas dosis-volumen, índices radiobiológicos y un reporte PDF listo para la práctica clínica. Soporta dos rutas de cálculo — MCTAL (Monte Carlo) y Kernel (convolución FFT) — con checkpoint persistente, guardado de escena tras cada paso, y verificación por AI Supervisor.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MCTAL | Archivo de salida de MCNP con tallies |
| MCNP | Monte Carlo N-Particle (LANL) |
| MIRD | Medical Internal Radiation Dose |
| DVH | Dose-Volume Histogram |
| BED | Biologically Effective Dose |
| EUD | Equivalent Uniform Dose |
| EQD2 | Equivalent Dose in 2 Gy fractions |
| FFT | Fast Fourier Transform |
| TMESH | Tally MESH (grilla de dosis en MCNP) |
| ROI | Region of Interest |
| MRB | Medical Reality Bundle (escena Slicer) |
| PDF | Portable Document Format |
| NRRD | Nearly Raw Raster Data |

---

## 1. Integración Mod1 → Mod3

```
Módulo 1                          Módulo 3
(PREPARACIÓN)                     (DOSIMETRÍA)
──────────────                    ──────────────

CT + PET DICOM
      │
      ▼
Segmentación (TS)
      │
      ▼
Labelmap dosimétrica ────────►   Escena .mrb
(NIfTI + NRRD,                    ├── CT (referencia espacial)
 índices phantom)                  ├── PET (actividad Bq/mL)
      │                           ├── Labelmap (90=hígado, 100=tumor...)
      ▼                           ├── ROIs (hígado, tumor, peritumoral)
Módulo 2 (MCNP)                    └── Transforms (IJK→RAS)
      │
      ▼                                     │
Archivo MCTAL ──────────────────►     Parse MCTAL
(paciente.o)                              │
                                          ▼
                                    Mapa dosis 3D (Gy)
                                          │
                               ┌──────────┼──────────┐
                               ▼          ▼          ▼
                             DVH       BED/EUD     MIRD
                                                   (verificación)
                               │          │          │
                               └──────────┴──────────┘
                                          │
                                          ▼
                                    Reporte PDF
                                    Escena final .mrb
```

---

## 2. Diagrama de Flujo General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MÓDULO 3 — DOSIMETRÍA                              │
│                                                                              │
│   Escena .mrb ──► load_scene ──► read_pet_activity                          │
│   (Mod1)              │                │                                     │
│                       ▼                ▼                                     │
│              ┌────────────────────────────────────┐                          │
│              │     DUAL PATH ENGINE                 │                        │
│              │                                      │                        │
│              │  ┌─────────────────┐  ┌──────────┐  │                        │
│              │  │ Ruta MCTAL      │  │ Ruta     │  │                        │
│              │  │                 │  │ Kernel   │  │                        │
│              │  │ parse_mctal()   │  │           │  │                        │
│              │  │ convert_to_gy() │  │ fft_dose()│  │                        │
│              │  │ × ρ, τ, A      │  │ GBq+norm  │  │                        │
│              │  └────────┬────────┘  └─────┬─────┘  │                        │
│              └─────────────┼────────────────┼────────┘                        │
│                            ▼                ▼                                 │
│                      ┌──────────────────────────┐                            │
│                      │   Mapa de dosis 3D (Gy)   │                            │
│                      └────────────┬─────────────┘                            │
│                                   │                                           │
│              ┌────────────────────┼────────────────────┐                      │
│              ▼                    ▼                    ▼                      │
│          compute_dvh()    compute_radiobiology()  mird_partition()            │
│              │                    │                    │                      │
│              └────────────────────┼────────────────────┘                      │
│                                   ▼                                           │
│                        ┌───────────────────┐                                 │
│                        │  Export reporte   │                                 │
│                        │  PDF + escena     │                                 │
│                        └───────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Los 10 Pasos del Pipeline

| # | Paso | Archivo | Entrada | Salida |
|:-:|------|---------|---------|--------|
| 1 | `load_scene` | `run_dosimetry_from_scene.py` | `.mrb` | Nodos CT+PET+Labelmap+ROIs |
| 2 | `read_pet_activity` | `pet_dicom_reader.py` | DICOM PET o `--activity` | Actividad total (Bq, GBq) |
| 3 | `parse_mctal` (opt) | `mctal_parser.py` | `paciente.o` | `dose_raw` [MeV/cm³] |
| 4 | `compute_dose_mctal` | `dosimetry.py` | `dose_raw` + ρ + τ + A | `dose_gy` (ruta MCTAL) |
| 4b | `compute_dose_kernel` | `dose_kernel.py` + `fft_dose.py` | `kernel.mat` + PET [GBq] | `dose_gy` (ruta Kernel) |
| 5 | `compute_dvh` | `dvh_analysis.py` | `dose_gy` + máscaras ROI | DVH (200 pts), D98-D2, V30-V70 |
| 6 | `compute_radiobiology` | `radiobiology.py` | `dose_gy` + α/β | BED, EUD, EQD2 |
| 7 | `mird_partition` | `mird_partition.py` | Actividad + T/N + volúmenes | D_liver, D_tumor (MIRD) |
| 8 | `visualize_slicer` | `isodose_contours.py` | `dose_gy` | Nodos isodosis + DVH en Slicer |
| 9 | `export_report` | `report_pdf.py` | Tablas + gráficos + capturas | `3Dosim_reporte.pdf` |
| 10 | `save_scene` | `run_dosimetry_from_scene.py` | Escena con nodos dosis | `3Dosim_dosis_final.mrb` |

---

## 4. Pasos Detallados

### Paso 1: `load_scene` — Cargar escena

Carga el archivo `.mrb` generado por el Módulo 1 desde `resultados_test/scenes/3Dosim_scene.mrb`.

Verifica que existan:
- Volumen CT (referencia espacial)
- Volumen PET (actividad en Bq/mL)
- Labelmap (índices phantom: 90, 100, 200)
- Nodos ROI (hígado, tumor, peritumoral)

```python
def load_scene(self, mrb_path: str):
    slicer.util.loadScene(mrb_path)
    self.ct_node = slicer.util.getNode('CT')
    self.pet_node = slicer.util.getNode('PET')
    self.labelmap_node = slicer.util.getNode('3Dosim_labelmap')
    # Verificar dimensiones consistentes
```

### Paso 2: `read_pet_activity` — Leer actividad PET

Lee DICOM PET raw replicando MATLAB `f_Rescale_Bq.m`. Ver [`lectura_actividad.md`](lectura_actividad.md).

Si no hay PET disponible, usa `--activity <GBq>` con distribución uniforme sobre las ROIs.

**Checkpoint**: Actividad total en GBq guardada para verificación cruzada con MIRD.

### Paso 3: `parse_mctal` — Parsear MCTAL (ruta Monte Carlo)

Busca el archivo MCTAL (`resultados_test/mcnp/paciente.o`), extrae tally 1, aplica reshape Fortran y filtros. Ver [`parse_mctal.md`](parse_mctal.md).

**Checkpoint**: `dose_raw` (MeV/cm³), error medio, voxeles filtrados.

### Paso 4: `compute_dose` — Conversión a Gy

**Ruta MCTAL:**

$$D_{\text{Gy}} = \frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} \times \tau \times A \times 1000$$

**Ruta Kernel:**

$$D_{\text{Gy}} = \text{FFT}^{-1}\big[\text{FFT}(A_{\text{GBq}}) \cdot \text{FFT}(K_{\text{norm}})\big] \times \text{mask}$$

Ver [`conversion_dosis.md`](conversion_dosis.md).

**Checkpoint**: `dose_gy` (NRRD), dosis media por ROI.

### Paso 5: `compute_dvh` — Histograma Dosis-Volumen

Calcula DVH acumulativo para 4 ROIs con 200 puntos y escala Y logarítmica. Extrae D98, D95, D70, D50, D5, D2, V30, V70. Ver [`dvh.md`](dvh.md).

**Checkpoint**: Tabla DVH (CSV), métricas por ROI.

### Paso 6: `compute_radiobiology` — Índices biológicos

Calcula BED (LQ con tasa de dosis), EUD (Niemierko), EQD2. Ver [`radiobiologia.md`](radiobiologia.md).

**Checkpoint**: Tabla de BED, EUD, EQD2 por ROI.

### Paso 7: `mird_partition` — Modelo MIRD

Verificación rápida vs. mapa 3D. Calcula dosis media por partición usando T/N de PET. Ver [`mird.md`](mird.md).

**Checkpoint**: Diferencia MIRD vs. 3D < 20%.

### Paso 8: `visualize_slicer` — Visualización 3D

Crea en Slicer:
- Nodo de dosis con overlay rainbow invertido
- 10 niveles de isodosis (10-100%, jet colormap)
- DVH interactivo en módulo Plots

Ver [`visualizacion_slicer.md`](visualizacion_slicer.md).

### Paso 9: `export_report` — Reporte PDF

Genera `3Dosim_reporte.pdf` con:
- Parámetros del paciente (actividad, isótopo)
- Mapa de dosis 3D (captura)
- Tabla DVH por ROI
- Curvas DVH
- Índices radiobiológicos
- Resultados MIRD
- Fecha y firma médica

### Paso 10: `save_scene` — Guardar escena final

Guarda `resultados_test/scenes/3Dosim_dosis_final.mrb` con todos los nodos.

---

## 5. Archivos de Entrada y Salida

### 5.1 Entradas

| Archivo | Ruta | Origen |
|---------|------|--------|
| Escena .mrb | `resultados_test/scenes/3Dosim_scene.mrb` | Módulo 1 |
| MCTAL (.o) | `resultados_test/mcnp/paciente.o` | MCNP (Módulo 2) |
| kernel.mat | `kernel/kernel.mat` | Precalculado |
| PET DICOM | `C:/MAT/3Dosim/ai-pipe/imagenes/PET/` | Estudio original |
| Config JSONC | `PipelineOrchestrator/pipeline_config.jsonc` | Config global |
| Tissue config | `SlicerDosim/Resources/Config/tissue_config.json` | Densidades |

### 5.2 Salidas

| Archivo | Ruta | Contenido |
|---------|------|-----------|
| `dose_gy.nrrd` | `resultados_test/dose/` | Mapa de dosis 3D en Gy |
| `dvh.csv` | `resultados_test/dvh/` | Tabla DVH por ROI |
| `radiobiology.csv` | `resultados_test/radiobiology/` | BED, EUD, EQD2 |
| `3Dosim_reporte.pdf` | `resultados_test/reports/` | Reporte clínico completo |
| `3Dosim_dosis_final.mrb` | `resultados_test/scenes/` | Escena con todos los nodos |
| `pipeline_results.json` | `resultados_test/` | Historial de ejecuciones |

### 5.3 Checkpoints

| Checkpoint | Datos guardados |
|-----------|----------------|
| `scene_loaded` | Nodos de escena, dimensiones |
| `activity_read` | Actividad GBq, estadísticas PET |
| `mctal_parsed` | `dose_raw`, error, filtros |
| `dose_computed` | `dose_gy`, dosis media por ROI |
| `dvh_computed` | Tabla DVH, métricas |
| `radiobiology_computed` | BED, EUD, EQD2 |
| `mird_computed` | D_liver, D_tumor, diferencia |
| `scene_saved` | Ruta de escena final |

---

## 6. Modos de Ejecución

| Modo | Flag | Pasos | Cuándo usarlo |
|------|------|:-----:|---------------|
| Completo (MCTAL) | (ninguno) | 10 | Validación final con Monte Carlo |
| Solo Kernel | `--kernel` | 9 (sin paso 3) | Planificación rápida |
| Solo DVH | `--dvh-only` | 1, 5 | Si ya existe `dose_gy.nrrd` |
| Reporte | `--report-only` | 9 | Regenerar PDF sin recalcular |
| Reset | `--reset` | 10 (desde cero) | Elimina checkpoints previos |

---

## 7. Integración con SlicerDosimMod3

El módulo **SlicerDosimMod3** dentro de 3D Slicer ejecuta el pipeline automáticamente:

1. Al abrir el módulo: auto-detecta escena `.mrb` en `resultados_test/`
2. Auto-ejecuta: carga escena → encuentra CT/PET/labelmap → kernel FFT → dosis → DVH → isodosis → guarda escena
3. Botones individuales: Cargar escena, Calcular dosis, DVH, Isodosis, MIRD, Guardar escena, Exportar PDF
4. Log en tiempo real en el panel de texto del UI

**Configuración del módulo:**
```
Slicer → Edit → Settings → Modules → Additional paths:
C:\programas\3Dosim\3Dosim_v4\slicer_modules\SlicerDosim\Modules\Scripted
```

---

## 8. Control de Calidad (AI Supervisor)

| Paso | Verificación | Condición de fallo |
|------|-------------|-------------------|
| 1. Cargar escena | Nodos CT, PET, Labelmap presentes | Falta algún nodo |
| 2. Actividad PET | Actividad > 0 Bq | Actividad ≤ 0 |
| 3. Parse MCTAL | Error medio < 0.5 | Error ≥ 0.5 |
| 4. Dosis Gy | Dosis ≥ 0 en todos los voxeles | Dosis negativa > 1% |
| 5. DVH | Monótono decreciente | Pendiente positiva |
| 6. Radiobiología | BED ≥ D física | BED < D |
| 7. MIRD | Diferencia 3D vs MIRD < 20% | Diferencia ≥ 20% |
| 8. Visualización | Nodos isodosis creados | Isodosis no generadas |
| 9. Reporte PDF | Archivo > 10 KB | No existe o vacío |
| 10. Escena final | Archivo .mrb creado | No se guardó |

---

## 9. Referencias

- `run_dosimetry_from_scene.py` — Orquestador del pipeline
- `pet_dicom_reader.py` — Lectura de actividad PET
- `mctal_parser.py` — Parser de archivos MCTAL
- `dosimetry.py` — Conversión MeV/cm³ → Gy
- `dose_kernel.py` / `fft_dose.py` — Ruta Kernel FFT
- `dvh_analysis.py` — Cálculo de DVH
- `radiobiology.py` — BED, EUD, EQD2
- `mird_partition.py` — Modelo MIRD de partición
- `isodose_contours.py` — Generación de isodosis
- `report_pdf.py` — Generación de reporte PDF
- `SlicerDosimMod3.py` — Módulo Slicer para Mod3
- `pipeline_mod3.py` — (futuro) Pipeline orquestador CLI
