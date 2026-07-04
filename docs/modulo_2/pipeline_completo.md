# Pipeline Completo — Integración del Módulo 2

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| FS | Final State (estado final del pipeline) |
| QC | Quality Control |
| MCNP | Monte Carlo N-Particle |
| MIRD | Medical Internal Radiation Dose |
| SIRT | Selective Internal Radiation Therapy |
| TACE | Transarterial Chemoembolization |
| PRRT | Peptide Receptor Radionuclide Therapy |
| VOI | Volume of Interest |
| ROI | Region of Interest |
| .mrb | Medical Reality Bundle |
| .i | Input file (MCNP input) |
| .o | Output file (MCNP output) |
| .m | METAL file (resultados procesados) |

## Contexto clínico

3Dosim es un sistema de dosimetría personalizada para terapias con
radionúclidos. El pipeline completo consta de 3 módulos secuenciales:

```
  Módulo 1          Módulo 2           Módulo 3
  Segmentación      Generación MC      Ejecución MC
  ──────────        ────────────       ───────────
  TC + PET          Escena .mrb        Input .i
       │                 │                  │
       ▼                 ▼                  ▼
  TotalSegmentator   pipeline_mod2.py    mcnp6
  Labelmap 3D        Input MCNP (.i)    MCTAL
  VOIs .vtk          Espectro (.dat)    Dosis (Gy)
  Escena .mrb        Fuente (.src)      Isodosis
       │                 │                  │
       └─────────────────┴──────────────────┘
                          │
                     Dosis por VOI
                     Mapas de dosis 3D
                     DVH (histograma dosis-volumen)
```

Este documento describe la integración del Módulo 2 en el flujo total y
las interfaces con los módulos vecinos.

## Interfaces

### Entrada (desde Módulo 1)

El Módulo 2 recibe:

| Elemento | Formato | Descripción |
|----------|---------|-------------|
| Escena 3D Slicer | .mrb | TC + labelmap + VOIs |
| Labelmap segmentado | NRRD | Índices de 1 a 153 |
| VOIs | VTK | Mallas de hígado, tumor, riñones |
| Parámetros clínicos | JSON/dict | Isótopo, actividad, n_particles |

### Salida (hacia Módulo 3)

El Módulo 2 produce:

| Elemento | Formato | Descripción |
|----------|---------|-------------|
| Input MCNP | .i | Archivo de entrada listo para MCNP6 |
| Fuente externa | .src | Posiciones de partículas muestreadas |
| Espectro | .dat | Distribución de energías |
| Metadata | .json | Parámetros usados en la generación |

## Orquestación completa

### Desde 3D Slicer (SlicerDosim)

El pipeline típico se inicia desde el módulo SlicerDosim:

```python
# Pseudocódigo del flujo de integración
def run_dosimetry_from_scene(mrb_path, params):
    # ===== Módulo 1: Segmentación (scope de Mod1) =====
    scene = slicer.util.loadScene(mrb_path)
    # ... segmentación, refinamiento, VOIs ...
    
    # ===== Módulo 2: Generación de input MCNP =====
    from pipeline_mod2 import PipelineMod2
    mod2 = PipelineMod2()
    
    mod2.check_slicer()
    mod2.load_scene(mrb_path)
    mod2.scan_nodes()
    mod2.validate_prereqs()
    input_path = mod2.generate_mcnp(params)
    mod2.validate(input_path)
    
    # ===== Módulo 3: Ejecución MCNP =====
    # ... run mcnp6, parse output, generate dose volumes ...
```

### Desde línea de comandos (standalone)

El pipeline también soporta ejecución independiente:

```bash
python pipeline_mod2.py --scene paciente.mrb \
    --isotope Y90 \
    --n_particles 1000000 \
    --output_dir ./output
```

## Diagrama de flujo detallado

