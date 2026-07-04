# Geometría MCNP

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| RPP | Rectangular Parallelepiped (caja ortogonal en MCNP) |
| LIKE n BUT | Sintaxis MCNP para reutilizar celda con modificaciones |
| U | Universe (número de universo en lattice) |
| FILL | Tarjeta MCNP para rellenar una celda con un lattice |
| LAT | Lattice (grilla regular de celdas en MCNP) |
| RLE | Run-Length Encoding (codificación por longitud de carrera) |
| TRCL | Transformación de coordenadas en celda MCNP |
| VVR | Voxel Volume Representation |

## Contexto clínico

La geometría de MCNP debe representar fielmente la anatomía del paciente
a partir del labelmap segmentado. Dado que un volumen típico de TC
contiene millones de voxels (por ejemplo, 512 × 512 × 300 ≈ 78.6
millones), es imposible definir cada voxel como una celda individual.
MCNP6 resuelve este problema con **lattice arrays**: una grilla
tridimensional regular donde cada elemento es una celda que se repite
con diferentes materiales.

## Estrategia de geometría voxelizada

MCNP no soporta voxels nativamente, pero sí lattices:

```
                   ┌──────────────────────┐
                   │   Celda mundo (999)   │
                   │   RPP contenedor      │
                   │   FILL = universo 1   │
                   └──────────┬───────────┘
                              │
                   ┌──────────▼───────────┐
                   │   Celda lattice (1)  │
                   │   LAT=1              │
                   │   RPP = volumen      │
                   │   FILL = i:nx j:ny k:nz
                   └──────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        Celda voxel      Celda voxel      Celda voxel
        (100 n)          (100 n)          (100 n)
        LIKE 100 BUT     LIKE 100 BUT     LIKE 100 BUT
        MAT = material   MAT = material   MAT = material
```

### Arquitectura

1. **Celda mundo** (id 999): RPP que envuelve todo el volumen del
   paciente. Se rellena con el universo del lattice.

2. **Celda lattice** (id 1): Define una grilla LAT=1 con las
   dimensiones del volumen. Cada elemento de la grilla es una celda
   voxel.

3. **Celdas voxel** (ids 100+n): Una celda base definida con `LIKE n
   BUT` que se repite para cada material distinto en el volumen, con la
   tarjeta U (universo) para indicar que pertenece al lattice.

## Construcción paso a paso

### 1. Celda mundo (envolvente)

Se calculan las coordenadas extremas del volumen en LPS:

```python
x_min = -origin_x - espaciado_x * dim_x / 2
x_max = -origin_x + espaciado_x * dim_x / 2
y_min = -origin_y - espaciado_y * dim_y / 2
y_max = -origin_y + espaciado_y * dim_y / 2
z_min = origin_z - espaciado_z * dim_z / 2
z_max = origin_z + espaciado_z * dim_z / 2
```

```mcnp
999 0 -1000 $ Celda mundo (vacío exterior)
1000 RPP x_min x_max y_min y_max z_min z_max
```

### 2. Celda lattice

Usa el operador `LAT=1` (lattice hexagonal en este caso es LAT=2, pero
para voxels cúbicos se usa LAT=1 con grilla ortogonal):

```mcnp
1 0 -1000 U=1 LAT=1
    FILL=-nx:2*nx -ny:2*ny -nz:2*nz
    1:n_rev(ny*nz), 1:n_rev((ny-1)*nz), ..., 1:3, 1:2, 1:1
```

El rango del FILL se define con:

$$ i \in [0, n_x), \quad j \in [0, n_y), \quad k \in [0, n_z) $$

Y cada elemento del FILL contiene el número de universo de la celda
voxel correspondiente.

### 3. Celdas voxel con LIKE n BUT

`mcnp_geometry.py` genera celdas voxel usando `LIKE n BUT`:

```mcnp
100 1 -0.001205 U=1 $ Celda base: aire
     $ sin RPP — la celda se define por el lattice
101 LIKE 100 BUT MAT=2 $ Tejido blando
    RHO=1.06
102 LIKE 100 BUT MAT=3 $ Hígado
    RHO=1.05
...
```

Cada celda voxel única se define una sola vez. La matriz FILL del
lattice asigna qué celda (material) está en cada posición (i,j,k).

### 4. Compresión RLE

Para reducir el tamaño del archivo de entrada, el generador implementa
**Run-Length Encoding (RLE)** sobre el plano k:

```
Sin RLE:
    FILL=-1:1 -1:1 0:0
        100 101 102
        101 100 101
        102 101 100

Con RLE:
    En lugar de repetir 100, 100, 100, 100, 100 en voxels
    consecutivos del mismo material, se escribe:
    5R 100
```

