# Generación del Input MCNP

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| RFL | Característica de formato MCNP (Right, Left, Free) |
| NPS | Number of Particles (número de historias) |
| CTME | Cutoff Time (tiempo máximo de simulación) |
| MODE | Modalidad de transporte (P: fotón, E: electrón) |
| IMP | Importance (importancia de celda) |
| VOID | Tarjeta VOID (espacio vacío sin transporte) |
| PRDMP | Print Dump (control de impresión) |
| LOST | Lost particles (partículas perdidas) |
| DBCN | Debug Control (control de depuración) |

## Contexto clínico

La generación del input MCNP es el paso central del Módulo 2. Recibe los
datos de la escena procesada (labelmap, TC, VOIs, parámetros del
tratamiento) y produce un archivo de texto con formato MCNP6 (.i) listo
para ejecutar.

El generador `mcnp_generator.py` organiza el input en 12 secciones
siguiendo la estructura canónica de MCNP: mensaje de bloqueo,
comentarios, celdas, superficies y datos.

## Flujo de generación

```
  Parámetros del tratamiento
  (isótopo, n_particles, refine_hu, flip_rows, flip_z)
         │
         ▼
  mcnp_generator.generate()
         │
         ├── 1. Cabecera (comentarios + metadata)
         ├── 2. Bloque de celdas (cell builder)
         ├── 3. Bloque de superficies (surface builder)
         ├── 4. Tarjetas de datos (data builder)
         ├── 5. Materiales (material builder)
         ├── 6. Fuente SDEF (source builder)
         ├── 7. Tallies TMESH (tally builder)
         ├── 8. Tallies *F8 (detector builder)
         ├── 9. Tally F6
         ├── 10. Print
         ├── 11. Archivo .src externo
         └── 12. Corte de geometría (geocut)
```

## Parámetros de entrada

```python
params = {
    "isotope": "Y90",        # Y90, Lu177, I131
    "n_particles": 1000000,  # 1×10⁶ historias
    "refine_hu": False,      # Refinar materiales por HU
    "flip_rows": False,      # Invertir filas RAS→MCNP
    "flip_z": False,         # Invertir slices
    "image_origin": None,    # Origen LPS opcional
}
```

## Las 12 secciones en detalle

### Sección 1: Cabecera

```
Mensaje de bloqueo (1 línea)

C ================================================================
C Archivo de entrada MCNP generado por 3Dosim v4.0
C ================================================================
C Paciente   : {patient_id}
C Isótopo    : {isotope}
C Partículas : {n_particles}
C Fecha      : {timestamp}
C Refine HU  : {refine_hu}
C Flip rows  : {flip_rows}
C Flip Z     : {flip_z}
C ================================================================
C
```

### Sección 2: Bloque de celdas

Define las celdas voxel usando `LIKE n BUT` y `LAT=1`:

```mcnp
C ===== CELDAS =====
C Celda mundo
999 0 -1000  IMP:P=1 IMP:E=1 $ Exterior (vacío)
C
C Celda lattice (voxels)
1 0 -1000 U=1 LAT=1 FILL=-{nx}:{2*nx} -{ny}:{2*ny} -{nz}:{2*nz}
1 1 1 1 2 2 2 3 3 3 3 4 ...
C
C Celdas voxel (materiales)
100 {mat_aire} -{rho_aire} U=1  $ Aire
101 {mat_blando} -{rho_blando} U=1  $ Tejido_blando
... resto de materiales ...
```

### Sección 3: Bloque de superficies

Define el RPP contenedor:

```mcnp
C ===== SUPERFICIES =====
1000 RPP {x_min} {x_max} {y_min} {y_max} {z_min} {z_max}
```

Las coordenadas se calculan desde el origen RAS y espaciado:

