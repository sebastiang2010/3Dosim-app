# Módulo 1 — Segmentación, Registro y Fusión de Imágenes

> **Portal de documentación técnica del pipeline de preparación para dosimetría hepática con $^{90}$Y.**

---

## ¿Qué hace el Módulo 1?

La dosimetría interna con $^{90}$Y requiere conocer **dónde está cada tejido** (hígado, tumor, pulmón, hueso) y **cuánta actividad hay en cada punto** (PET). El Módulo 1 toma imágenes DICOM crudas — un CT anatómico y un PET funcional — y las procesa a través de 12 pasos automatizados para producir una **labelmap dosimétrica**: un volumen 3D donde cada voxel tiene un número entero que identifica su tipo de tejido según la tabla de materiales ICRP-110/ICRU-44.

Sin este módulo, no es posible asignar materiales MCNP ni calcular dosis voxel a voxel. Es la **puerta de entrada** del pipeline 3Dosim.

---

## Diagrama de Flujo General

```
                          ┌─────────────────────────┐
                          │  DICOM CRUDO             │
                          │  CT (512×512×N, 0.97 mm) │
                          │  PET (200×200×N, 4.07 mm)│
                          └────────┬────────┬────────┘
                                   │        │
                          ┌────────▼────────▼────────┐
                          │  1. Carga DICOM          │
                          │     (DB temporal Slicer) │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  2. Calibración PET       │
                          │     raw → Bq/mL por slice │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  3. Eliminar Camilla+Aire │
                          │     (threshold + morfología)│
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  4. Registro PET → CT     │
                          │     (BRAINSResample / NumPy)│
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  5. Fusión CT+PET         │
                          │     (layout 4-up + diálogo)│
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  6. Anonimización         │
                          │     (limpiar metadatos)   │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  7. TotalSegmentator      │
                          │     104 clases anatómicas │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  8. Validación Médica     │
                          │     ⛔ paso OBLIGATORIO   │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │  9. Creación de Tumor     │
                          │     4 modos configurables │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │ 10. Validación Tumor      │
                          │     ⛔ paso OBLIGATORIO   │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │ 11. Hígado Sano           │
                          │     = hígado − tumor      │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │ 12. Body Segmentation     │
                          │     TS task="body"        │
                          └────────┬─────────────────┘
                                   │
                          ┌────────▼─────────────────┐
                          │ 13. Exportar Labelmap     │
                          │     NIfTI + NRRD c/ IDs  │
                          └────────┬─────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │  LABELMAP DOSIMÉTRICA lista    │
                    │  para Módulo 2 (generación     │
                    │  de entrada MCNP)              │
                    └───────────────────────────────┘
```

---

## Los 12 Pasos en Detalle

| # | Paso | Archivo fuente | Entrada | Salida |
|:-:|------|---------------|---------|--------|
| 1 | Carga DICOM | `pipeline_mod1.py` | Directorios DICOM CT+PET | Nodos `CT`, `PET` en escena Slicer |
| 2 | Calibración PET | `pet_dicom_reader.py` | DICOM PET raw | `A_{total}` [Bq], `PET_{cal}` [Bq/mL] |
| 3 | Eliminar Camilla | `couch_remover.py` | CT [HU] | `CT_{sin\_camilla}` [HU] |
| 4 | Registro PET→CT | `pet_registration.py` | `PET_{cal}` + `CT` | `PET_{registrado}` en grilla CT |
| 5 | Fusión CT+PET | `fusion_dialog.py` | `CT`, `PET_{reg}` | Diálogo informativo NO modal |
| 6 | Anonimización | `pipeline_mod1.py` | DICOM original | `ANON\_CT`, `ANON\_PET` |
| 7 | TotalSegmentator | `segmentation.py` | CT anonimizado | 104 segmentos anatómicos |
| 8 | Validación Médica | `validation.py` | Segmentos TS | Aprobación/rechazo |
| 9 | Creación Tumor | `tumor_creator.py` | Hígado (TS) | Máscara tumoral |
| 10 | Validación Tumor | `tumor_validation.py` | Tumor | Aprobación/rechazo |
| 11 | Hígado Sano | `tumor_creator.py` | Hígado + Tumor | `M_{higado} \setminus M_{tumor}` |
| 12 | Body Segmentation | `segmentation.py` | CT | Contorno corporal |
| 13 | Exportar Labelmap | `labelmap_exporter.py` | Todos los segmentos | `labelmap.nii` + `labelmap.nrrd` |