La función `comprimir_rle(filas, n_cols)` en `mcnp_geometry.py` recorre
cada fila del plano k y reemplaza secuencias del mismo material por el
factor de repetición:

```python
def comprimir_rle(filas, n_cols):
    """Comprime una lista de índices de material usando RLE.
    
    Args:
        filas: lista de listas (cada sublista = una fila j)
        n_cols: número de columnas (nx)
    
    Returns:
        str: representación RLE del plano
    """
    resultado = []
    for fila in filas:
        count = 0
        prev = None
        linea = []
        for val in fila:
            if val == prev:
                count += 1
            else:
                if prev is not None:
                    if count == 1:
                        linea.append(str(prev))
                    else:
                        linea.append(f"{count}R {prev}")
                prev = val
                count = 1
        if count == 1:
            linea.append(str(prev))
        else:
            linea.append(f"{count}R {prev}")
        resultado.append(" ".join(linea))
    return "\n".join(resultado)
```

## Reorientación de ejes (flip_rows y flip_z)

Los flags `flip_rows` y `flip_z` controlan la orientación del volumen.

### flip_rows

Invierte el orden de las filas (eje j) en el lattice:

```
Sin flip:               Con flip:
j=0: material_A         j=ny-1: material_Z
j=1: material_B         j=ny-2: material_Y
j=2: material_C   ──►  j=ny-3: material_X
...                     ...
```

Esto corrige la diferencia entre el sistema de coordenadas RAS de Slicer
y LPS de MCNP:

$$ j_{MCNP} = (n_y - 1) - j_{RAS} $$

### flip_z

Invierte el orden de los slices (eje k):

```python
if flip_z:
    slices = slices[::-1]  # slice 0 pasa a ser el último
```

La transformación completa es:

$$ \begin{aligned}
i_{MCNP} &= i_{RAS} \\
j_{MCNP} &= \begin{cases} j_{RAS} & \text{si } \neg flip\_rows \\
                          (n_y - 1) - j_{RAS} & \text{si } flip\_rows \end{cases} \\
k_{MCNP} &= \begin{cases} k_{RAS} & \text{si } \neg flip\_z \\
                          (n_z - 1) - k_{RAS} & \text{si } flip\_z \end{cases}
\end{aligned} $$

## Debug geométrico

El generador incluye una rutina de depuración que escribe un archivo
`.debug_geom.txt` con:

- Dimensiones del volumen (nx, ny, nz)
- Espaciado (dx, dy, dz)
- Origen RAS
- Coordenadas RPP (x_min, x_max, y_min, y_max, z_min, z_max)
- Cantidad de materiales únicos
- Bandera flip_rows y flip_z

## Estructura completa en el .i

```
Celda mundo:
999 0 -1000        imp:p=1 imp:e=1
1000 RPP -150 150 -200 200 -300 0

Celda lattice:
1 0 -1000 u=1 lat=1
    fill=-5:2*5 -4:2*4 -3:2*3
    ...

Celdas voxel (6 + 53 materiales posibles):
100 1 -0.001205 u=1  $ Aire
101 2 -1.06     u=1  $ Tejido_blando  
102 3 -1.05     u=1  $ Higado
103 4 -0.50     u=1  $ Pulmon
104 5 -1.60     u=1  $ Hueso
105 6 -1.05     u=1  $ Tumor
106 7 -1.03     u=1  $ ICRP-110 primer material
...
153 54 -DENSIDAD u=1  $ ICRP-110 último material
```

## Consideraciones de rendimiento

| Factor | Impacto |
|--------|---------|
| Tamaño del .i | Lineal con n_voxels únicos (RLE reduce ~10×) |
| Tiempo de carga MCNP | Proporcional al tamaño del FILL |
| Memoria MCNP | 1–2 GB para volúmenes típicos (512³) |
| Velocidad de transporte | Independiente de la geometría (depende de materiales) |

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| RPP del lattice contiene todo el body | Voxels fuera del RPP |
| FILL tiene nx×ny×nz elementos | Cuenta incorrecta |
| Todos los materiales tienen celda U=1 | Falta celda voxel |
| RLE mantiene integridad de materiales | Suma de repeticiones ≠ nx×ny |
| flip_rows/flip_z consistentes con image_origin | Error de registro espacial |

## Referencias

- MCNP6 User's Manual, Ch. 3: Geometry, LA-UR-13-22934
- MCNP6 LATTICE Card, LA-CP-13-00634
- Solberg et al., "Lattice and voxel geometry in MCNP for medical
  physics applications", Nuclear Science and Engineering, 2001
