# Visualización 3D

## Propósito

Configurar la interfaz de 3D Slicer para mostrar las imágenes y
segmentaciones en un layout 4-up optimizado para visualización
médica: axial, sagital, coronal y vista 3D.

## Layout 4-up

```
┌──────────────┬──────────────┐
│   AXIAL      │   SAGITAL    │
│   (slice)    │   (slice)    │
├──────────────┼──────────────┤
│   CORONAL    │    3D        │
│   (slice)    │  (volumen    │
│              │  rendering)  │
└──────────────┴──────────────┘
```

## setup_medical_views()

Esta función se llama al menos 3 veces durante el pipeline:

| Momento | Propósito |
|---------|-----------|
| Tras fusión CT+PET | Mostrar las 3 imágenes (CT, PET, fusión) |
| Tras TotalSegmentator | Mostrar segmentaciones sobre CT (opacidad) |
| Tras validación | Mostrar resultado final |

### Algoritmo

```python
def setup_medical_views(ct_node, pet_node=None, seg_node=None, tumor_node=None):
    # 1. Configurar layout 4-up
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    # 2. Sincronizar vistas
    #    - Misma posición de slice en axial/sagital/coronal
    #    - Crosshair sincronizado entre vistas
    
    # 3. Configurar foreground-background en slices
    for view_name in ["axial", "sagittal", "coronal"]:
        sliceNode = layoutManager.sliceWidget(view_name).mrmlSliceNode()
        sliceNode.SetForegroundOpacity(0.3)  # opacidad PET
        
        # Compositores: CT como background, PET como foreground
        compositeNode = sliceNode.GetCompositeNode()
        compositeNode.SetBackgroundVolumeID(ct_node.GetID())
        if pet_node:
            compositeNode.SetForegroundVolumeID(pet_node.GetID())
    
    # 4. Volumen rendering en 3D
    viewNode = layoutManager.threeDWidget(0).mrmlViewNode()
    # Opcional: mostrar CT rendering con corte sagital
    
    # 5. Color legend (opcional)
    #    Mostrar barra de colores para HU (CT) o SUV (PET)
```

## Volumen Rendering

- CT en ventana: nivel 600 HU, ancho 1600 HU (abdomen)
- PET en colormap "Rainbow" sobre CT
- Segmentaciones con opacidad 30-50%

## Interactividad

| Acción | Efecto |
|--------|--------|
| Scroll en axial | Desplaza slice |
| Ctrl+scroll en 3D | Zoom |
| Click en vista 3D | Rotar |
| Click en crosshair | Mover slice a esa posición |
| Slider opacidad | PET fade in/out |

## Notas

- El layout 4-up usa el preset `SlicerLayoutFourUpView` de Slicer
- Se puede cambiar a 3-only o 1-only según espacio disponible
- El volumen rendering se configura con el preset de abdomen
- Los slices linked permiten navegación coordinada