---

## Archivos de Configuración

| Archivo | Propósito | Claves principales |
|---------|-----------|-------------------|
| `pipeline_config.jsonc` | Config global del pipeline | `scene_output_dir`, `tumor.mode`, `ai_supervisor`, `patient_weight_kg` |
| `totalsegmentator_config.jsonc` | Config TS task="total" | `task`, `fast`, `force_cpu`, `subset` |
| `totalsegmentator_config_body.jsonc` | Config TS task="body" | `task`, `fast`, `force_cpu` |
| `tissue_config.json` | 53+ tejidos ICRP-110 | `ts_label_to_phantom`, `tissues[].mcnp_material` |

---

## Modos de Ejecución

### Completo (12 pasos)
```bash
& "Slicer.exe" --python-script "main.py" --data-dir "Paciente_2"
```

### Hasta fusión (test rápido, 5 pasos)
```bash
& "Slicer.exe" --python-script "main.py" --data-dir "Paciente_2" --stop-after-fusion
```

### Hasta antes de segmentar (segmentación manual)
```bash
& "Slicer.exe" --python-script "main.py" --data-dir "Paciente_2" --stop-before-segment
```

### Reset (borrar checkpoints, empezar de cero)
```bash
& "Slicer.exe" --python-script "main.py" --data-dir "Paciente_2" --reset
```

---

## Estructura de Directorios de Salida

```
output_dir/
├── anon/
│   ├── ANON_CT.nrrd       (CT anonimizado)
│   └── ANON_PET.nii       (PET anonimizado)
├── checkpoints/
│   └── pipeline_checkpoint.json  (estado persistente)
├── labelmaps/
│   ├── labelmap.nii       (NIfTI para Módulo 2 — MCNP)
│   └── labelmap.nrrd      (NRRD para Slicer)
├── logs/
│   ├── pipeline_mod1.log  (log del pipeline)
│   └── ai_supervisor.log  (log del AI Supervisor)
└── summary.txt            (resumen de la ejecución)
```

---

## Documentos Relacionados

| Documento | Contenido |
|-----------|-----------|
| [Visión General](./vision_general.md) | Arquitectura, stack tecnológico, índices del phantom |
| [Pipeline Completo](./pipeline_completo.md) | Secuencia detallada de los 12 pasos |
| [Carga DICOM](./carga_dicom.md) | Indexación y carga de CT+PET desde DICOM |
| [Calibración PET](./calibracion_pet.md) | Conversión raw → Bq/mL con factores por slice |
| [Eliminar Camilla](./eliminar_camilla.md) | Umbral HU + morfología + componente conexa |
| [Registro PET/CT](./registro_pet.md) | Remuestreo PET→CT (3 métodos + conservación actividad) |
| [Fusión CT+PET](./fusion_ct_pet.md) | Layout 4-up + diálogo informativo |
| [Anonimización](./anonimizacion.md) | Limpieza de metadatos DICOM (HIPAA/GDPR) |
| [TotalSegmentator](./totalsegmentator.md) | Segmentación automática de 104 clases |
| [Mapeo TS → Phantom](./mapeo_phantom.md) | Conversión de labels TS a índices de material |
| [Creación de Tumor](./creacion_tumor.md) | 4 modos: synthetic, load_file, manual, TS |
| [Validación Médica](./validacion_medica.md) | Diálogos NO modales obligatorios |
| [Segmentación Body](./segmentacion_body.md) | Contorno corporal con TS task="body" |
| [Exportar Labelmap](./exportar_labelmap.md) | NIfTI + NRRD con resolución de solapamientos |
| [Checkpoint System](./checkpoint_system.md) | Persistencia JSON y reanudación |
| [AI Supervisor](./ai_supervisor.md) | Verificaciones automáticas post-paso |
| [Visualización 3D](./visualizacion_3d.md) | Layout médico, volumen rendering, slice linking |