$$ \begin{aligned}
x_{min} &= -origin_{RAS,x} - \frac{espaciado_x \cdot n_x}{2} \\
x_{max} &= -origin_{RAS,x} + \frac{espaciado_x \cdot n_x}{2} \\
y_{min} &= -origin_{RAS,y} - \frac{espaciado_y \cdot n_y}{2} \\
y_{max} &= -origin_{RAS,y} + \frac{espaciado_y \cdot n_y}{2} \\
z_{min} &= origin_{RAS,z} - \frac{espaciado_z \cdot n_z}{2} \\
z_{max} &= origin_{RAS,z} + \frac{espaciado_z \cdot n_z}{2}
\end{aligned} $$

### Sección 4: Tarjetas de datos

```mcnp
C ===== DATOS =====
MODE P E
IMP:P 1 $ Importancia fotón = 1 en todas las celdas
IMP:E 1 $ Importancia electrón = 1 en todas las celdas
CUT:P 1e10 $ Tiempo de corte para fotones
CUT:E 1e10 $ Tiempo de corte para electrones
```

### Sección 5: Materiales

Sección generada por `mcnp_materials.py`. Cada material M se define una
sola vez y se referencia por ID en las celdas:

```mcnp
C ===== MATERIALES =====
M1   6000 0.000124  7000 0.755268  8000 0.231481  18000 0.012827 $ Aire
M2   1000 0.105  6000 0.143  7000 0.034  8000 0.708  $ Tejido_blando
     11000 0.002  15000 0.003  16000 0.003  17000 0.002
     19000 0.003
...
M6   1000 0.102  6000 0.131  7000 0.031  8000 0.724  $ Tumor
     ...
```

### Sección 6: Fuente SDEF

Define la fuente radiactiva. Cuando se usa archivo .src externo:

```mcnp
C ===== FUENTE =====
SDEF POS=0 0 0 ERG=D1 WGT=1 PAR=P
SI1 L 0.25 1.39
SP1 0.3 0.7
```

### Sección 7: Tallies TMESH

Grilla de dosis 3D:

```mcnp
C ===== TMESH =====
TMESH
  RMESH1:PEDEP PEDEP
  CORA1 {x_min} {x_max} {nx}
  CORB1 {y_min} {y_max} {ny}
  CORC1 {z_min} {z_max} {nz}
  DE4 0.001 0.003 0.01 0.03 0.1 0.3 1.0 2.0 3.0 5.0 10.0
  DF4 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0
  ENDSD
```

### Sección 8: Tallies *F8

Detectores en VOIs:

```mcnp
C ===== *F8 =====
*F8:P {celda_higado}
*F18:P {celda_tumor}
*F28:P {celda_rinon_izq}
*F38:P {celda_rinon_der}
```

### Sección 9: Tally F6

Energía total depositada:

```mcnp
C ===== F6 =====
F6:P {celda_body}
```

### Sección 10: Print

Control de impresión de resultados:

```mcnp
C ===== PRINT =====
PRINT
PRDMP 2J 1
```

### Sección 11: Archivo de fuente externo

Cuando `n_particles > 0` y se usa distribución en VOI, se genera un
archivo `.src` con las posiciones muestreadas:

```
{output_dir}/{patient_id}.src
```

### Sección 12: Corte de geometría (opcional)

Geometría simplificada para debugging:

```mcnp
C ===== GEOCUT =====
VOID
```

Solo se incluye si la variable de entorno `DOSIM_DEBUG_GEOM` está
activa.

## Flujo completo de generate()

