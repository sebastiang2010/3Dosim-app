# Diagnóstico de carga de escena en 3D Slicer

## Objetivo

El pipeline lanza correctamente **3D Slicer**, pero la escena `.mrb` no termina cargándose, por lo que el resto del procesamiento nunca encuentra los nodos necesarios y la dosimetría no se ejecuta.

El objetivo NO es modificar el algoritmo de dosimetría sino encontrar la causa exacta de la falla en la carga de la escena.

---

# Situación actual

El launcher construye correctamente el comando:

```text
Slicer.exe
    --python-script run_dosimetry_from_scene.py
    --scene-path <ruta escena>
    --kernel <ruta kernel>
```

Por lo tanto, el problema probablemente NO está en el launcher.

El script ejecutado por Slicer contiene una llamada a:

```python
success = slicer.util.loadScene(scene_path)
```

Sin embargo, la escena nunca aparece cargada en la interfaz.

---

# Objetivo del diagnóstico

Determinar exactamente cuál de los siguientes casos ocurre:

1. `loadScene()` nunca se ejecuta.
2. `loadScene()` recibe una ruta incorrecta.
3. `loadScene()` devuelve False.
4. `loadScene()` devuelve True pero la escena queda vacía.
5. La escena se carga parcialmente.
6. La escena se carga correctamente pero el código continúa demasiado rápido.
7. Existe alguna excepción silenciosa.

No realizar modificaciones funcionales hasta conocer cuál de estos casos ocurre.

---

# Paso 1 - Verificar que el script realmente llegó a loadScene()

Agregar inmediatamente antes de la llamada:

```python
logger.info("=" * 80)
logger.info("ANTES DE loadScene")
logger.info(f"scene_path = {scene_path}")
logger.info(f"exists = {os.path.exists(scene_path)}")
logger.info(f"size = {os.path.getsize(scene_path) if os.path.exists(scene_path) else 'NO FILE'}")
logger.info("=" * 80)
```

---

# Paso 2 - Registrar el resultado de loadScene()

Inmediatamente después:

```python
logger.info(f"loadScene() -> {success}")
```

---

# Paso 3 - Registrar errores de Slicer

Después de loadScene():

```python
try:
    logger.info(f"Scene error: {slicer.mrmlScene.GetErrorMessage()}")
except Exception:
    pass
```

---

# Paso 4 - Esperar a que Slicer procese eventos

Si loadScene devuelve True, agregar temporalmente:

```python
import time

for _ in range(20):
    slicer.app.processEvents()
    time.sleep(0.1)
```

Esto permitirá descartar problemas de inicialización asíncrona.

---

# Paso 5 - Listar todos los nodos de la escena

Después de la espera anterior:

```python
logger.info("=" * 80)
logger.info("NODOS CARGADOS")

n = slicer.mrmlScene.GetNumberOfNodes()
logger.info(f"Cantidad: {n}")

for i in range(n):
    node = slicer.mrmlScene.GetNthNode(i)
    logger.info(
        f"{i:03d} | {node.GetClassName()} | {node.GetName()}"
    )

logger.info("=" * 80)
```

Esto permitirá distinguir entre:

* escena vacía
* escena parcialmente cargada
* escena completamente cargada

---

# Paso 6 - Capturar excepciones

Envolver la llamada completa en:

```python
try:
    success = slicer.util.loadScene(scene_path)
except Exception as e:
    logger.exception(e)
    raise
```

No permitir que una excepción quede oculta.

---

# Paso 7 - No modificar find_nodes()

Mientras no se confirme que la escena realmente fue cargada, NO modificar:

* find_nodes()
* procesamiento PET
* procesamiento CT
* segmentaciones
* convolución FFT

Primero debe comprobarse que la escena exista realmente dentro de `slicer.mrmlScene`.

---

# Paso 8 - Verificación manual

Comprobar manualmente que el mismo archivo

```
C:\MAT\3Dosim\ai-pipe\scenes\3Dosim.mrb
```

puede abrirse desde:

```
File → Open
```

dentro de la misma versión de 3D Slicer utilizada por el pipeline.

Si tampoco abre manualmente, el problema no pertenece al código.

---

# Resultado esperado

Al finalizar el diagnóstico deberá conocerse con certeza:

* si `loadScene()` fue ejecutado;
* si devolvió True o False;
* si hubo mensajes de error internos de Slicer;
* cuántos nodos quedaron cargados;
* los nombres y tipos de todos los nodos presentes;
* si la escena realmente quedó vacía o simplemente no fue reconocida por el pipeline.

No realizar cambios en la lógica de dosimetría hasta completar este diagnóstico.
