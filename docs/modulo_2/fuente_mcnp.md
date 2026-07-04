# Definición de Fuente (Source)

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| SDEF | Source Definition (tarjeta MCNP para definir la fuente) |
| WGT | Weight (peso de la partícula) |
| ERG | Energy (energía de emisión) |
| POS | Position (posición de la fuente) |
| TME | Time (tiempo de emisión) |
| .src | Archivo externo con posiciones de fuente |
| XS | Cross Section (sección eficaz) |
| PDF | Probability Density Function |
| CDF | Cumulative Distribution Function |
| ACE | A Compact ENDF (formato de datos nucleares) |

## Contexto clínico

En dosimetría de radionúclidos, la fuente de radiación está distribuida
en el volumen del paciente (no es un haz externo). El $^{90}$Y, $^{177}$Lu
o $^{131}$I se administra al paciente y se acumula selectivamente en
tejidos (hígado para SIRT, tumores, etc.). La fuente MCNP debe
representar esta distribución volumétrica con la energía espectral
correcta.

## Estrategia de definición de fuente

MCNP ofrece dos estrategias para fuentes distribuidas:

1. **Definición inline** con SDEF + distribuciones SI/SP
2. **Archivo externo** con posiciones muestradas desde la actividad

3Dosim usa ambas: SDEF define el espectro y las probabilidades, mientras
que el archivo `.src` contiene las posiciones de emisión muestreadas
desde la distribución de actividad.

## Espectro de energías

### Y-90 ($^{90}$Y)

El $^{90}$Y decae por emisión beta pura a $^{90}$Zr (estable). El
espectro continuo tiene energía máxima:

$$ E_{\beta,\text{max}}^{^{90}\text{Y}} = 2.28\ \text{MeV} $$

Energía media:

$$ \bar{E}_\beta = \frac{1}{3} E_{\beta,\text{max}} \approx 0.935\ \text{MeV} $$

El espectro se modela con 2 grupos de energía en `mcnp_source.py`:

```python
Y90_SPECTRUM = {
    "groups": 2,
    "energies": [0.0, 0.5, 2.28],  # MeV, límites de bins
    "probabilities": [0.3, 0.7],    # fracción de partículas en cada bin
}
```

La función de densidad de probabilidad (PDF) del espectro beta
teórico de Fermi:

$$ \frac{dN}{dE} = C \cdot F(Z, E) \cdot p \cdot E \cdot (E_{\max} - E)^2 $$

| Símbolo | Significado |
|---------|-------------|
| $C$ | Constante de normalización |
| $F(Z, E)$ | Función de Fermi (corrección coulombiana) |
| $p$ | Momento del electrón ($p = \sqrt{E^2 - m_e^2 c^4}$) |
| $E$ | Energía cinética del electrón |
| $E_{\max}$ | Energía máxima ($^{90}$Y: 2.28 MeV) |
| $Z$ | Número atómico del núcleo hijo ($^{90}$Zr, Z=40) |

### Lu-177 ($^{177}$Lu)

El $^{177}$Lu emite electrones de conversión y beta con energías
medias más bajas:

| Grupo | Rango (MeV) | Probabilidad |
|-------|:-----------:|:------------:|
| 1 | 0.0 – 0.2 | 0.15 |
| 2 | 0.2 – 0.5 | 0.60 |
| 3 | 0.5 – 0.8 | 0.25 |

### I-131 ($^{131}$I)

El $^{131}$I tiene emisiones beta y gamma. Se modela con ambos modos:

| Partícula | Energía | Modo MCNP | Probabilidad |
|-----------|:-------:|:---------:|:------------:|
| e− | 0.0–0.6 MeV | P | 0.90 |
| γ | 0.364 MeV | E | 0.10 |

## Tarjeta SDEF

La tarjeta SDEF generada tiene la forma:

```mcnp
SDEF POS=0 0 0 ERG=D1 WGT=1 PAR=P
SI1 L 0.25 1.39     $ energías discretas (centroides de grupo)
SP1 0.3 0.7         $ probabilidades
```

Cuando se usa archivo .src externo, se reemplaza POS y ERG por:

```mcnp
SDEF POS=FPOS=<x> <y> <z> ERG=D1 WGT=<actividad>
SI1 L 0.50 1.50
SP1 0.3 0.7
```

Donde `<x>`, `<y>`, `<z>` y `<actividad>` se leen del archivo .src.

## Archivo de fuente externo (.src)

Para fuentes distribuidas, el generador produce un archivo de texto
donde cada línea contiene las coordenadas de emisión de una partícula:

