# Anonimización DICOM

> **Las imágenes DICOM contienen información de salud protegida (PHI) que debe eliminarse antes de procesarlas con herramientas externas.** Este paso copia los archivos DICOM originales a un directorio `anon/`, limpia los metadatos identificables (nombre del paciente, ID, fecha del estudio, institución, etc.) y renombra los archivos con prefijo `ANON_`. Es un requisito legal según HIPAA (EEUU) y GDPR (Europa).

---

**Acrónimos usados en este documento:**

| Acrónimo | Significado |
|----------|-------------|
| DICOM | Digital Imaging and Communications in Medicine |
| GDPR | General Data Protection Regulation (Unión Europea) |
| HIPAA | Health Insurance Portability and Accountability Act (EEUU) |
| PHI | Protected Health Information — datos de salud protegidos |
| TS | TotalSegmentator |

---

## 1. ¿Por Qué es Necesaria la Anonimización?

Los archivos DICOM contienen metadatos que identifican directa o indirectamente al paciente:

- **Identificación directa**: nombre completo, número de historia clínica
- **Identificación indirecta**: fecha del estudio, nombre de la institución, médico tratante

TotalSegmentator y otros módulos externos pueden almacenar o transmitir estos archivos. La anonimización previene la exposición de PHI.

---

## 2. Algoritmo

### Paso 1: Crear directorio de salida

Se crea `output_dir/anon/` si no existe.

### Paso 2: Copiar archivos

Los archivos DICOM de CT y PET se copian al directorio `anon/`.

### Paso 3: Limpiar metadatos

Para cada archivo DICOM:

```python
ds = pydicom.dcmread(filepath)
for tag in FIELDS_TO_CLEAR:
    if tag in ds:
        ds[tag].value = ""  # o valor por defecto
ds.save_as(filepath)
```

### Paso 4: Renombrar

Los archivos se renombran con prefijo `ANON_` para identificar que están anonimizados.

---

## 3. Campos Eliminados

| Tag DICOM | Campo | Razón |
|-----------|-------|-------|
| (0010,0010) | `PatientName` | Identificación directa del paciente |
| (0010,0020) | `PatientID` | Identificación directa (historia clínica) |
| (0008,0020) | `StudyDate` | Fecha del estudio (información temporal) |
| (0008,0080) | `InstitutionName` | Origen del estudio |
| (0008,0090) | `ReferringPhysician` | Médico tratante |
| (0008,0050) | `AccessionNumber` | ID interno del estudio |
| (0020,0010) | `StudyID` | ID del estudio |
| (0008,103E) | `SeriesDescription` | Descripción de la serie |
| (0008,0081) | `InstitutionAddress` | Dirección de la institución |

---

## 4. Configuración

```jsonc
{
    "anonymization": {
        "enabled": true,
        "prefix": "ANON_",
        "output_dir": "{output_dir}/anon/",
        "fields_to_clear": [
            "PatientName", "PatientID", "StudyDate", "InstitutionName",
            "ReferringPhysician", "AccessionNumber", "StudyID",
            "SeriesDescription", "InstitutionAddress"
        ]
    }
}
```

| Clave | Descripción | Default |
|-------|-------------|:-------:|
| `enabled` | Activar/desactivar anonimización | `true` |
| `prefix` | Prefijo para archivos anonimizados | `"ANON_"` |
| `output_dir` | Directorio de salida | `{output_dir}/anon/` |
| `fields_to_clear` | Lista de campos DICOM a limpiar | (ver tabla §3) |

---

## 5. Formato de Salida

| Archivo original | Archivo anonimizado |
|------------------|---------------------|
| CT DICOM (serie de archivos .dcm) | `output_dir/anon/ANON_CT.nrrd` |
| PET DICOM (serie de archivos .dcm) | `output_dir/anon/ANON_PET.nii` |

Los archivos anonimizados se guardan como volúmenes NIfTI/NRRD (no como DICOM individual) para facilitar su uso en TotalSegmentator.

---

## 6. Diagrama de Flujo

```
DICOM original (CT, PET)
    │
    ▼
┌─────────────────────────┐
│ Crear directorio anon/  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Copiar archivos a anon/ │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Para cada archivo:      │
│                         │
│ 1. dcmread()            │
│ 2. Limpiar tags PHI     │
│ 3. save_as()            │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Renombrar ANON_*         │
│ CT → ANON_CT.nrrd       │
│ PET → ANON_PET.nii      │
└────────────┬────────────┘
             │
             ▼
    Archivos listos para TS
```

---

## 7. Control de Calidad

| Verificación | Criterio | Acción |
|-------------|:--------:|:------:|
| Archivos anonimizados existen | `os.path.exists(anon_ct)` y `anon_pet` | Error si no existen |
| Campos PHI limpiados | Verificar que PatientName esté vacío | Warning si no se pudo verificar |

---

## 8. Notas Importantes

- La anonimización es **irreversible**: una vez eliminados los metadatos, no se pueden recuperar.
- Los archivos originales siempre se conservan en el directorio de entrada original.
- Solo los archivos en `anon/` se pasan a TotalSegmentator.
- Si `enabled: false`, se usan los archivos originales directamente (no recomendado).
- Este paso no modifica los píxeles de la imagen, solo los metadatos. Las firmas (hashes) de los archivos cambiarán aunque el contenido visual sea idéntico.