```python
def generate(params, volume_node, labelmap_node, voi_nodes, output_dir):
    """Genera el archivo de input MCNP.
    
    Args:
        params: dict con parámetros del tratamiento
        volume_node: nodo de TC de 3D Slicer
        labelmap_node: nodo de segmentación
        voi_nodes: lista de nodos VOI
        output_dir: directorio de salida
        
    Returns:
        str: ruta al archivo .i generado
    """
    # 1. Extraer parámetros espaciales
    origin = volume_node.GetOrigin()
    spacing = volume_node.GetSpacing()
    dims = volume_node.GetImageData().GetDimensions()
    
    # 2. Inicializar configuraciones
    tissue_config = TissueConfig.load_config()
    label_data = slicer.util.arrayFromVolume(labelmap_node)
    
    # 3. Construir bloques
    blocks = {
        "header": build_header(params),
        "cells": build_cells(dims, label_data, tissue_config,
                             params["flip_rows"], params["flip_z"]),
        "surfaces": build_surfaces(origin, spacing, dims),
        "data": build_data(),
        "materials": build_materials(tissue_config),
        "source": build_source(params),
        "tmesh": build_tmesh(origin, spacing, dims),
        "f8": build_f8(voi_nodes),
        "f6": build_f6(),
        "print": build_print(),
        "src_file": build_src_file(params, voi_nodes),
        "geocut": build_geocut() if DEBUG_GEOM else ""
    }
    
    # 4. Escribir archivo
    output_path = join(output_dir, f"{patient_id}.i")
    with open(output_path, "w") as f:
        f.write(message_block)
        for block_name, block_content in blocks.items():
            if block_content:
                f.write(block_content)
    
    return output_path
```

## Validación post-generación

Después de escribir el archivo, `validate_mcnp_input()` ejecuta:

### Verificación 1: Tamaño mínimo

```python
assert os.path.getsize(path) > 10_000, "Archivo demasiado pequeño"
```

### Verificación 2: Keywords obligatorias

```python
keywords = ["C ", "M", "SDEF", "TMESH", "CORA", "CORB", "CORC",
            "MODE", "CUT", "PRINT", "FILL", "LAT", "RPP"]
content = open(path).read()
for kw in keywords:
    assert kw in content, f"Falta keyword: {kw}"
```

### Verificación 3: Coincidencia RPP vs TMESH

```python
# Extraer límites y verificar que TMESH esté dentro de RPP
rpp = extract_rpp(content)
tmesh = extract_tmesh_limits(content)
assert (tmesh[0] >= rpp[0] and tmesh[1] <= rpp[1] and
        tmesh[2] >= rpp[2] and tmesh[3] <= rpp[3] and
        tmesh[4] >= rpp[4] and tmesh[5] <= rpp[5]), (
    "TMESH fuera de los límites del RPP"
)
```

### Verificación 4: Tarjetas CUT

```python
modes = extract_modes(content)
if "P" in modes:
    assert "CUT:P" in content, "Falta CUT:P"
if "E" in modes:
    assert "CUT:E" in content, "Falta CUT:E"
```

### Verificación 5: Archivo .src generado

```python
src_path = path.replace(".i", ".src")
if params["n_particles"] > 0:
    assert os.path.exists(src_path), "Falta archivo .src"
    assert os.path.getsize(src_path) > 0, "Archivo .src vacío"
```

## Archivos de salida

| Archivo | Contenido | Tamaño típico |
|---------|-----------|:------------:|
| `paciente.i` | Input MCNP completo | 5–100 MB |
| `paciente.src` | Posiciones de fuente | 10–100 MB |
| `paciente.dat` | Espectro de energías | 1–10 KB |
| `paciente.debug_geom.txt` | Debug geométrico (si DEBUG) | 1–5 KB |

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| Archivo .i generado con tamaño > 10 KB | Tamaño ≤ 10 KB |
| Todas las keywords MCNP presentes | Keyword faltante |
| Coordenadas TMESH dentro del RPP | TMESH fuera de límites |
| Tarjetas CUT para modos activos | Modo sin CUT |
| TODAS las celdas tienen material > 0 | Celda con material 0 |
| FILL tiene nx×ny×nz elementos | Cuenta incorrecta en FILL |
| Material M definido para cada celda | Material referenciado sin M |
| Archivo .src existe y tiene contenido | Archivo faltante o vacío |

## Referencias

- MCNP6 User's Manual, LA-UR-13-22934 (2013)
- X-5 Monte Carlo Team, "MCNP — A General N-Particle Transport Code,
  Version 5", LA-UR-03-1987 (2003)
- 3Dosim v4 PipelineOrchestrator, `mcnp_generator.py`