```
                             ┌─────────────┐
                             │   Inicio     │
                             │ (SlicerDosim)│
                             └──────┬──────┘
                                    │
                                    ▼
                            ┌─────────────────┐
                            │  Cargar escena  │
                            │  loadScene(.mrb)│
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  scan_nodes()   │
                            │  Identificar:   │
                            │  • volume_node  │
                            │  • labelmap     │
                            │  • VOIs         │
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  validate_      │
                            │  prereqs()      │
                            │  4 checks       │
                            └────────┬────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
              ¿TC OK?          ¿Labelmap OK?     ¿VOIs OK?
                    │                │                │
                    └───────┬────────┴────────┬───────┘
                            ▼                 ▼
                     Continuar            Detener
                            │
                            ▼
              ┌─────────────────────────────┐
              │  Configurar TissueConfig    │
              │  Cargar tissue_config.json  │
              │  (59 materiales totales)     │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │  Construir bloques del .i   │
              │                             │
              │  ┌─► Cabecera (metadata)    │
              │  ├─► Celdas (lattice+RLE)   │
              │  ├─► Superficies (RPP)      │
              │  ├─► Datos (MODE/CUT/IMP)   │
              │  ├─► Materiales (M1..M6+)   │
              │  ├─► SDEF (espectro+src)    │
              │  ├─► TMESH (grilla 3D)      │
              │  ├─► *F8 (detectores VOI)   │
              │  ├─► F6 (energía total)     │
              │  ├─► PRINT/PRDMP            │
              │  └─► Archivo .src externo   │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │  Escribir paciente.i        │
              │  Escribir paciente.src      │
              │  Escribir paciente.dat      │
              └─────────────┬───────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │  validate_mcnp_input()      │
              │  5 verificaciones           │
              └─────────────┬───────────────┘
                            │
                    ┌───────┴───────┐
                    ▼               ▼
                Válido           Inválido
                    │               │
                    ▼               ▼
        ┌─────────────────┐  ┌──────────────┐
        │  Continuar      │  │  Corregir y  │
        │  a Módulo 3     │  │  regenerar   │
        └─────────────────┘  └──────────────┘
```

## Dependencias entre secciones del .i

El generador debe respetar dependencias implícitas:

```
  Superficies (RPP) ──────────► Celdas (usan números de superficie)
        │                              │
        │                              ▼
        │                     Materiales (M1..M6+)
        │                              │
        ▼                              ▼
  TMESH (coordenadas           Celdas (MAT + RHO)
  deben coincidir con RPP)          │
                                    ▼
                              SDEF (archivo .src)
                                    │
                                    ▼
                              *F8 / F6 (celdas de VOI)
```

## Manejo de errores y estados

### Estados del pipeline

| Estado | Significado |
|--------|-------------|
| `INIT` | Pipeline creado, sin ejecutar |
| `CHECKING_SLICER` | Verificando Slicer |
| `LOADING_SCENE` | Cargando escena .mrb |
| `SCANNING_NODES` | Identificando nodos |
| `VALIDATING` | Validando prerequisitos |
| `GENERATING` | Generando input MCNP |
| `VALIDATING_OUTPUT` | Validando archivo generado |
| `COMPLETED` | Pipeline terminado exitosamente |
| `FAILED` | Pipeline falló |

### Errores comunes

| Error | Causa | Solución |
|-------|-------|----------|
| `SceneLoadError` | .mrb corrupto | Regenerar escena en Mod1 |
| `NodeNotFound` | Falta volume/labelmap | Verificar segmentación |
| `DimensionMismatch` | TC ≠ labelmap | Reprocesar Mod1 |
| `TissueConfigError` | JSON mal formado | Verificar tissue_config.json |
| `MCNPValidationError` | Input inválido | Revisar validate_mcnp_input.py |
| `SourceSamplingError` | VOI vacío | Verificar segmentación tumor |

## Integración con el resto del sistema

```
                    ┌──────────────────────┐
                    │   3Dosim v4.0        │
                    │   Interfaz Slicer    │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      ┌────────────┐  ┌──────────────┐  ┌──────────────┐
      │  Módulo 1  │  │  Módulo 2    │  │  Módulo 3    │
      │ Segmentac. │──►│ Gen. Input   │──►│ Ejecución    │
      │ (Python)   │  │ (Python)     │  │ (MCNP + Py)  │
      └────────────┘  └──────────────┘  └──────────────┘
                              │                  │
                              ▼                  ▼
                     ┌──────────────┐  ┌──────────────┐
                     │tissue_config │  │   MCTAL      │
                     │.json         │  │   Parser     │
                     │ICRP-110      │  │   Dosis en Gy│
                     └──────────────┘  └──────────────┘
```

## Flujo de datos entre módulos

```
Módulo 1 → Módulo 2:
  scene.mrb (NRRD + VTK + MRML)

Módulo 2 → Módulo 3:
  paciente.i
  paciente.src
  paciente.dat

Módulo 3 → Salida clínica:
  Dose volume (NRRD, Gy)
  Isodose contours (VTK)
  Dosis por VOI (CSV/JSON)
  DVH (CSV/JSON)
```

## Referencias

- Arquitectura 3Dosim v4, `docs/modulo_1/vision_general.md`
- MCNP6 User's Manual, LA-UR-13-22934
- ICRP Publication 110, Ann. ICRP 39(2), 2009
- Loevinger et al., MIRD Primer, SNM, 1988
- 3Dosim PipelineOrchestrator, `pipeline_mod2.py`
- 3Dosim SlicerDosim, `SlicerDosimMod3.py`
