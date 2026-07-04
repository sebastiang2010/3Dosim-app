# Calibración PET a Bq/mL

> **El PET DICOM almacena valores crudos (cuentas detectadas) que no son directamente utilizables para dosimetría.** Cada fabricante de escáner PET aplica factores de calibración diferentes, y estos factores pueden variar incluso entre slices del mismo estudio. Este paso lee cada slice DICOM individualmente, extrae los factores `RescaleSlope` y `RescaleIntercept` específicos de cada uno, y convierte los valores raw a concentración de actividad radiactiva en Bq/mL. Es una réplica del algoritmo MATLAB `f_Rescale_Bq.m`.

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| Bq/mL | Becquerel por mililitro — concentración de actividad |
| DICOM | Digital Imaging and Communications in Medicine |
| GBq | Gigabecquerel ($10^9$ Bq) |
| mCi | Milicurie ($3.7 \times 10^7$ Bq) |
| PET | Positron Emission Tomography |
| SUV | Standardized Uptake Value |
| TS | TotalSegmentator |

---

## 1. El Problema de la Calibración

Un escáner PET registra la cantidad de fotones de aniquilación detectados en cada voxel. Estos valores crudos no son actividad real, sino cuentas arbitarias que dependen de:

- La sensibilidad del detector
- El tiempo de adquisición
- La atenuación del tejido
- La calibración cruzada con una fuente conocida

Para convertir a Bq/mL (actividad real por unidad de volumen), cada slice DICOM lleva metadatos de calibración:

| Tag DICOM | Campo | Descripción |
|-----------|-------|-------------|
| (0028,1052) | `RescaleSlope` | Factor multiplicativo $m_k$ del slice $k$ |
| (0028,1053) | `RescaleIntercept` | Término aditivo $b_k$ del slice $k$ |
| (0028,1054) | `RescaleType` | Unidad de salida (debe ser `"BQML"`) |

**Importante**: Cada archivo DICOM (que contiene un slice) puede tener sus propios valores de $m_k$ y $b_k$. No se puede asumir un valor global para todo el volumen.

---

## 2. Algoritmo de Calibración

### Paso 1: Listar y ordenar archivos DICOM

Se listan todos los archivos en el directorio PET y se ordenan por nombre de archivo (que típicamente corresponde al orden axial de los slices).

### Paso 2: Leer cada slice

```python
for fname in sorted(os.listdir(pet_dir)):
    ds = pydicom.dcmread(os.path.join(pet_dir, fname))
```

### Paso 3: Extraer factores de calibración

```python
m_k = float(ds.RescaleSlope)       # pendiente del slice k
b_k = float(ds.RescaleIntercept)   # intercepto del slice k
tau_k = str(ds.RescaleType).strip()  # tipo: debe ser "BQML"
```

### Paso 4: Aplicar calibración

Si $\tau_k = \text{"BQML"}$:

$$A_{\text{vox}}^{(k)}(i,j) = P_{\text{raw}}^{(k)}(i,j) \cdot m_k + b_k$$

| Variable | Descripción | Unidades |
|----------|-------------|:--------:|
| $A_{\text{vox}}^{(k)}(i,j)$ | Concentración de actividad calibrada en el voxel $(i,j)$ del slice $k$ | Bq/mL |
| $P_{\text{raw}}^{(k)}(i,j)$ | Valor crudo DICOM (pixel_array) del voxel $(i,j)$ del slice $k$ | adimensional |
| $m_k$ | RescaleSlope del slice $k$ — factor de escala | (Bq/mL)/unidad |
| $b_k$ | RescaleIntercept del slice $k$ — término aditivo | Bq/mL |
| $i$ | Índice de columna (0 a $N_x-1$) | — |
| $j$ | Índice de fila (0 a $N_y-1$) | — |
| $k$ | Índice de slice (0 a $N_z-1$) | — |

Si $\tau_k \neq \text{"BQML"}$, se registra un warning y el slice se omite.

### Paso 5: Calcular actividad total

#### 5.1 Volumen del voxel PET