---

## Flujo de Datos entre Módulos

```
Módulo 1 (este)              Módulo 2                     Módulo 3
─────────────                ──────────                   ──────────
CT + PET                     Labelmap dosimétrica         Output MCNP
     │                             │                           │
     ▼                             ▼                           ▼
Segmentación anatómica        Generación input MCNP        Post-procesamiento
Registro PET→CT              (geometría voxelizada,       (dosis, DVH, BED,
Creación de tumor            fuentes Y-90, materiales     EUD, NTCP, TCP,
Validación médica            ICRP-110, tallies FMESH4)    isodosis, reporte
Export labelmap                                            PDF LaTeX)
```

---

## Acrónimos Usados en este Módulo

| Acrónimo | Significado |
|----------|-------------|
| 3Dosim | Pipeline de dosimetría interna 3D para radioembolización hepática |
| ASGD | Adaptive Stochastic Gradient Descent — optimizador de Elastix |
| CT | Computed Tomography — imagen anatómica en Hounsfield Units (HU) |
| DICOM | Digital Imaging and Communications in Medicine — estándar médico |
| DOF | Degrees of Freedom — grados de libertad de una transformación |
| GDPR | General Data Protection Regulation — regulación europea de datos |
| HIPAA | Health Insurance Portability and Accountability Act — privacidad EEUU |
| HU | Hounsfield Unit — escala de densidad radiológica (agua=0, aire=-1000) |
| ICRP-110 | Publicación 110: phantoms computacionales de referencia |
| ICRU-44 | Reporte 44: composiciones de tejidos para dosimetría |
| MCNP | Monte Carlo N-Particle — código de simulación de transporte de radiación |
| MI | Mutual Information — métrica de similitud entre imágenes |
| MIRD | Medical Internal Radiation Dose — modelo analítico de dosimetría |
| NCC | Normalized Cross-Correlation — métrica de similitud (rango [-1,1]) |
| NIfTI | Neuroimaging Informatics Technology Initiative — formato .nii |
| NRRD | Nearly Raw Raster Data — formato .nrrd nativo de Slicer |
| PET | Positron Emission Tomography — imagen funcional de actividad |
| PHI | Protected Health Information — datos de salud protegidos |
| SF | Shunt Fraction — fracción de microesferas que escapan al pulmón |
| SUV | Standardized Uptake Value — medida semicuantitativa PET |
| T/N | Tumor-to-Normal ratio — razón de captación PET tumor/hígado |
| TS | TotalSegmentator — segmentador anatómico por deep learning |

---

## Verificación Final del Módulo

- [ ] CT y PET cargados y visibles en escena Slicer
- [ ] PET calibrado: actividad total $> 0$ Bq, RescaleType = "BQML"
- [ ] Camilla eliminada: volumen removido $< 50\%$ del total
- [ ] PET registrado a CT: NCC $> 0.6$ entre PET y CT
- [ ] Fusión visual verificada: CT $+$ PET con opacidad 0.35
- [ ] Anonimización completada: metadatos DICOM limpiados
- [ ] TotalSegmentator: $N_{seg} \geq 20$ segmentos generados
- [ ] Médico aprobó segmentación (obligatorio, sin auto-approve)
- [ ] Tumor creado: $V_{tumor} \geq 0.5$ cm³, dentro del hígado
- [ ] Médico aprobó tumor (obligatorio)
- [ ] Body contiene todos los órganos (ninguno fuera)
- [ ] Labelmap exportada: solapamiento $= 0$, sin voxeles sin asignar
