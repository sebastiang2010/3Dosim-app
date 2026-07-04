# Exportación de Labelmap Dosimétrica

## Propósito

Convertir la segmentación completa (órganos + tumor + body) en un
archivo **NIfTI** y **NRRD** donde cada voxel tiene un valor entero
que corresponde al índice del tejido en `tissue_config.json`.

Esta labelmap es la **entrada del Módulo 2** (generación de entrada MCNP).

## Algoritmo

### 1. Cargar tissue_config.json

```python
tissue_config = _load_tissue_config(config_path)
# Construye mapeo: nombre_segmento → indice_phantom
```

### 2. Construir mapping nombre → índice

Para cada segmento en la segmentación:
1. Si el ID del segmento es un número (label TS original), lookup en
   `ts_label_to_phantom`
2. Si no, lookup por nombre en `DEFAULT_NAME_TO_PHANTOM`
3. Si no, detectar hueso por palabras clave ("rib", "vertebra", etc.)
4. Si no, asignar índice libre 2-256

### 3. Acumular en labelmap 3D

```python
final_labelmap = np.zeros((Nz, Ny, Nx), dtype=np.int16)
any_organ = np.zeros((Nz, Ny, Nx), dtype=bool)

for seg_name, phantom_idx in mapping.items():
    mask = _extract_single_segment_mask(seg_name)
    # Resolver solapamientos: gana el índice más alto (más específico)
    new_region = (mask > 0) & ((final_labelmap == 0) | (phantom_idx > final_labelmap))
    final_labelmap[new_region] = phantom_idx
    any_organ[new_region] = True
```

### 4. Incorporar body segmentation

```python
body_mask = _extract_body_mask(body_segmentation_node)
body_region = (body_mask > 0) & ~any_organ
final_labelmap[body_region] = 30  # Tejido_blando
```

### 5. Verificar integridad

- Sin solapamiento entre órganos
- Todos los voxeles dentro del body tienen un índice asignado
- Si hay voxeles sin asignar dentro del body → asignar tejido blando (30)

### 6. Exportar

| Formato | Extensión | Uso |
|---------|-----------|-----|
| NIfTI | `.nii` | Módulo 2 (MCNP), compatible con mayoría herramientas |
| NRRD | `.nrrd` | 3D Slicer, formato nativo |

## Esquema

```
Segmentation nodes (órganos + tumor)
         │
         ▼
┌─────────────────────────────┐
│ Mapeo nombre → índice        │
│ ts_label_to_phantom + lookup│
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│ Acumular en labelmap 3D     │
│ Resolver solapamientos      │
│ (índice más alto gana)      │
└────────────┬────────────────┘
             │
   ┌─────────┴─────────┐
   ▼                   ▼
Body seg          Body NO disp
   │                   │
   ▼                   ▼
Body = 30        Voxels sueltos
donde no hay     → asignar 30
órganos
   │
   ▼
┌─────────────────────────────┐
│ Verificar integridad        │
│ (sin solapamientos)         │
└────────────┬────────────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
 NIfTI (.nii)    NRRD (.nrrd)
```

## Verificaciones post-export

| Verificación | Qué detecta |
|-------------|-------------|
| Valores únicos | Todos los índices esperados presentes |
| Overlap voxels | Solapamiento entre órganos (ideal: 0) |
| Voxels sin asignar | Dentro del body sin tejido asignado |
| Body vs órganos | Body no solapa con ningún órgano |

## Notas

- El nodo `3Dosim_Labelmap` queda visible en Slicer (Data module)
- NO se guarda escena después de exportar labelmap porque el nodo
  de 89 MB dentro del MRB cuelga Slicer
- Los archivos se guardan en `output_dir/labelmaps/`
- Los índices 1 (Aire) no se asignan explícitamente: todo lo que no
  tiene un índice > 1 es aire por defecto