$$V_{\text{voxel}} = \frac{s_x^{\text{PET}}}{10} \cdot \frac{s_y^{\text{PET}}}{10} \cdot \frac{s_z^{\text{PET}}}{10}$$

| Variable | Descripción | Unidades |
|----------|-------------|:--------:|
| $V_{\text{voxel}}$ | Volumen de un voxel PET | cm³ (= mL) |
| $s_x^{\text{PET}}$ | PixelSpacing en X (DICOM tag (0028,0030)[0]) | mm |
| $s_y^{\text{PET}}$ | PixelSpacing en Y (DICOM tag (0028,0030)[1]) | mm |
| $s_z^{\text{PET}}$ | SliceThickness (DICOM tag (0018,0050)) | mm |
| División por 10 | Conversión mm → cm | — |

Ejemplo: para PET con $4.07 \times 4.07 \times 2.5$ mm:
$$V_{\text{voxel}} = 0.407 \times 0.407 \times 0.25 = 0.0414 \text{ cm}^3 = 0.0414 \text{ mL}$$

#### 5.2 Actividad por voxel

$$A_{\text{Bq}}^{(k)}(i,j) = A_{\text{vox}}^{(k)}(i,j) \cdot V_{\text{voxel}}$$

| Variable | Descripción | Unidades |
|----------|-------------|:--------:|
| $A_{\text{Bq}}^{(k)}(i,j)$ | Actividad total en el voxel $(i,j,k)$ | Bq |
| $A_{\text{vox}}^{(k)}(i,j)$ | Concentración de actividad | Bq/mL |
| $V_{\text{voxel}}$ | Volumen del voxel | mL |

#### 5.3 Actividad total

$$A_{\text{total}} = \sum_{k=1}^{N_z} \sum_{i=1}^{N_y} \sum_{j=1}^{N_x} A_{\text{Bq}}^{(k)}(i,j)$$

#### 5.4 Conversiones de unidades

$$A_{\text{GBq}} = \frac{A_{\text{total}}}{10^9} \quad [\text{GBq}]$$

$$A_{\text{mCi}} = \frac{A_{\text{total}}}{3.7 \times 10^7} \quad [\text{mCi}]$$

| Unidad | Equivalencia |
|:------:|:------------:|
| 1 Bq | 1 desintegración por segundo |
| 1 GBq | $10^9$ Bq |
| 1 mCi | $3.7 \times 10^7$ Bq = 37 MBq |

---

## 3. Parámetros Típicos

| Parámetro | Símbolo | Valor típico | Descripción |
|-----------|:-------:|:------------:|-------------|
| RescaleSlope | $m_k$ | $1.0$ a $2.5$ | Factor de pendiente (varía por slice) |
| RescaleIntercept | $b_k$ | $0.0$ | Intercepto (típicamente 0) |
| RescaleType | $\tau_k$ | `"BQML"` | Unidad: Bq/mL |
| Voxel PET | $V_{\text{voxel}}$ | $0.041$ mL | Para espaciado $4.07 \times 4.07 \times 2.5$ mm |
| Actividad administrada ($^{90}$Y) | — | $1$ a $5$ GBq | Rango clínico típico |
| Actividad en imagen | — | $0.5$ a $3$ GBq | Depende del tiempo post-administración |
| Número de slices | $N_s$ | $100$ a $400$ | Según duración de la adquisición |

---

## 4. Conservación de la Actividad Post-Registro

Cuando el PET se re-muestrea a la grilla del CT (Paso 4), la interpolación lineal altera la suma total de actividad. Para compensar, se aplica un factor de corrección:

$$A_{\text{corregido}}(\mathbf{r}) = A_{\text{interp}}(\mathbf{r}) \cdot \frac{A_{\text{original}}}{A_{\text{interpolada}}}$$

| Variable | Descripción | Unidades |
|----------|-------------|:--------:|
| $A_{\text{corregido}}(\mathbf{r})$ | Actividad corregida en el voxel $\mathbf{r} = (x,y,z)$ | Bq/mL |
| $A_{\text{interp}}(\mathbf{r})$ | Actividad interpolada (del remuestreo) | Bq/mL |
| $A_{\text{original}}$ | Actividad total del PET original (pre-resample) | Bq |
| $A_{\text{interpolada}}$ | Actividad total del PET interpolado (post-resample) | Bq |

