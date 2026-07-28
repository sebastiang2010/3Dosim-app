# Visión General — Módulo 3: Dosimetría Interna 3D

> **De la simulación Monte Carlo al reporte clínico.** La simulación MCNP genera archivos MCTAL con energía depositada por partícula fuente en cada voxel. Sin embargo, estos valores crudos no son directamente utilizables para la práctica clínica: deben convertirse a dosis absorbida en Gray (Gy), combinarse con la actividad del paciente medida por PET, y analizarse mediante histogramas dosis-volumen y modelos radiobiológicos.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MCNP | Monte Carlo N-Particle (LANL) |
| MCTAL | Archivo de salida binario/ASCII de MCNP con resultados de tallies |
| MIRD | Medical Internal Radiation Dose (modelo de partición) |
| DVH | Dose-Volume Histogram |
| BED | Biologically Effective Dose |
| EUD | Equivalent Uniform Dose |
| EQD2 | Equivalent Dose in 2 Gy fractions |
| NTCP | Normal Tissue Complication Probability |
| TCP | Tumor Control Probability |
| FFT | Fast Fourier Transform (convolución de kernel) |
| TMESH | Tally MESH (grilla de dosis en MCNP) |
| Y-90 | Itrio-90 (isótopo beta, terapia hepática) |
| HU | Hounsfield Units |
| ROI | Region of Interest |
| NRRD | Nearly Raw Raster Data |
| MRB | Medical Reality Bundle (escena de 3D Slicer) |

---

## 1. Contexto Clínico

En radioembolización hepática con microesferas de $$^{90}$$Y, la dosis absorbida en cada voxel depende de:

1. La **actividad** administrada y su distribución espacial (medida por PET post-infusión)
2. La **densidad** de cada tejido (derivada de la TC, segmentada en Módulo 1)
3. El **transporte** de partículas beta (simulado por MCNP en Módulo 2)

El Módulo 3 toma los resultados de la simulación Monte Carlo (archivo MCTAL) o la convolución de kernel (archivo `kernel.mat`) y produce:

- **Mapa de dosis 3D** en Gray (Gy)
- **Histogramas dosis-volumen** (DVH) acumulativos por ROI
- **Índices radiobiológicos:** BED, EUD, EQD2
- **Reporte clínico** en PDF

---

## 2. Pipeline de 10 Pasos

