# Visión General — Módulo 2: Generación de Input MCNP

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MCNP | Monte Carlo N-Particle (transport code, LANL) |
| TMESH | Tally MESH (grilla de dosis en MCNP) |
| SDEF | Source Definition (tarjeta de fuente en MCNP) |
| RLE | Run-Length Encoding (compresión de geometría) |
| VOI | Volume of Interest |
| HU | Hounsfield Units (unidades de atenuación en TC) |
| ICRP | International Commission on Radiological Protection |
| ICRU | International Commission on Radiation Units |
| .mrb | Medical Reality Bundle (escena de 3D Slicer) |
| TS | TotalSegmentator (segmentación anatómica) |
| RPP | Rectangular Parallelepiped (caja en MCNP) |

## Contexto clínico

La dosimetría personalizada en terapias con radionúclidos ($^{90}$Y,
$^{177}$Lu, $^{131}$I) requiere transportar partículas a través de una
geometría voxelizada derivada de la TC del paciente. El Módulo 2 toma la
escena segmentada generada por el Módulo 1 (labelmap + transforms +
volúmenes) y produce un archivo de entrada listo para MCNP (.i) que
describe:

- La geometría voxelizada del paciente
- La composición y densidad de cada material (6 tejidos base + 53
  tejidos ICRP-110)
- La fuente radiactiva (isótopo, actividad, distribución espacial)
- Los detectores (tallies) para estimar dosis absorbida

El archivo generado se entrega al Módulo 3 para ejecutar MCNP y
procesar resultados.

## Pipeline de 6 pasos

El pipeline se orquesta desde `pipeline_mod2.py` y ejecuta 6 pasos en
secuencia estricta:

```
   ┌─────────────────────────────────────────────────────────┐
   │               pipeline_mod2.py                          │
   │                                                         │
   │   check_slicer()  →  load_scene()  →  scan_nodes()      │
   │                                                         │
   │   validate_prereqs()  →  generate_mcnp()  →  validate() │
   └─────────────────────────────────────────────────────────┘
```

### 1. `check_slicer()` — Verificar Slicer

Confirma que 3D Slicer está disponible (en ejecución con el módulo
SlicerDosim cargado). Sin Slicer no hay acceso a la escena .mrb.

### 2. `load_scene(mrb_path)` — Cargar escena

Carga el archivo .mrb que contiene:
- El volume node de la TC (referencia espacial)
- El labelmap segmentado por TotalSegmentator (Módulo 1)
- Las transformaciones espaciales (RAS a voxel)
- Volúmenes ROI (hígado, tumor, etc.)

### 3. `scan_nodes()` — Escanear nodos

Recorre el scene tree de 3D Slicer e identifica:

- `volume_node`: la TC del paciente
- `labelmap_node`: segmentación con materiales asignados
- `voi_nodes`: volúmenes de interés (hígado, tumor, etc.)

### 4. `validate_prereqs()` — Validar prerequisitos

Verifica que no haya valores nulos o inconsistentes antes de pasar a
generación:

- Volumen de TC cargado
- Labelmap presente y con dimensiones compatibles
- VOIs existentes (al menos hígado y tumor)

### 5. `generate_mcnp(params)` — Generar input MCNP

Paso central que invoca `mcnp_generator.py` con los parámetros del
tratamiento:

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `isotope` | str | Isótopo (`Y90`, `Lu177`, `I131`) |
| `n_particles` | int | Número de historias MCNP |
| `refine_hu` | bool | Refinar materiales por HU |
| `flip_rows` | bool | Invertir eje filas (RAS→MCNP) |
| `flip_z` | bool | Invertir eje Z |

El generador construye 12 secciones del archivo .i:

1. Comentarios/Cabecera
2. Celdas (geometría voxel + lattice)
3. Superficies (RPP contenedor)
4. Tarjetas de datos (transform, cut)
5. Materiales (composiciones + densidades)
6. Fuente (SDEF + espectro)
7. Tallies TMESH (grilla de dosis)
8. Tallies *F8 (detectores puntuales)
9. Tally F6 (energía depositada)
10. Print
11. Archivo de fuentes externo
12. Corte de geometría (opcional)

### 6. `validate_mcnp_input(ruta_i)` — Validar output

Post-procesamiento que verifica:

- Archivo > 10 KB (no vacío)
- Presencia de palabras clave MCNP obligatorias
- Coincidencia de coordenadas entre RPP y tallies
- Que no falten las tarjetas de corte
- Generación de archivo .dat de espectro y .src

## Relación con el código MATLAB legacy

3Dosim tiene dos implementaciones paralelas:

| Componente | MATLAB (v3.14) | Python (v4) |
|------------|:--------------:|:-----------:|
| Segmentación | `modulo_1/` | `SlicerDosimLib/` + TotalSegmentator |
| Generación MCNP | `modulo_2/` | `SlicerDosimLib/mcnp_*.py` |
| Post-procesamiento | `modulo_3/` | `SlicerDosimLib/dosimetry.py` |
| Kernel de dosis | `kernel/` | `dose_kernel.py` + `fft_dose.py` |
| Espectros | `espectro/` | `mcnp_source.py` (embebido) |

La versión MATLAB original escribía el input MCNP directamente desde
scripts `.m` usando fprintf. La versión Python refactoriza en 4
módulos especializados manteniendo la misma estructura de output.

### Equivalencia MATLAB → Python

```
MATLAB                        Python
───────────────────────────── ─────────────────────────────
modulo_2/Generar_Input_MCNP   mcnp_generator.py (orquestador)
  └── crear geometría         mcnp_geometry.py (RPP, lattice, RLE)
  └── asignar materiales      mcnp_materials.py (TS_SEGMENT_MAP, ICRP-110)
  └── definir fuente          mcnp_source.py (SDEF, espectro, .src)
  └── configurar tallies      mcnp_tallies.py (TMESH, *F8, F6)
  └── escribir archivo .i     generate() → paciente.i
```

## Flujo de datos

```
  Módulo 1                Módulo 2                Módulo 3
  ─────────              ─────────               ─────────
  Escena .mrb     ──►    pipeline_mod2.py  ──►   MCNP
  (TC + labelmap          │                        │
   + VOIs)                ├── check_slicer()       │
                          ├── load_scene()         │
                          ├── scan_nodes()         │
                          ├── validate_prereqs()   │
                          ├── generate_mcnp()      │
                          │     └──► paciente.i    │
                          └── validate()     ──►   mcnp6
                                                    │
                                               Resultados
                                               (mcnp_output)
```

## Pipeline configuration (JSONC)

El pipeline se configura mediante `pipeline_config.jsonc`:

```jsonc
{
  "scene_output_dir": "C:/MAT/3Dosim/ai-pipe/imagenes",
  "mcnp": {
    "isotope": "Y90",
    "n_particles": 1000000,
    "refine_hu": false,
    "flip_rows": false,
    "flip_z": false
  },
  "tumor": {
    "mode": "ts_liver_lesions",
    "synthetic_radius_mm": 10.0,
    "create_healthy_liver": true
  },
  "views": {
    "layout": "ConventionalView",
    "pet_opacity": 0.3,
    "link_slices": true
  }
}
```

### Parámetros MCNP editables

| Parámetro | JSON key | Efecto |
|-----------|----------|--------|
| Isótopo | `mcnp.isotope` | Selecciona espectro de energías |
| Partículas | `mcnp.n_particles` | Precisión estadística |
| Refinar HU | `mcnp.refine_hu` | Activa refinamiento por HU |
| Flip rows | `mcnp.flip_rows` | Corrige eje RAS→LPS |
| Flip Z | `mcnp.flip_z` | Invierte slices |

## Secciones del input MCNP

El archivo generado sigue la estructura canónica de MCNP6:

```
Mensaje de bloqueo    (1 línea)
C                    Comentarios de cabecera
C                      Paciente, isótopo, fecha
C
Bloque de celdas      100 1 -0.001205 -1 2 3 ...  $ Celda voxel
                      999 0 -1000                   $ Celda mundo
                      ...
Bloque de superficies 1 RPP -150 150 -200 200 ...   $ Caja contenedora
                      ...
Bloque de datos       MODE P E
                      IMP:P 1
                      CUT:P 1e10
                      MATERIALES (Mn celdas)
                      SDEF POS=... ERG=... WGT=...
                      TMESH
                      *F8
                      F6
                      PRINT
```

## Referencias

- MCNP6 User's Manual, LA-UR-13-22934 (2013)
- ICRP Publication 110: Adult Reference Computational Phantoms (2009)
- ICRU Report 44: Tissue Substitutes in Radiation Dosimetry (1989)
- Wasserthal et al., "TotalSegmentator: Robust Segmentation of 104
  Anatomic Structures in CT Images", Radiology Insights (2023)

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| Archivo .i generado | Archivo no existe o < 10 KB |
| Keywords MCNP presentes | Falta C, cells, surfaces, data |
| Coordenadas RPP coinciden con tallies | Rango TMESH fuera del RPP |
| Tarjetas CUT presentes | Modo P o E sin CUT:P/E |
| Materiales asignados | Voxel con índice 0 (sin material) |
| Archivo .src generado | No existe o está vacío |