El factor se aplica solo si difiere de $1.0$ en más de $0.001$.

---

## 5. Diagrama de Flujo

```
Archivos DICOM PET (uno por slice)
       │
       ▼
Para cada slice k:
       │
       ├── dcmread(slice_k)
       ├── m_k = RescaleSlope_k
       ├── b_k = RescaleIntercept_k
       ├── τ_k = RescaleType_k
       │
       ├── ¿τ_k == "BQML"?
       │   ├── SÍ: A_Bq/mL = pixel_array × m_k + b_k
       │   └── NO: warning, se omite
       │
       └── A_Bq = A_Bq/mL × V_voxel
       │
       ▼
A_total = Σ A_Bq
A_GBq = A_total / 1e9
A_mCi = A_total / 3.7e7
       │
       ▼
Almacenar en pipeline.pet_activity:
{
  "total_bq": 1.5e9,
  "total_gbq": 1.5,
  "total_mci": 40.5,
  "mean_bqml": 8500,
  "max_bqml": 45000,
  "nonzero_voxels": 850000
}
```

---

## 6. Advertencia Crítica: Slicer Pierde la Calibración por Slice

El nodo de volumen de Slicer **NO conserva** los factores `RescaleSlope`/`RescaleIntercept` individuales por slice. Slicer aplica factores globales a todo el volumen cuando lee DICOM, lo que significa que la actividad almacenada en el nodo Slicer puede ser incorrecta.

**Por esta razón**, el pipeline:

1. **No usa** el nodo Slicer para obtener la actividad
2. **Lee directamente** los DICOM raw con `pydicom`
3. **Calcula la actividad** slice por slice con los factores correctos
4. **Guarda** el resultado en `self.pet_activity` para referencia futura

---

## 7. Ejemplo de Código

```python
# pet_dicom_reader.py — función read_pet_dicom_activity()
import os, pydicom, numpy as np

def read_pet_dicom_activity(pet_dir):
    """Lee actividad PET desde DICOM raw, slice por slice."""
    total_bq = 0.0
    voxel_count = 0
    n_slices = 0
    rescale_types = set()
    
    for fname in sorted(os.listdir(pet_dir)):
        ds = pydicom.dcmread(os.path.join(pet_dir, fname))
        m_k = float(ds.RescaleSlope)
        b_k = float(ds.RescaleIntercept)
        tau = str(ds.RescaleType).strip()
        rescale_types.add(tau)
        
        if tau == "BQML":
            pixels = ds.pixel_array.astype(np.float64)
            bqml = pixels * m_k + b_k
            # Calcular actividad...
            total_bq += np.sum(bqml) * voxel_volume_ml
    
    return {"total_bq": total_bq, "total_gbq": total_bq / 1e9, ...}
```

---

## 8. Control de Calidad (AI Supervisor)

| Verificación | Condición de fallo | Acción |
|-------------|:------------------:|:------:|
| Actividad total $\leq 0$ | $A_{\text{total}} \leq 0$ Bq | Error → detener pipeline |
| RescaleType no es "BQML" | $\tau_k \neq \text{"BQML"}$ | Warning (puede ser PET no calibrado) |
| Actividad fuera de rango | $A_{\text{total}} < 0.1$ o $> 50$ GBq | Warning (rango normal Y-90: 1-5 GBq administrados) |
| Sin slices válidos | $N_{\text{slices}} = 0$ | Error → detener pipeline |

---

## 9. Notas Importantes

- La actividad se mide **antes** del remuestreo PET→CT. Este valor se guarda como referencia para la conservación de actividad post-registro.
- Si `RescaleType` no es `"BQML"`, los valores raw se usan sin recalibración, pero se registra una advertencia.
- Tras la calibración, el checkpoint del remuestreo se invalida para forzar su re-ejecución con el nodo calibrado nuevo.
- El peso del paciente ($W_{\text{pac}}$) puede proporcionarse en `pipeline_config.jsonc` para cálculos de SUV si es necesario.
