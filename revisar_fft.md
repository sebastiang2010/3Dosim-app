# Revisión de `fft_dose.py`

## Objetivo

La función `convolve_imfilter_symmetric()` pretende reproducir exactamente el comportamiento de MATLAB:

```matlab
imfilter(activity, kernel, 'conv', 'same', 'symmetric')
```

Actualmente la implementación **no es completamente equivalente**. A continuación se describen los cambios que deben realizarse.

---

# 1. Corregir el origen del kernel antes de la FFT (CRÍTICO)

## Problema

Actualmente se calcula:

```python
K_fft = rfftn(kernel_f32, s=fft_shape, workers=-1)
```

Esto supone que el origen del kernel está en el índice `(0,0,0)`.

Sin embargo, en MATLAB el origen del kernel está en su centro.

Para un kernel de tamaño:

```
51 × 51 × 51
```

el centro está en

```
(25,25,25)
```

Si no se corrige este desplazamiento, toda la convolución queda desplazada aproximadamente 25 vóxeles en cada eje.

---

## Solución

Antes de calcular la FFT debe desplazarse el kernel mediante:

```python
kernel_fft = np.fft.ifftshift(kernel_f32)
```

o una operación equivalente con `np.roll`.

Luego calcular:

```python
K_fft = rfftn(kernel_fft, s=fft_shape, workers=-1)
```

No modificar el kernel original; únicamente utilizar la versión desplazada para la FFT.

---

# 2. Verificar el recorte "same"

Actualmente se utiliza:

```python
offset = tuple((s - ap) // 2 for s, ap in zip(full_shape, activity_pad.shape))
```

Para kernels impares (como 51×51×51) produce el resultado esperado.

Sin embargo, para reproducir exactamente MATLAB el recorte debería comenzar en el radio del kernel:

```
kernel_radius = kernel.shape // 2
```

y no depender del centrado del arreglo completo.

Aunque actualmente no genera errores debido al tamaño impar del kernel, conviene modificarlo para que sea matemáticamente correcto y general.

---

# 3. Cambiar el padding reflectivo

Actualmente se utiliza:

```python
np.pad(..., mode="reflect")
```

MATLAB utiliza:

```matlab
'symmetric'
```

La equivalencia más cercana en NumPy es:

```python
np.pad(..., mode="symmetric")
```

La diferencia aparece únicamente en los vóxeles cercanos al borde, pero si el objetivo es reproducir exactamente MATLAB debe utilizarse `mode="symmetric"`.

---

# 4. Mantener la convolución y no convertirla en correlación

El objetivo es reproducir:

```matlab
imfilter(...,'conv')
```

No debe cambiarse la operación por correlación.

El uso de `ifftshift` antes de la FFT conserva correctamente la convolución.

No agregar inversiones (`flip`) adicionales salvo que se demuestre que son necesarias mediante comparación con MATLAB.

---

# 5. Mejorar el cache del kernel

Actualmente el cache utiliza únicamente:

```python
cache_key = fft_shape
```

Si en el futuro cambia el kernel (por ejemplo otro radionúclido, distinta resolución o distinto tamaño), el programa reutilizará incorrectamente una FFT anterior.

El cache debería depender al menos de:

* tamaño del kernel
* tipo de dato
* tamaño FFT

Idealmente incluir también un hash del contenido del kernel.

Ejemplo conceptual:

```python
cache_key = (
    fft_shape,
    kernel.shape,
    kernel.dtype
)
```

---

# 6. Aspectos que NO deben modificarse

Los siguientes puntos son correctos y deben mantenerse:

* uso de `rfftn`
* uso de `irfftn`
* `workers=-1`
* `next_fast_len`
* conversión temporal a `float32`
* retorno final en `float64`
* padding para evitar wrap-around
* cache de la FFT del kernel (una vez corregida la clave)

---

# Resultado esperado

Tras las modificaciones, la función deberá producir resultados equivalentes a:

```matlab
imfilter(activity, kernel, 'conv', 'same', 'symmetric')
```

dentro del error numérico esperado de una implementación mediante FFT.

La prioridad de implementación es:

1. Corregir el origen del kernel mediante `ifftshift` (crítico).
2. Cambiar el padding a `mode="symmetric"`.
3. Revisar el recorte `same`.
4. Mejorar la clave del cache del kernel.