```
# Archivo de fuente 3Dosim
# Isótopo: Y90
# N partículas: 1000000
# Formato: x(mm) y(mm) z(mm) energía(MeV) peso
-45.2 30.1 -12.5 0.93 1.0
-44.8 29.7 -12.1 1.45 1.0
...
```

### Muestreo espacial

Las posiciones se muestrean uniformemente dentro del volumen del tumor
(o del hígado completo, según la configuración):

```python
def sample_positions_in_voi(voi_mesh, n_particles):
    """Muestrea posiciones dentro de un VOI.
    
    Args:
        voi_mesh: malla VTK del volumen de interés
        n_particles: número de partículas a muestrear
    
    Returns:
        array(n_particles, 3): coordenadas (x, y, z) en LPS
    """
    positions = []
    bbox = voi_mesh.GetBounds()
    
    for _ in range(n_particles):
        # Muestreo por rechazo dentro del bounding box
        while True:
            x = uniform(bbox[0], bbox[1])
            y = uniform(bbox[2], bbox[3])
            z = uniform(bbox[4], bbox[5])
            if point_in_mesh(x, y, z, voi_mesh):
                positions.append([x, y, z])
                break
    
    return array(positions)
```

### Distribución uniforme en voxels

Cuando no se dispone de una malla VOI, el generador distribuye las
partículas uniformemente sobre los voxels del labelmap que corresponden
al tumor:

```python
def sample_positions_in_labelmap(labelmap, tumor_index=100, n_particles=1e6):
    """Muestrea posiciones uniformes en voxels tumorales."""
    mask = labelmap == tumor_index
    voxel_indices = argwhere(mask)
    n_voxels = len(voxel_indices)
    
    # Seleccionar voxels aleatorios
    selected = voxel_indices[randint(0, n_voxels, n_particles)]
    
    # Agregar desplazamiento aleatorio intra-voxel
    positions = selected + uniform(-0.5, 0.5, selected.shape)
    return positions * espaciado + origen_lps
```

## Actividad y peso

El peso de cada partícula (WGT) representa su fracción de la actividad
total:

$$ WGT_i = \frac{A_{total}}{N_{partículas}} $$

| Símbolo | Significado | Unidad |
|---------|-------------|--------|
| $A_{total}$ | Actividad administrada | Bq |
| $WGT_i$ | Peso de la partícula $i$ | Bq/historia |

Para MCNP, el peso se normaliza para que la suma de todos los pesos
sea 1.0 (cada historia representa una partícula), y la actividad se
especifica como normalización post-proceso:

$$ \dot{D} = \frac{A_{total}}{N_{partículas}} \cdot \sum_{i=1}^{N} D_i $$

donde $D_i$ es la dosis estimada por la historia $i$.

## Tarjetas relacionadas

### CUT (corte de historia)

```mcnp
CUT:P 1e10    $ Corte de tiempo para fotones
CUT:E 1e10    $ Corte de tiempo para electrones
```

### MODE (modo de transporte)

```mcnp
MODE P E      $ Transportar fotones y electrones
```

### PHYS (física)

```mcnp
PHYS:E 1 0 0 0 1 0  $ Habilitar creación de e- secundarios
                     $ (estándar para dosimetría)
```

## Resumen de parámetros de fuente

| Parámetro | Valor típico | Dependencia |
|-----------|:------------:|-------------|
| Isótopo | Y90 / Lu177 / I131 | Input del usuario |
| N partículas | 1×10⁶ a 1×10⁷ | Exactitud deseada |
| Actividad | 0.5–5 GBq (Y90 SIRT) | Informe médico |
| Energía media | 0.935 MeV (Y90) | Isótopo |
| Alcance medio β | 2.5 mm (Y90 en tejido) | Isótopo + densidad |
| Volumen fuente | Tumor / Hígado | Segmentación |

## AI Supervisor

| Verificación | Condición de fallo |
|-------------|-------------------|
| Espectro definido para el isótopo | Falta entrada en SPECTRA dict |
| Archivo .src generado (si aplica) | No existe o 0 partículas |
| SDEF tiene ERG y WGT consistentes | Mismatch entre parámetros |
| Peso suma ≈ 1.0 | |Σ WGT − 1| > 0.01 |
| Partículas dentro del VOI | Coordenadas fuera de la malla |
| MODE coincide con la partícula | Modo P sin electrones para beta |

## Referencias

- MCNP6 User's Manual, Ch. 4: Source Definition, LA-UR-13-22934
- Eckerman et al., "Nuclear Decay Data for Dosimetric Calculations",
  ICRP Publication 107, Ann. ICRP 38(3), 2008
- Loevinger et al., "MIRD Primer for Absorbed Dose Calculations",
  Society of Nuclear Medicine, 1988
- ICRU Report 56: Dosimetry of External Beta Rays for Radiation
  Protection, 1997
