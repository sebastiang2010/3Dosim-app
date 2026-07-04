# Parsing de Archivo MCTAL de MCNP

> **Extrayendo energía depositada desde el output ASCII de MCNP6.** El archivo MCTAL contiene los resultados de las tallies (detectores) de la simulación Monte Carlo. En 3Dosim, el tally de interés es el `tally 1` (TMESH o *F8), que registra la energía depositada por partícula fuente en MeV/cm³.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| MCTAL | Archivo de resultados de MCNP (ASCII o binario) |
| TMESH | Tally MESH (grilla de dosis 3D en MCNP) |
| F8 | Tally de energía depositada en un detector |
| F6 | Tally de energía depositada en una celda |
| NPS | Number of Particle Source (historias simuladas) |
| RSE | Relative Statistical Error |
| LANL | Los Alamos National Laboratory (creador de MCNP) |
| TFC | Tally Fluctuation Chart (estadísticas en MCTAL) |

---

## 1. Contexto

MCNP6 escribe los resultados de las tallies en un archivo de salida llamado por defecto `OUTPUT`, pero con extensión `.o` o en formato MCTAL (especificado con `PRINT`). El formato MCTAL es un **formato ASCII estructurado** que MCNP usa para comunicar resultados a programas externos.

Cada tally en MCTAL contiene:

1. **Cabecera**: tipo de tally, partículas, número de bins
2. **Dimensiones**: tamaño de cada eje de la grilla
3. **Boundaries**: coordenadas de cada bin en el espacio
4. **Valores**: pares (resultado, error relativo) para cada bin en orden **column-major Fortran**

---

## 2. Estructura del Archivo MCTAL

```
 tally type n    (1 = tally 1)
   particles = p  (photons)
   ...

 tally 1
   ...
   energy
   ...   (optional energy bins)
   
   segment 1
     ...
     
   segment 2
     ...
   
   vals
       1.2345E-03  0.0123   2.3456E-03  0.0156   ...
       3.4567E-03  0.0189   ...
```

### 2.1 Palabras Clave Buscadas

| Palabra clave | Propósito |
|---------------|-----------|
| `tally 1` | Identificar el tally de energía depositada |
| `segment 1` | Identificar el primer segmento (único para FMESH4) |
| `vals` | Inicio de los datos numéricos |
| `energy` | Rango de energía (si hay bins de energía) |
| `values follow` | Formato alternativo de datos |

---

## 3. Formato de Datos

Los datos en `vals` vienen como **pares (valor, error)** en punto flotante:

```
vals
   v1 e1  v2 e2  v3 e3  v4 e4  ...
   v5 e5  v6 e6  v7 e7  v8 e8  ...
```

| Elemento | Descripción | Unidad |
|----------|-------------|--------|
| $$v_i$$ | Energía depositada por partícula fuente | MeV/cm³ |
| $$e_i$$ | Error relativo (RSE = $$\sigma / \mu$$) | adimensional |

### 3.1 Reshape Column-Major (Fortran)

MCNP escribe los valores en **orden column-major** (Fortran): el primer índice varía más rápido.

Si la grilla TMESH tiene dimensiones `[nx, ny, nz]`:

```python
# Leer como vector plano (column-major Fortran)
vals_flat = np.array([v1, v2, v3, ...])

# Reshape: Fortran order
vals_3d_fortran = vals_flat.reshape([ny, nx, nz], order='F')

# Transponer a orden RAS (Row-major): [nx, ny, nz]
vals_3d = np.transpose(vals_3d_fortran, [1, 0, 2])
```

```
Datos crudos MCTAL:  v1 v2 v3 v4 v5 v6 v7 v8 ...
                           │
                           ▼
                reshape(order='F', shape=[ny,nx,nz])
                           │
                    ┌──────┴──────┐
                    │ Fortran:     │
                    │ [0,0,0] = v1 │
                    │ [1,0,0] = v2 │
                    │ [0,1,0] = v3 │
                    └──────┬──────┘
                           ▼
                transpose([1,0,2])
                           │
                    ┌──────┴──────┐
                    │ Row-major:   │
                    │ [0,0,0] = v1 │
                    │ [1,0,0] = v3 │
                    │ [0,1,0] = v2 │
                    └─────────────┘
```

---

## 4. Algoritmo de Parsing