El pipeline del Módulo 3 se orquesta secuencialmente:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          MÓDULO 3 — DOSIMETRÍA                           │
│                                                                          │
│   Escena .mrb ───► Cargar ───► Leer PET ───► Parsear MCTAL (o kernel)   │
│      (Mod1)              escena    actividad           │                  │
│                         + labelmap          ┌──────────┘                  │
│                                              ▼                           │
│                           ┌──────────────────┴──────────────────┐        │
│                           │ Ruta MCTAL:    │   Ruta Kernel:     │        │
│                           │                │                    │        │
│                           │ Parse MCTAL    │ Cargar kernel.mat  │        │
│                           │ Extraer tally  │ FFT convolución    │        │
│                           │ MeV/cm³→Gy     │ (sin τ×A)          │        │
│                           └─────────────────┴───────────────────┘        │
│                                              │                           │
│                                              ▼                           │
│                        ┌──────────────────────────────────┐              │
│                        │    Mapa de dosis 3D (Gy)         │              │
│                        └──────────┬───────────────────────┘              │
│                                   │                                      │
│                    ┌──────────────┼──────────────┐                       │
│                    ▼              ▼              ▼                       │
│                 DVH por     BED, EUD,      Isodosis +                   │
│                 ROI (5)     EQD2 (6)       Visualización 3D (8)         │
│                                                                          │
│                                   ▼                                      │
│                        ┌──────────────────────┐                         │
│                        │   Reporte PDF (9)    │                         │
│                        └──────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────────┘
```

### Paso 1: `load_scene` — Cargar escena desde Módulo 1

Carga el archivo `.mrb` generado por el Módulo 1. Contiene:
- **CT**: volumen anatómico de referencia
- **PET**: actividad en Bq/mL (ya calibrado)
- **Labelmap**: segmentación con índices de tejido (90=hígado, 100=tumor, 200=peritumoral)
- **ROIs**: volúmenes de interés (hígado, tumor, peritumoral, body)

### Paso 2: `read_pet_activity` — Leer actividad PET

Lee la actividad desde DICOM PET raw replicando la función MATLAB `f_Rescale_Bq.m`. Si no hay PET disponible, acepta actividad por línea de comandos (`--activity`). Ver [`lectura_actividad.md`](lectura_actividad.md).

### Paso 3: `parse_mctal` — Parsear archivo MCTAL

Procesa el archivo ASCII generado por MCNP6. Lee:
- Dimensiones de la grilla TMESH
- Boundaries de voxeles
- Valores de energía depositada (MeV/cm³ por partícula fuente)
- Errores relativos asociados

Aplica reshaping column-major Fortran y filtros de calidad. Ver [`parse_mctal.md`](parse_mctal.md).

### Paso 4: `convert_to_dose` — Convertir MeV/cm³ a Gy

**Ruta MCTAL:**
$$D_{\text{Gy}} = \frac{D_{\text{raw}}}{\rho} \times 1.6\times10^{-13} \times \tau \times A \times 1000$$

**Ruta Kernel (FFT):**
$$D_{\text{Gy}} = \text{FFT}^{-1}\big[\text{FFT}(A_{\text{GBq}}) \cdot \text{FFT}(K_{\text{norm}})\big] \times \text{mask}$$

Donde el kernel.mat **ya incluye** $$\tau \times A$$ — **NO se multiplica nuevamente**. Ver [`conversion_dosis.md`](conversion_dosis.md).

### Paso 5: `compute_dvh` — Histograma Dosis-Volumen

Calcula DVH acumulativo para cada ROI con 200 puntos (99 intervalos):

$$V(D) = \frac{1}{N}\sum_i [D_i \geq D] \times 100\%$$

Extrae D98, D95, D70, D50, D5, D2, V30, V70. Ver [`dvh.md`](dvh.md).

### Paso 6: `compute_radiobiology` — BED, EUD, EQD2

$$\text{BED} = D + \frac{\lambda}{(\alpha/\beta)(\lambda + \mu)} \cdot D^2$$

$$\text{EUD} = \left(\sum_i v_i D_i^a\right)^{1/a}$$

$$\text{EQD2} = \frac{\text{BED}}{1 + 2/(\alpha/\beta)}$$

Ver [`radiobiologia.md`](radiobiologia.md).

### Paso 7: `mird_partition` — Modelo MIRD de Partición

Calcula dosis media en hígado y tumor usando el modelo de partición:

$$T/N = \frac{\text{actividad\_PET\_tumor}}{\text{actividad\_PET\_higado}}$$
$$D_{\text{higado}} = \frac{A \cdot k \cdot \text{FU}_{\text{normal}}}{m_{\text{higado}}}$$

Ver [`mird.md`](mird.md).

### Paso 8: `visualize_slicer` — Visualización en 3D Slicer

Renderiza el mapa de dosis con overlay rainbow invertido, contornos de isodosis (10 niveles, 10%–100%), y DVH interactivo en módulo Plots. Ver [`visualizacion_slicer.md`](visualizacion_slicer.md).

### Paso 9: `export_report` — Exportar reporte PDF

Genera un reporte clínico PDF que incluye:
- Parámetros del paciente (actividad, isótopo, dosis prescrita)
- Mapa de dosis 3D (captura de Slicer)
- DVH por ROI con tabla de métricas
- Índices radiobiológicos (BED, EUD, EQD2)
- Resultados del modelo MIRD
- Fecha, firma del médico, sello institucional

### Paso 10: `save_scene` — Guardar escena final

Guarda el archivo `.mrb` con todos los nodos de dosis, isodosis y DVH para inspección posterior en Slicer.

---

## 3. Dos Rutas de Cálculo de Dosis

| Característica | Ruta MCTAL (Monte Carlo) | Ruta Kernel (Convolución FFT) |
|----------------|:------------------------:|:----------------------------:|
| Origen de datos | Archivo MCTAL de MCNP6 | `kernel.mat` precalculado |
| Tiempo de cómputo | Horas (MCNP real) | Segundos (FFT) |
| Precisión | Alta (transporte completo) | Aproximada (medio homogéneo) |
| Multiplica por $$\tau$$ | Sí | No (kernel.mat ya lo incluye) |
| Multiplica por $$A$$ | Sí | Sí (en GBq/voxel) |
| Densidad por voxel | Sí ($$\rho$$ de labelmap) | No (densidad en kernel) |
| Uso clínico | Validación final | Planificación rápida |

---

## 4. Entradas y Salidas

| Elemento | Ruta típica | Descripción |
|----------|-------------|-------------|
| **Entrada: escena .mrb** | `resultados_test/scenes/3Dosim_scene.mrb` | Escena con CT+PET+labelmap+ROIs |
| **Entrada: kernel.mat** | `kernel/kernel.mat` | Kernel de dosis precalculado para FFT |
| **Entrada: MCTAL** | `resultados_test/mcnp/paciente.o` | Output MCNP6 con tallies |
| **Salida: dosis 3D** | `resultados_test/dose/` | Mapa de dosis en Gy (NRRD) |
| **Salida: DVH** | `resultados_test/dvh/dvh.csv` | Tabla DVH por ROI |
| **Salida: reporte** | `resultados_test/reports/3Dosim_reporte.pdf` | Reporte clínico completo |
| **Salida: escena final** | `resultados_test/scenes/3Dosim_dosis_final.mrb` | Escena con todos los nodos |

---

## 5. Archivos de Código

| Archivo | Función |
|---------|---------|
| `pet_dicom_reader.py` | Lectura de actividad PET DICOM raw |
| `mctal_parser.py` | Parser de archivos MCTAL MCNP |
| `dosimetry.py` | Conversión MeV/cm³ → Gy (ruta MCTAL) |
| `dose_kernel.py` | Carga de kernel.mat (sin normalizar) |
| `fft_dose.py` | Convolución FFT optimizada |
| `dvh_analysis.py` | Cálculo de DVH y métricas |
| `radiobiology.py` | BED, EUD, EQD2, NTCP, TCP |
| `mird_partition.py` | Modelo MIRD de partición |
| `isodose_contours.py` | Generación de contornos de isodosis |
| `report_pdf.py` | Generación de reporte PDF |
| `run_dosimetry_from_scene.py` | Orquestador del pipeline Mod3 |

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| Actividad PET > 0 | Actividad total <= 0 Bq |
| MCTAL válido | error ≥ 1.5 o dosis negativa en > 5% voxeles |
| Dosis media en tumor ≥ dosis en hígado | D_tumor < D_liver (biológicamente imposible en Y-90) |
| DVH monótono decreciente | Punto DVH con pendiente positiva |
| BED ≥ D físic (dosis altas) | BED < D (error fórmula) |
| EUD dentro de rango | EUD fuera de [min(D), max(D)] |
| Volumen de dosis conservado | V30 + V70 > 110% (inconsistencia) |
| Reporte PDF generado | Archivo no existe o < 10 KB |

---

## 7. Referencias

- MCNP6 User's Manual, LA-UR-13-22934 (2013)
- MIRD Pamphlet No. 21: A Generalized Schema for Radiopharmaceutical Dosimetry (2009)
- Gulec et al., "Hepatic Radioembolization with Y-90 Microspheres", Semin Nucl Med (2008)
- Dezarn et al., "Recommendations for Radioembolization Dosimetry", J Vasc Interv Radiol (2021)
- Fowler JF, "The Linear-Quadratic Formula and Progress in Fractionated Radiotherapy", BJR (1989)
- Niemierko A, "Reporting and Analyzing Dose Distributions: EUD", Med Phys (1997)
