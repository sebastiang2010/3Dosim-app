# Lectura de Actividad PET desde DICOM Raw

> **Replicando la función MATLAB `f_Rescale_Bq.m`.** La actividad del paciente medida por PET post-infusión es el factor escalar que convierte la energía depositada por partícula simulada en dosis absorbida real en Gray. Este documento describe cómo se lee la actividad desde los archivos DICOM PET raw, slice por slice, usando `pydicom`.

## Acrónimos

| Acrónimo | Significado |
|----------|-------------|
| PET | Positron Emission Tomography |
| DICOM | Digital Imaging and Communications in Medicine |
| BQML | Becquerel per Milliliter (unidad de actividad PET) |
| SUV | Standardized Uptake Value |
| GBq | Gigabecquerel ($$10^9$$ Bq) |
| mCi | miliCurie (1 mCi = 37 MBq) |
| CLUT | Color Look-Up Table |
| RescaleSlope | Factor de escala lineal DICOM |
| RescaleIntercept | Intercepción lineal DICOM |

---

## 1. Contexto Clínico

La actividad medida por PET es la **fuente real de radiación** en el paciente. En radioembolización con $$^{90}$$Y, la distribución de microesferas se visualiza mediante PET post-infusión. Cada voxel contiene una concentración de actividad en Bq/mL que debe integrarse sobre el volumen para obtener la actividad total en Bq.

La lectura directa de los archivos DICOM PET raw es necesaria porque:

1. **Slicer ya aplica RescaleSlope/Intercept** al cargar, pero no necesariamente por slice
2. **El MATLAB legacy (`f_Rescale_Bq.m`) lee slice por slice** con `pydicom`
3. **La unidad puede variar**: BQML (correcto) vs. otros modos (SUV, USCAL)
4. **La actividad total** se necesita para el diálogo de fusión y los cálculos MIRD

---

## 2. Fórmula de Conversión por Voxel

Para cada slice $$k$$ de la PET:

$$A_{\text{vox}}^{(k)}(i,j) = P_{\text{raw}}^{(k)}(i,j) \cdot m_k + b_k$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$A_{\text{vox}}^{(k)}(i,j)$$ | Actividad en el voxel (i,j) del slice k | Bq/mL |
| $$P_{\text{raw}}^{(k)}(i,j)$$ | Valor crudo DICOM (pixel_array) del slice k | adimensional |
| $$m_k$$ | `RescaleSlope` del slice k | (Bq/mL)/unidad |
| $$b_k$$ | `RescaleIntercept` del slice k | Bq/mL |

### 2.1 Verificación de Unidades

Solo se aplica la conversión si `RescaleType == 'BQML'`:

```python
if rescale_type.upper() != 'BQML':
    log.warning(f"Slice {k}: RescaleType = {rescale_type}, no BQML. "
                f"Actividad puede ser incorrecta.")
```

### 2.2 Conversión mm³ → cm³

Si el espaciado del PET está en milímetros cúbicos (mm³), la actividad por voxel debe convertirse a cm³:

$$A_{\text{vox}}^{(k)}(i,j)_{\text{cm}^3} = A_{\text{vox}}^{(k)}(i,j)_{\text{mm}^3} \times \frac{1\ \text{cm}^3}{1000\ \text{mm}^3}$$

### 2.3 Actividad Total

$$A_{\text{total}} = \sum_{k=1}^{N_s} \sum_{i=1}^{N_x} \sum_{j=1}^{N_y} A_{\text{vox}}^{(k)}(i,j) \cdot V_{\text{vox}}$$

| Variable | Descripción | Unidad |
|----------|-------------|--------|
| $$A_{\text{total}}$$ | Actividad total del paciente | Bq |
| $$V_{\text{vox}}$$ | Volumen de un voxel PET | cm³ |
| $$N_s$$ | Número de slices PET | — |
| $$N_x, N_y$$ | Dimensiones del slice PET | — |

---

## 3. Implementación

### 3.1 Algoritmo

```
1. Listar archivos DICOM PET del directorio (orden por InstanceNumber)
2. Para cada slice k:
   a. Leer con pydicom.dcmread()
   b. Obtener RescaleSlope (m_k), RescaleIntercept (b_k), RescaleType
   c. Verificar RescaleType == 'BQML'
   d. Obtener pixel_array
   e. Aplicar: actividad_vox = pixel_array * m_k + b_k
   f. Si espaciado en mm³, dividir por 1000
3. Acumular actividad_vox en array 3D (z, y, x)
4. Calcular actividad_total = sum(actividad_3d) * volumen_voxel
5. Reportar en Bq, GBq, mCi, Bq/mL
```

### 3.2 Código Python