```
1. Abrir archivo MCTAL en modo texto
2. Buscar línea que contenga "tally 1" (case-insensitive)
3. Leer dimensiones:
   a. Buscar "nx", "ny", "nz" o patrón "tally"
   b. Extraer nx, ny, nz de la línea de dimensiones
4. Leer boundaries:
   a. Buscar "x   axis" -> nx+1 valores
   b. Buscar "y   axis" -> ny+1 valores
   c. Buscar "z   axis" -> nz+1 valores
5. Buscar "vals"
6. Leer pares (valor, error) hasta agotar nx*ny*nz pares:
   - Repetir líneas hasta completar el total de bins
   - Cada línea contiene N pares (valor, error)
7. Separar vectores de valor y error
8. Aplicar reshape column-major + transpose
9. Aplicar filtros de calidad
```

---

## 5. Filtros de Calidad Post-Parsing

### 5.1 Error Relativo ≥ 1.5

Voxeles con $$e_i \geq 1.5$$ se consideran **no estadísticamente significativos** y su dosis se anula a 0:

```python
dosis_filtered[dosis_filtered >= 1.5] = 0.0
```

### 5.2 Dosis Negativa

Por fluctuaciones estadísticas, algunos valores pueden ser negativos (especialmente en zonas de muy baja dosis). Se convierten a 0:

```python
dosis[dosis < 0] = 0.0
```

### 5.3 Voxeles de Aire

Los voxeles marcados como aire (índice de tejido = 1) en la labelmap deben tener dosis = 0:

```python
dosis[air_mask] = 0.0
```

### 5.4 Tabla de Filtros

| Filtro | Condición | Valor asignado | Porcentaje típico afectado |
|--------|-----------|:--------------:|:--------------------------:|
| Error ≥ 1.5 | $$e_i \geq 1.5$$ | 0 Gy | < 2% voxeles |
| Dosis negativa | $$v_i < 0$$ | 0 Gy | < 1% voxeles |
| Aire | labelmap == 1 | 0 Gy | ~30–50% voxeles (exterior) |

---

## 6. Implementación

### 6.1 MCTALParser en SlicerDosimLib

La clase `MCTALParser` en `mctal_parser.py` expone la API pública:

```python
class MCTALParser:
    """
    Parser de archivos MCTAL de MCNP.

    Parameters
    ----------
    mctal_path : str
        Ruta al archivo MCTAL (.o o .mctal)
    """

    def parse(self) -> dict:
        """
        Parsear archivo MCTAL completo.

        Returns
        -------
        dict con:
            - 'dose_raw': np.ndarray [nx,ny,nz] — energía depositada MeV/cm³
            - 'error': np.ndarray [nx,ny,nz] — error relativo
            - 'dimensions': tuple (nx, ny, nz)
            - 'boundaries': dict con x, y, z arrays
            - 'filtered_count': int — voxeles anulados por filtros
            - 'metadata': dict — NPS, tally type, etc.
        """

    def get_dose_gy(self, activity_bq: float,
                    density_map: np.ndarray) -> np.ndarray:
        """
        Convertir directamente a Gy (delega a dosimetry.py).
        """
```

### 6.2 Ejemplo de Uso

```python
from mctal_parser import MCTALParser

parser = MCTALParser("resultados_test/mcnp/paciente.o")
result = parser.parse()

print(f"Dimensiones: {result['dimensions']}")
print(f"Voxeles filtrados: {result['filtered_count']}")
print(f"Dosis raw media: {np.mean(result['dose_raw']):.4e} MeV/cm³")
print(f"Error medio: {np.mean(result['error']):.4f}")
```

---

## 7. Validación contra MATLAB

| Métrica | MATLAB | Python | Tolerancia |
|---------|:------:|:------:|:----------:|
| dtype después de reshape | float64 | float32 | — |
| Orden de datos | Fortran → transpose | Fortran → transpose | Idéntico |
| Filtro error ≥ 1.5 | `error >= 1.5` | `error >= 1.5` | Idéntico |
| Filtro negativo | `< 0 → 0` | `< 0 → 0` | Idéntico |
| Filtro aire | `air → 0` | `air → 0` | Idéntico |

---

## 8. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| Tally 1 encontrado | No existe tally 1 en el archivo |
| Dimensiones nx, ny, nz > 0 | Cualquier dimensión ≤ 0 |
| Coincidencia con labelmap | Dimensiones MCTAL ≠ dimensiones labelmap |
| Pares valor/error completos | Faltan pares (nx × ny × nz esperados) |
| Error medio < 0.5 | Error medio ≥ 0.5 (mala estadística) |
| Filtrados < 5% del total | Más de 5% filtrados |
| Voxeles activos > 0 | Suma total de dosis = 0 |
| Parsing time < 30 s | Timeout |

---

## 9. Referencias

- MCNP6 User's Manual, LA-UR-13-22934, Chapter 6: Tallies
- MCNP6 Output Guide: MCTAL File Format
- `mctal_parser.py` en `SlicerDosimLib/`
- MATLAB legacy: `modulo_3/lee_MCTAL_Y90.m`
