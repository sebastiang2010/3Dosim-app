# Tallies MCNP

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| TMESH | Tally MESH (grilla 3D de dosis en MCNP) |
| CORA/CORB/CORC | Coordinate Axis bins (ejes de la grilla TMESH) |
| DE4/DF4 | Dose Energy / Dose Function (conversión de fluencia a dosis) |
| *F8 | Pulse Height Tally (detector tipo pulso) |
| F6 | Energy Deposition Tally (energía depositada por gramo) |
| PEDEP | Particle Energy DEPosition |
| keV/g | Unidad de dosis en MCNP (kiloelectronvolt por gramo) |
| Gy | Gray (J/kg, unidad SI de dosis absorbida) |
| MeV/g | Mega-electronvolt por gramo |
| ROT | Rotation (transformación de coordenadas) |

## Contexto clínico

Las tallies (detectores) en MCNP son el mecanismo para estimar la dosis
absorbida en el paciente. 3Dosim utiliza tres tipos complementarios de
tallies:

- **TMESH rmesh1:e pedep**: grilla 3D de dosis para mapas de dosis
  volumétricos (el principal resultado clínico)
- ***F8**: detectores puntuales en órganos de interés (hígado, tumor,
  riñones) para dosis específicas por estructura
- **F6:e**: energía depositada total para verificación de conservación

## TMESH — Tally de grilla 3D

TMESH es un tally tipo 1 (fluencia) sobre una malla cartesiana que
cubre el volumen del paciente. La unidad es MeV/cm² (fluencia) que se
convierte a dosis usando coeficientes DE/DF.

### Definición en el input MCNP

```mcnp
TMESH
  RMESH1:PEDEP PEDEP
  CORA1  x_min  x_max  nx
  CORB1  y_min  y_max  ny
  CORC1  z_min  z_max  nz
  ENDSD
```

| Parámetro | Significado | Valor típico |
|-----------|-------------|:------------:|
| `x_min`, `x_max` | Límites de la grilla en X (mm) | −150 a 150 |
| `y_min`, `y_max` | Límites de la grilla en Y (mm) | −200 a 200 |
| `z_min`, `z_max` | Límites de la grilla en Z (mm) | −300 a 0 |
| `nx`, `ny`, `nz` | Número de intervalos en cada eje | 128 a 256 |

### BUG CORREGIDO — TMESH nx vs nx-1

Versiones anteriores del generador usaban:

```mcnp
CORA1 x_min x_max nx i  $ INCORRECTO — nx intervalos, nx+1 valores
```

La corrección cambió a:

```mcnp
CORA1 x_min x_max nx  $ CORRECTO — MCNP espera nx intervalos
```

Ver issue interno: `TMESH_CORA_FIX_2024`.

### Conversión de fluencia a dosis (DE4/DF4)

El tally `RMESH1:PEDEP` usa un par DE4/DF4 para convertir fluencia de
electrones (MeV/cm²) a dosis (MeV/g):

```mcnp
DE4  0.001 0.003 0.01 0.03 0.1 0.3 1.0 2.0 3.0 5.0 10.0
DF4  1.0   1.0   1.0  1.0  1.0 1.0 1.0 1.0 1.0 1.0 1.0
```

La conversión se hace con coeficientes precalculados para tejido:

$$ H(E) = \frac{\mu_{en}(E)}{\rho} \cdot \Phi(E) \cdot E $$

| Símbolo | Significado |
|---------|-------------|
| $H(E)$ | Dosis en energía $E$ |
| $\mu_{en}(E)/\rho$ | Coeficiente másico de absorción de energía |
| $\Phi(E)$ | Fluencia de partículas en energía $E$ |
| $E$ | Energía de la partícula |

Los 11 puntos de la DE4/DF4 cubren el rango 0.001–10.0 MeV.

### Post-processamiento

Después de MCNP, la dosis en MeV/g se convierte a Gy:

$$ D_{Gy} = D_{MeV/g} \cdot \frac{1.602176634 \times 10^{-13}\ \text{J/MeV}}{10^{-3}\ \text{kg/g}} $$

$$ D_{Gy} = D_{MeV/g} \times 1.602176634 \times 10^{-10} $$

El archivo de resultados TMESH se parsea en el Módulo 3 para generar
el volume node DICOM de dosis.

## *F8 — Detectores puntuales por órgano

Los tallies *F8 (pulse height) proporcionan el espectro de energía
depositada en una celda. 3Dosim define un *F8 para cada VOI:

```mcnp
*F8:P  liver_det $ Tally F8 en hígado
*F18:P tumor_det $ Tally F8 en tumor
*F28:P kidney_l  $ Tally F8 en riñón izquierdo
*F38:P kidney_r  $ Tally F8 en riñón derecho
```

Cada detector *F8 se asocia a una celda específica que contiene los
voxels del órgano correspondiente.

### Ventajas del *F8

- Entrega dosis por evento individual (espectro de energía depositada)
- Permite calcular la fracción de energía depositada localmente
- Útil para validación contra modelos analíticos (MIRD)

### Incertidumbre estadística

La desviación estándar relativa (RSD) para *F8:

$$ RSD = \frac{1}{\sqrt{N_{eventos}}} $$

Para alcanzar RSD < 5% se necesitan aproximadamente:

$$ N_{eventos} > \left(\frac{1}{0.05}\right)^2 = 400 $$

## F6:e — Energía depositada total

El tally F6 mide la energía depositada por unidad de masa (MeV/g) en
una celda:

```mcnp
F6:P  body_cell $ Energía depositada en todo el paciente
```

Se usa como verificación de conservación:

$$ E_{depositada}^{F6} \approx E_{emitida}^{SDEF} $$

## Tarjetas de corte (CUT)