```python
import pydicom
import numpy as np
import os

def read_pet_activity(pet_dir: str, spacing_mm: tuple = None):
    """
    Lee actividad PET desde DICOM raw replicando MATLAB f_Rescale_Bq.m.

    Parameters
    ----------
    pet_dir : str
        Directorio con archivos DICOM PET.
    spacing_mm : tuple, optional
        Espaciado del PET en mm (sx, sy, sz). Si no se provee,
        se lee del primer archivo DICOM.

    Returns
    -------
    activity_3d : np.ndarray
        Actividad por voxel en Bq/cm³, shape (Nz, Ny, Nx).
    total_bq : float
        Actividad total en Bq.
    total_gbq : float
        Actividad total en GBq.
    stats : dict
        Estadísticas: mean, max, min Bq/mL.
    """

    dicom_files = sorted(
        [f for f in os.listdir(pet_dir) if f.endswith('.dcm')],
        key=lambda f: int(pydicom.dcmread(
            os.path.join(pet_dir, f), specific_tags=['InstanceNumber']
        ).InstanceNumber)
    )

    slices = []
    first = pydicom.dcmread(os.path.join(pet_dir, dicom_files[0]))

    for fname in dicom_files:
        ds = pydicom.dcmread(os.path.join(pet_dir, fname))
        m = float(ds.RescaleSlope) if hasattr(ds, 'RescaleSlope') else 1.0
        b = float(ds.RescaleIntercept) if hasattr(ds, 'RescaleIntercept') else 0.0
        rtype = ds.RescaleType if hasattr(ds, 'RescaleType') else ''

        if rtype.upper() != 'BQML':
            print(f"WARNING: {fname}: RescaleType={rtype}, no BQML")

        pixel = ds.pixel_array.astype(np.float64)
        activity_slice = pixel * m + b
        slices.append(activity_slice)

    activity_3d = np.stack(slices, axis=0).astype(np.float32)

    if spacing_mm is None:
        pix = first.PixelSpacing
        spacing_mm = (float(pix[0]), float(pix[1]), float(first.SliceThickness))

    vox_vol_mm3 = spacing_mm[0] * spacing_mm[1] * spacing_mm[2]
    vox_vol_cm3 = vox_vol_mm3 / 1000.0

    total_bq = float(np.sum(activity_3d) * vox_vol_cm3)
    total_gbq = total_bq / 1e9
    total_mci = total_bq / 37e6

    stats = {
        'mean_bqml': float(np.mean(activity_3d)),
        'max_bqml': float(np.max(activity_3d)),
        'min_bqml': float(np.min(activity_3d)),
        'total_mci': total_mci,
        'vox_vol_cm3': vox_vol_cm3,
    }

    return activity_3d, total_bq, total_gbq, stats
```

---

## 4. Rangos Normales de Actividad

| Parámetro | Rango típico | Unidad | Notas |
|-----------|:------------:|:------:|-------|
| Actividad total | 1.0 – 5.0 | GBq | Radioembolización Y-90 |
| Actividad total | 27 – 135 | mCi | Conversión: 1 mCi = 37 MBq |
| Concentración media | 0.1 – 50 | kBq/mL | Depende del volumen hepático |
| Actividad en tumor | 2 – 10× | hígado sano | T/N ratio típico |
| Voxeles activos | > 100 | — | Para estadística válida |

### 4.1 Fuera de Rango

| Condición | Acción |
|-----------|--------|
| Actividad total ≤ 0 Bq | **Error**: detener pipeline |
| < 0.1 GBq | **Warning**: actividad muy baja para Y-90 |
| > 50 GBq | **Warning**: actividad extremadamente alta |
| Voxeles activos ≤ 100 | **Warning**: PET con muy poca señal |

---

## 5. Fallback: Actividad por CLI

Si no hay PET disponible (p. ej., el estudio no incluye PET post-infusión), la actividad se acepta por línea de comandos:

```bash
python pipeline_mod3.py --scene escena.mrb --activity 3.5  # 3.5 GBq
```

En este caso:

$$A_{\text{vox}} = \frac{A_{\text{CLI}}}{N_{\text{voxeles en ROI}}}$$

Distribución uniforme sobre los voxeles del hígado + tumor.

---

## 6. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo |
|-------------|-------------------|
| RescaleType = BQML | Cualquier slice con tipo diferente |
| Actividad total > 0 | Suma total ≤ 0 Bq |
| Actividad en rango 0.1 – 50 GBq | Fuera de rango (warning) |
| Coherencia con peso paciente | Actividad/kg fuera de 0.01 – 0.1 GBq/kg |
| Número de archivos DICOM | Menos de 10 slices (estadística insuficiente) |
| Dimensiones consistentes | Distinto tamaño entre slices |
| Valores NaN o Inf presentes | Cualquier voxel con NaN o Inf |
| Contraste tumor/hígado | T/N < 1.5 (poco contraste) |

---

## 7. Referencias

- DICOM Standard PS3.3: Nuclear Medicine Image Module (C.8.9)
- Gulec et al., "Hepatic Radioembolization with Y-90 Microspheres", Semin Nucl Med 2008
- MATLAB `f_Rescale_Bq.m` de 3Dosim v3.14 (legacy `modulo_3/`)
- `pet_dicom_reader.py` en `PipelineOrchestrator/`
