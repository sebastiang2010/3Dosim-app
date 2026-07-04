# Especificación de implementación
## Separación automática de lesiones de TotalSegmentator (`liver_lesion`)

## Objetivo

Implementar una etapa automática del pipeline que se ejecute **únicamente** cuando el origen de la segmentación sea **TotalSegmentator** y exista el segmento **`liver_lesion`**.

TotalSegmentator genera todas las lesiones hepáticas dentro de un único segmento. Esta implementación deberá separar automáticamente cada lesión (componente conectada) en un segmento independiente.

El resultado esperado es:

```
Antes

Segmentation
 ├── liver
 └── liver_lesion


Después

Segmentation
 ├── liver
 ├── tumor_1
 ├── tumor_2
 ├── tumor_3
 └── ...
```

Cada segmento `tumor_i` deberá contener exactamente una lesión.

---

# Alcance

Esta funcionalidad debe ejecutarse **únicamente** para el segmento:

```
liver_lesion
```

cuando dicho segmento haya sido generado por **TotalSegmentator**.

No debe ejecutarse para:

- liver
- lungs
- kidneys
- vessels
- otras estructuras
- segmentos creados manualmente por el usuario

---

# Objetivo técnico

No modificar la geometría de las lesiones.

No aplicar ningún procesamiento morfológico.

Únicamente separar las componentes conectadas existentes.

---

# Algoritmo requerido

No implementar algoritmos propios de búsqueda.

Utilizar exclusivamente SimpleITK:

```python
sitk.ConnectedComponent()
```

para identificar automáticamente todas las componentes conectadas.

---

# Flujo de procesamiento

```
SegmentationNode

        │

buscar segmento "liver_lesion"

        │

obtener Binary Labelmap

        │

convertir a SimpleITK Image

        │

ConnectedComponent()

        │

LabelShapeStatisticsImageFilter()

        │

obtener todas las etiquetas

        │

para cada etiqueta:

        │

crear Binary Labelmap independiente

        │

crear nuevo segmento

        │

nombre: tumor_1
        tumor_2
        tumor_3
        ...

        │

importar al SegmentationNode

        │

eliminar segmento liver_lesion
```

---

# Obtención del Binary Labelmap

El procesamiento debe realizarse sobre la representación Binary Labelmap del segmento.

No operar directamente sobre el objeto Segment.

El flujo esperado es:

```
vtkSegment

↓

Binary Labelmap

↓

vtkOrientedImageData

↓

SimpleITK Image
```

---

# Separación de lesiones

Ejecutar:

```python
ConnectedComponent()
```

sobre la imagen binaria.

Cada componente conectada representa una lesión independiente.

No utilizar:

- distancia
- clustering
- watershed
- operaciones geométricas

Únicamente Connected Components.

---

# Cantidad de lesiones

No asumir una cantidad fija.

Obtener las componentes mediante:

```python
stats = sitk.LabelShapeStatisticsImageFilter()
stats.Execute(cc)

labels = stats.GetLabels()
```

La cantidad de lesiones será:

```python
len(labels)
```

Cada elemento de `labels` representa una lesión.

---

# Creación de segmentos

Para cada etiqueta:

```
1

2

3

...

N
```

crear una máscara binaria independiente:

```python
mask = (cc == label)
```

Convertir dicha máscara nuevamente a Binary Labelmap.

Importarla al SegmentationNode.

Crear un segmento llamado:

```
tumor_1

tumor_2

tumor_3

...

tumor_N
```

Cada segmento debe contener únicamente una componente conectada.

---

# Orden de numeración

Mantener el orden devuelto por ConnectedComponent.

No reordenar por:

- volumen
- posición
- centroide
- coordenadas

La numeración será:

```
tumor_1

tumor_2

...

tumor_N
```

según el orden natural de las etiquetas generadas por SimpleITK.

---

# Segmento original

Una vez creados correctamente todos los segmentos individuales:

Eliminar completamente el segmento:

```
liver_lesion
```

No conservarlo oculto.

No mantener simultáneamente:

```
liver_lesion
```

y

```
tumor_i
```

para evitar duplicaciones de volumen durante cálculos posteriores.

---

# Casos especiales

## Caso 1

No existe el segmento:

```
liver_lesion
```

Resultado esperado:

No realizar ninguna acción.

Continuar normalmente el pipeline.

---

## Caso 2

El segmento existe pero está vacío.

Resultado esperado:

No crear segmentos.

Continuar normalmente.

---

## Caso 3

Existe una única componente conectada.

Resultado esperado:

Crear:

```
tumor_1
```

Eliminar:

```
liver_lesion
```

El resto del pipeline deberá trabajar igualmente con:

```
tumor_1
```

---

## Caso 4

Existen múltiples componentes.

Resultado esperado:

```
tumor_1

tumor_2

...

tumor_N
```

Eliminar:

```
liver_lesion
```

---

# Colisiones de nombres

Esta rutina se ejecutará inmediatamente después de TotalSegmentator.

Se asume que todavía no existen segmentos:

```
tumor_*
```

Por lo tanto no es necesario implementar lógica para renombrados automáticos.

---

# Restricciones

No aplicar:

- Closing
- Opening
- Dilation
- Erosion
- Margin
- Smoothing
- Islands
- Wrap Solidify
- Surface Operations
- Mesh Processing

No modificar:

- volumen
- forma
- bordes
- voxelización

Las lesiones deben conservar exactamente la geometría producida por TotalSegmentator.

---

# Compatibilidad

La implementación debe funcionar correctamente con:

- 1 lesión
- 2 lesiones
- 5 lesiones
- 20 lesiones
- cualquier cantidad de lesiones

sin modificar el código.

---

# Resultado esperado

Entrada:

```
Segmentation

├── liver
└── liver_lesion
```

Salida:

```
Segmentation

├── liver
├── tumor_1
├── tumor_2
├── tumor_3
├── tumor_4
└── ...
```

Cada segmento debe contener exactamente una lesión independiente.

---

# Objetivo final

Los segmentos generados deberán utilizarse posteriormente por el resto del pipeline para:

- cálculo individual de volumen;
- cálculo individual de actividad;
- cálculo individual de dosis;
- estadísticas por lesión;
- exportación a LabelMap con una etiqueta independiente por lesión;
- procesamiento automático en módulos posteriores de 3Dosim.

La implementación debe ser completamente automática, determinista y no requerir interacción del usuario.