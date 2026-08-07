# Graficar una `vtkMRMLTableNode` en 3D Slicer

## Objetivo

Este documento describe cómo visualizar una tabla (`vtkMRMLTableNode`) como un gráfico utilizando el módulo **Plots** de 3D Slicer desde Python.

---

# Paso 1. Obtener la tabla

Por ejemplo, para la DVH del tumor:

```python
tableNode = slicer.util.getNode("DVH_Table_Tumor")
```

---

# Paso 2. Verificar las columnas

Antes de crear el gráfico es recomendable inspeccionar la tabla:

```python
table = tableNode.GetTable()

for i in range(table.GetNumberOfColumns()):
    print(
        i,
        table.GetColumnName(i),
        table.GetColumn(i).GetClassName()
    )
```

La salida debería ser similar a:

```
0 Dose vtkDoubleArray
1 Volume vtkDoubleArray
2 Structure vtkStringArray
```

---

# Paso 3. Eliminar columnas de texto

El módulo **Plots** trabaja correctamente con columnas numéricas (`vtkDoubleArray` o `vtkFloatArray`).

Si existe una tercera columna de texto (`vtkStringArray`), debe eliminarse.

Por ejemplo, si la tercera columna corresponde al índice 2:

```python
table = tableNode.GetTable()

table.RemoveColumn(2)

table.Modified()
tableNode.Modified()
```

Después de eliminarla, verificar nuevamente:

```python
for i in range(table.GetNumberOfColumns()):
    print(
        i,
        table.GetColumnName(i),
        table.GetColumn(i).GetClassName()
    )
```

Ahora únicamente deberían quedar columnas numéricas, por ejemplo:

```
0 Dose vtkDoubleArray
1 Volume vtkDoubleArray
```

---

# Paso 4. Crear la Plot Series

```python
plotSeriesNode = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLPlotSeriesNode"
)

plotSeriesNode.SetAndObserveTableNodeID(
    tableNode.GetID()
)

plotSeriesNode.SetXColumnName(
    tableNode.GetTable().GetColumnName(0)
)

plotSeriesNode.SetYColumnName(
    tableNode.GetTable().GetColumnName(1)
)
```

---

# Paso 5. Configurar el tipo de gráfico

Gráfico de puntos con línea:

```python
plotSeriesNode.SetPlotType(
    slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter
)

plotSeriesNode.SetLineStyle(
    slicer.vtkMRMLPlotSeriesNode.LineStyleSolid
)

plotSeriesNode.SetMarkerStyle(
    slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone
)
```

También pueden utilizarse otros tipos de representación según la aplicación.

---

# Paso 6. Crear el gráfico

```python
plotChartNode = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLPlotChartNode"
)

plotChartNode.AddAndObservePlotSeriesNodeID(
    plotSeriesNode.GetID()
)
```

---

# Paso 7. Configurar títulos

```python
plotChartNode.SetTitle("DVH")

plotChartNode.SetXAxisTitle("Dose (Gy)")

plotChartNode.SetYAxisTitle("Volume (%)")
```

---

# Paso 8. Mostrar el gráfico

```python
slicer.modules.plots.logic().ShowChartInLayout(
    plotChartNode
)
```

El layout cambiará automáticamente para mostrar la ventana de gráficos.

---

# Código completo

```python
# Obtener la tabla
tableNode = slicer.util.getNode("DVH_Table_Tumor")

# Eliminar la tercera columna (si es de texto)
table = tableNode.GetTable()

if table.GetNumberOfColumns() > 2:
    table.RemoveColumn(2)

table.Modified()
tableNode.Modified()

# Crear la serie
plotSeriesNode = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLPlotSeriesNode"
)

plotSeriesNode.SetAndObserveTableNodeID(
    tableNode.GetID()
)

plotSeriesNode.SetXColumnName(
    tableNode.GetTable().GetColumnName(0)
)

plotSeriesNode.SetYColumnName(
    tableNode.GetTable().GetColumnName(1)
)

# Configuración del gráfico
plotSeriesNode.SetPlotType(
    slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter
)

plotSeriesNode.SetLineStyle(
    slicer.vtkMRMLPlotSeriesNode.LineStyleSolid
)

plotSeriesNode.SetMarkerStyle(
    slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone
)

# Crear el Plot Chart
plotChartNode = slicer.mrmlScene.AddNewNodeByClass(
    "vtkMRMLPlotChartNode"
)

plotChartNode.AddAndObservePlotSeriesNodeID(
    plotSeriesNode.GetID()
)

# Títulos
plotChartNode.SetTitle("DVH")
plotChartNode.SetXAxisTitle("Dose (Gy)")
plotChartNode.SetYAxisTitle("Volume (%)")

# Mostrar el gráfico
slicer.modules.plots.logic().ShowChartInLayout(
    plotChartNode
)
```

---

# Requisitos

Para que el gráfico pueda generarse correctamente:

- La tabla debe ser un `vtkMRMLTableNode`.
- Las columnas utilizadas para los ejes X e Y deben ser de tipo `vtkDoubleArray` o `vtkFloatArray`.
- Las columnas de texto (`vtkStringArray`) deben eliminarse o no utilizarse para el gráfico.
- La tabla debe contener datos numéricos válidos.