Controlan el tiempo máximo de simulación de cada partícula:

```mcnp
CUT:P 1e10    $ Corte para fotones (1e10 shakes ≈ 100 ms)
CUT:E 1e10    $ Corte para electrones
```

Las tarjetas CUT evitan la simulación infinita de partículas de muy
baja energía que no contribuyen significativamente a la dosis.

## Conversión de unidades

| Unidad MCNP | Unidad SI | Factor |
|:-----------:|:---------:|:------:|
| MeV/g | Gy | $1.602176634 \times 10^{-10}$ |
| MeV/cm² | — | (fluencia, se multiplica por $\mu_{en}/\rho$) |
| shakes | s | $10^{-8}$ |

## Resumen de tallies

| Tally | ID | Tipo | Propósito |
|-------|:--:|:----:|-----------|
| RMESH1:PEDEP | 1 | Grilla 3D | Mapa de dosis volumétrico |
| DE4/DF4 | 4 | Conversión | Fluencia → dosis (11 puntos) |
| *F8:P | 8 | Puntual | Dosis en órgano específico |
| *F18:P | 18 | Puntual | Dosis en tumor |
| *F28:P | 28 | Puntual | Dosis en riñón izquierdo |
| *F38:P | 38 | Puntual | Dosis en riñón derecho |
| F6:P | 6 | Volumétrica | Energía depositada total |

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| TMESH cubre todo el volumen RPP | Rango TMESH < RPP |
| CORA/CORB/CORC definidos | Falta alguno de los 3 ejes |
| nx, ny, nz en COR son enteros > 0 | nx ≤ 0 o no entero |
| DE4/DF4 tienen 11 puntos cada uno | Distinta cantidad de puntos |
| *F8 asocia celda existente | Celda del detector no definida |
| CUT:P y CUT:E presentes | Modo P o E sin CUT |
| F6 activo para body_cell | Celda body_cell no definida |
| ENDSD cierra TMESH | Falta ENDSD |

## Mapeo de resultados TMESH al volumen DICOM

Después de ejecutar MCNP, el archivo de salida MCTAL contiene los
resultados de RMESH1:PEDEP. El Módulo 3 (post-procesamiento) parsea
este archivo y reconstruye un volume node DICOM de dosis.

### Formato del MCTAL para TMESH

```
tally     1    rmesh1:p    pedep
 ...
  energy bin:   1
  tfc     nps  ...     8.70E-05  ...
  results for cora  1  ...  values follow
  corb  1
   5.12E-05  4.89E-05  5.01E-05  ...
  corb  2
   4.95E-05  5.22E-05  5.10E-05  ...
```

### Reconstrucción del volumen de dosis

```python
def parse_tmesh_to_volume(mctal_path, dims):
    """Parsea el archivo MCTAL y reconstruye volumen de dosis.
    
    Args:
        mctal_path: ruta al archivo MCTAL de MCNP
        dims: tupla (nx, ny, nz) del volumen original
    
    Returns:
        ndarray (nz, ny, nx) con dosis en MeV/g
    """
    # 1. Extraer bloque RMESH1 del MCTAL
    # 2. Leer valores en orden CORA→CORB→CORC
    # 3. Reorganizar a (nz, ny, nx)
    # 4. Convertir MeV/g → Gy
    dose_gy = dose_mev_per_g * 1.602176634e-10
    return dose_gy
```

### Regridding a dimensiones del volumen

Si las dimensiones de TMESH (nx, ny, nz) no coinciden exactamente con
las del labelmap (por ejemplo, TMESH usa 128³ mientras el volumen es
512×512×300), se realiza un remuestreo trilineal:

$$ D_{voxel}(i,j,k) = \sum_{p,q,r} w_{pqr} \cdot D_{TMESH}(i_p, j_q, k_r) $$

Donde $w_{pqr}$ son los pesos de interpolación trilineal entre los 8
vértices del cubo TMESH que rodean al voxel.

## Verificación de conservación de energía

Un chequeo de calidad crítico es verificar que la energía total
depositada coincida con la energía total emitida:

$$ E_{emitida} = N_{partículas} \times \bar{E}_{\beta} $$
$$ E_{depositada} = \sum_{voxels} D_{voxel} \times \rho_{voxel} \times V_{voxel} $$
$$ \text{Ratio} = \frac{E_{depositada}}{E_{emitida}} \approx 1.0 $$

| Símbolo | Significado |
|---------|-------------|
| $E_{emitida}$ | Energía total emitida por la fuente |
| $E_{depositada}$ | Energía total depositada en el volumen |
| $\bar{E}_{\beta}$ | Energía media del espectro beta |
| $V_{voxel}$ | Volumen de un voxel ($dx \cdot dy \cdot dz$) |

El ratio debe estar entre 0.95 y 1.05. Valores fuera de este rango
indican problemas en la geometría, materiales o fuente.

## Conversión de unidades para reporte clínico

| Paso | Operación | Resultado |
|------|-----------|-----------|
| MCNP raw | RMESH1:PEDEP | MeV/g |
| Convertir a Gy | × 1.602176634e-10 | Gy |
| Acumular por VOI | Suma sobre máscara del órgano | Gy/organ |
| Dosis等效 (EQD2) | $D \times \frac{d + \alpha/\beta}{2 + \alpha/\beta}$ | Gy₂ |
| BED | $D \times (1 + \frac{d}{\alpha/\beta})$ | Gy |

## Referencias

- MCNP6 User's Manual, Ch. 5: Tallies, LA-UR-13-22934
- MCNP6 TMESH Card, LA-CP-14-00745
- Shultis & Faw, "An MCNP Primer", Kansas State University, 2011
- ICRU Report 56: Dosimetry of External Beta Rays for Radiation
  Protection, 1997
