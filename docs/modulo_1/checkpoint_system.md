# Sistema de Checkpoints — Persistencia y Reanudación del Pipeline

**Acrónimos usados en este documento:**  
`JSON` = JavaScript Object Notation · `SIGINT` = Signal Interrupt (Ctrl+C) · `MRB` = Medical Reality Bundle (formato de escena de 3D Slicer) · `NCC` = Normalized Cross-Correlation · `TS` = TotalSegmentator

---

En un pipeline de dosimetría que puede ejecutarse durante 15-60 minutos (dependiendo de si TotalSegmentator se ejecuta en modo rápido o completo), las interrupciones son inevitables: el usuario cierra Slicer por error, la computadora se reinicia, una segmentación falla por falta de memoria. El sistema de checkpoints resuelve este problema guardando el estado completo del pipeline después de **cada paso exitoso** en un archivo JSON estructurado. Al reiniciar, el orquestador `PipelineMod1` detecta automáticamente el último checkpoint y reanuda desde el primer paso pendiente, restaurando nodos, parámetros y visualización sin pérdida de progreso.

---

## Archivo de checkpoint

Se guarda en `output_dir/.checkpoints/pipeline_checkpoint.json`. Su estructura es un dict con las siguientes claves:

| Clave | Tipo | Descripción |
|-------|------|-------------|
| `version` | int | Versión del schema de checkpoint (actual: 1). Controla compatibilidad hacia atrás; versiones distintas provocan reinicio automático. |
| `completed` | [string] | Lista de nombres de pasos completados exitosamente. Cada nombre corresponde a una constante `STEP_*` de `PipelineMod1`. |
| `data` | {string: dict} | Diccionario que asocia cada paso completado con sus metadatos de restauración (nombres de nodos, paths, parámetros). |

### Ejemplo real

```json
{
    "version": 1,
    "completed": [
        "check_slicer",
        "load_dicom",
        "remove_couch_air",
        "resample_pet_to_ct",
        "show_fusion",
        "anonymize",
        "export_dicom_info"
    ],
    "data": {
        "check_slicer": {
            "slicer_version": "5.8.1"
        },
        "load_dicom": {
            "ct_node_name": "CT",
            "pet_node_name": "PET",
            "ct_dir": "C:/.../Paciente_2/CT",
            "pet_dir": "C:/.../Paciente_2/PET"
        },
        "remove_couch_air": {
            "ct_node_name": "CT",
            "ct_masked_node_name": "CT_sin_camilla"
        },
        "segment_phantom": {
            "segmentation_node_name": "TotalSegmentator_104",
            "segmenter": "totalsegmentator"
        }
    }
}
```

### Estados de un paso

Aunque el archivo solo almacena pasos completados, el orquestador clasifica cada paso en uno de tres estados lógicos:

| Estado | Significado | Acción al reanudar |
|--------|-------------|-------------------|
| `completed` | El paso finalizó exitosamente y su checkpoint fue guardado | Se salta completamente (no se re-ejecuta) |
| `in_progress` | El paso empezó pero no terminó (corte abrupto, excepción, SIGINT) | Se vuelve a ejecutar desde cero |
| `pending` | El paso no ha sido intentado | Se ejecuta normalmente |

La lógica de restauración busca el primer paso en estado `pending` o implícitamente `in_progress` (ausente de `completed`). Todos los pasos anteriores (presentes en `completed`) se saltan.

---

## Flujo de restauración

```
Inicio del pipeline
    │
    ├── ¿--reset?
    │   └── SÍ → CheckpointManager.reset(): elimina pipeline_checkpoint.json
    │            state = {version: 1, completed: [], data: {}}
    │
    └── NO → CheckpointManager._load()
                │
                ├── ¿pipeline_checkpoint.json existe?
                │   ├── NO → state vacío, ejecutar paso 1
                │   └── SÍ → leer JSON
                │               │
                │               ├── ¿version == CHECKPOINT_VERSION (1)?
                │               │   ├── SÍ → usar state
                │               │   └── NO → warning, reiniciar state
                │               │
                │               └── Cargar state
                │
                ▼
          PipelineMod1.run()
                │
                ▼
          Por cada paso:
                │
                ├── _checkpoint_step(step_name, display_name, func, data_func)
                │       │
                │       ├── ¿checkpoint.is_completed(step_name)?
                │       │   ├── SÍ → log "saltando por checkpoint"
                │       │   │        restaurar estado del paso (nodos, vistas)
                │       │   │        return True
                │       │   │
                │       │   └── NO → ejecutar func()
                │       │               │
                │       │               ├── ÉXITO → checkpoint.mark_completed(step_name, data)
                │       │               │           checkpoint._save() → escribe JSON
                │       │               │           AI supervisor revisa paso
                │       │               │           return True
                │       │               │
                │       │               └── FALLO → log error
                │       │                        AI supervisor revisa paso (con error)
                │       │                        return False
                │       │
                │       └── Continuar o detener según resultado
                │
                ▼
          Pipeline completado
```

---

## Integración en `pipeline_mod1.py`

Cada paso del pipeline está envuelto en `_checkpoint_step()`, que centraliza la lógica de checkpoint, logging, medición de tiempo y revisión del AI Supervisor.

```python
def _checkpoint_step(self, step_name, display_name, func, data_func=None):
    """Ejecuta un paso del pipeline con soporte de checkpoint.

    Parámetros:
        step_name (str): Nombre interno del paso (constante STEP_*).
                         Ej: "load_dicom", "segment_phantom".
        display_name (str): Nombre legible para logs.
                           Ej: "Cargando imagenes DICOM".
        func (callable): Función a ejecutar. Sin parámetros (usa self).
        data_func (callable, opcional): Función que retorna dict con datos
                                       a persistir en el checkpoint.
                                       Se llama SOLO si el paso es exitoso.

    Retorna:
        bool: True si el paso fue exitoso (o ya estaba completado),
              False si falló.

    Comportamiento:
        1. Si checkpoint.is_completed(step_name) → salta, restaura estado, retorna True.
        2. Ejecuta func().
        3. Si éxitosa:
           - Calcula elapsed = time.time() - t0
           - Guarda resultado en self.results["pasos"]
           - checkpoint.mark_completed(step_name, data=data_func())
           - Dispara AI supervisor con contexto del paso
           - Retorna True
        4. Si falla (exception):
           - Guarda error en self.results["errores"]
           - Dispara AI supervisor con el error
           - Retorna False
    """
```

### Ejemplo: paso de exportación de labelmap

```python
def _export_labelmap(self):
    """Paso 16: Exportar labelmap dosimétrica."""
    from PipelineOrchestrator.utils import track_time
    import slicer

    ct_node = getattr(self, 'ct_node', None) or getattr(self, 'ct_masked_node', None)
    seg_node = getattr(self, 'segmentation_node', None)
    body_node = getattr(self, 'body_node', None)

    if not seg_node or not ct_node:
        raise RuntimeError("Nodos necesarios no disponibles para exportar labelmap")

    # Ubicar tissue_config.json (búsqueda en múltiples rutas)
    tissue_config_path = self._find_tissue_config()

    with track_time("Generando labelmap dosimetrica"):
        resultado = labelmap_exporter.export_labelmap(
            segmentation_node=seg_node,
            ct_node=ct_node,
            tissue_config_path=tissue_config_path,
            output_dir=self.labelmap_dir,
            body_segmentation_node=body_node,
        )

    # Mostrar resumen en Slicer status bar (NO QMessageBox — cuelga Slicer)
    logger.info(f"  Segmentos: {resultado['num_segments']} | "
                f"Overlap: {resultado['overlap_voxels']}")
    slicer.util.showStatusMessage(
        f"Labelmap exportada: {resultado['num_segments']} segmentos", 8000)
```

El checkpoint se guarda automáticamente al finalizar `_checkpoint_step()`:

```python
# Dentro de _checkpoint_step, tras func() exitoso:
data = data_func() if data_func else {}
self.checkpoint.mark_completed(step_name, data=data)
# Esto llama a _save() que escribe pipeline_checkpoint.json inmediatamente
```

---

## Restauración de estado post-checkpoint

Cuando un paso ya está completado, `_checkpoint_step()` salta la ejecución pero llama a `_restore_step_state()` para que el pipeline tenga disponibles los nodos que necesita para pasos posteriores.

```python
def _restore_step_state(self, step_name, data):
    """Restaura nodos Slicer desde datos guardados en checkpoint.

    El mapeo data_key → attr_name permite restaurar tanto
    nombres de nodos (busca en escena) como referencias directas:

        ct_node_name   →  ct_node (busca nodo por nombre)
        pet_node_name  →  pet_node
        segmentation_node_name → segmentation_node

    Si la búsqueda por nombre exacto falla, usa _restore_node_by_type()
    que busca por tipo de nodo y palabras clave (CT, PET, Seg, sin_camilla).
    """
    restore_map = {
        "ct_node": "ct_node",
        "pet_node": "pet_node",
        "segmentation_node": "segmentation_node",
        "ct_node_name": "ct_node_name",
        "pet_node_name": "pet_node_name",
        "ct_masked_node_name": "ct_masked_node_name",
    }
    for data_key, attr_name in restore_map.items():
        if data_key in data and data[data_key] is not None:
            if data_key.endswith("_name"):
                # Buscar nodo por nombre en la escena de Slicer
                try:
                    node = slicer.util.getNode(data[data_key])
                    actual_attr = data_key.replace("_name", "_node")
                    if hasattr(self, actual_attr):
                        setattr(self, actual_attr, node)
                except Exception:
                    self._restore_node_by_type(data_key, data[data_key])
            else:
                setattr(self, attr_name, data[data_key])

    # Restaurar visualización médica si hay nodos disponibles
    if self.ct_node or self.pet_node:
        setup_medical_views(
            ct_node=self.ct_node,
            ct_masked_node=self.ct_masked_node,
            pet_node=self.pet_node,
            segmentation_node=self.segmentation_node,
            layout_name=self.pipeline_config.get("views", {}).get("layout"),
            pet_opacity=self.pipeline_config.get("views", {}).get("pet_opacity", 0.35),
            link_slices=self.pipeline_config.get("views", {}).get("link_slices", True),
        )
```

Además, al iniciar el pipeline se carga la escena `.mrb` guardada si existe:

```python
def _load_scene_if_needed(self):
    """Carga la escena 3Dosim.mrb guardada si hay checkpoints previos.

    Solo carga si hay al menos un checkpoint de los pasos críticos
    (load_dicom, remove_couch, resample_pet, segment). La escena
    contiene todos los nodos de volumen y segmentación necesarios.
    """
    scene_path = os.path.join(self.scene_output_dir, "3Dosim.mrb")
    if not os.path.exists(scene_path):
        return

    checkpoint_keys = [
        self.STEP_LOAD_DICOM, self.STEP_REMOVE_COUCH,
        self.STEP_RESAMPLE_PET, self.STEP_SEGMENT,
    ]
    needs_restore = any(self.checkpoint.is_completed(k) for k in checkpoint_keys)
    if not needs_restore:
        return

    success = slicer.util.loadScene(scene_path)
    if success:
        self._scan_scene_for_nodes()
```

---

## Guardado de escena y checkpoint

El pipeline guarda la escena `.mrb` en los siguientes puntos (según `save_scene.frequency`):

| Frecuencia | Puntos de guardado | Uso recomendado |
|------------|-------------------|-----------------|
| `minimal` (default) | post-carga DICOM y post-body segmentation | Producción, mínimo overhead |
| `all` | Tras cada paso | Debug, desarrollo |

El guardado de escena es independiente del checkpoint JSON: el checkpoint guarda **qué** pasos se completaron, la escena guarda **todo el estado visual** de Slicer.

```python
def _save_scene(self, tag=None, force=False):
    """Guarda la escena 3Dosim.mrb.

    Una sola escena que se sobrescribe acumulando cada paso.
    Workaround para Windows: setea TMP/TEMP a C:\\tmp (path corto)
    para evitar error NRRD write por path muy largo.

    Args:
        tag: Identificador opcional para el paso (log).
        force: Si True, guarda siempre ignorando config frequency.
    """
    freq = self.pipeline_config.get("save_scene", {}).get("frequency", "minimal")
    if not force and freq == "minimal":
        allowed = {"01_post_load_dicom", "12_segment_body"}
        if tag not in allowed:
            return

    # Workaround path corto para Windows
    old_tmp = os.environ.get("TMP", "")
    old_temp = os.environ.get("TEMP", "")
    try:
        os.environ["TMP"] = r"C:\tmp"
        os.environ["TEMP"] = r"C:\tmp"
        success = slicer.util.saveScene(filepath)
    finally:
        os.environ["TMP"] = old_tmp
        os.environ["TEMP"] = old_temp
```

---

## Resumen post-pipeline

Al finalizar (o interrumpir con SIGINT), `PipelineMod1._report()` imprime un resumen que incluye el estado de cada paso:

```
======================================================================
 REPORTE FINAL - MODULO 1
======================================================================
Pasos totales:     12
Exitosos:          12
Desde checkpoint:  5
Fallos:            0
DETALLE DE PASOS:
----------------------------------------------------------------------
  + check_slicer                                    1.2s
  + Cargando imagenes DICOM                         3.4s
  + Eliminando camilla y aire                       1.0s
  + Re-muestreando PET a geometria CT               5.2s
  + Mostrando fusion CT+PET registrada              0.8s
  + Anonimizando imagenes                           2.1s
  + Exportando metadata DICOM a JSON                0.5s
  + Segmentando (totalsegmentator)                 173.4s
  + Validacion medica de la segmentacion            12.3s
  + Tumor sintetico esferico en higado              3.2s
  + Higado sano (higado - tumor)                    1.1s
  + Exportar labelmap dosimetrica                  45.6s
----------------------------------------------------------------------
Output: C:\MAT\3Dosim\ai-pipe
 RESULTADO: TODOS LOS PASOS EXITOSOS
======================================================================
```

---

## Control de calidad

### Verificaciones de integridad del checkpoint

| Verificación | Método | Acción si falla |
|-------------|--------|-----------------|
| Archivo JSON existe y es válido | `json.load()` dentro de `_load()` | Retorna estado vacío (empezar de cero) |
| Versión de checkpoint coincide | `state["version"] == CHECKPOINT_VERSION` | Warning + reinicio de estado |
| Nodos referenciados existen en escena | `slicer.util.getNode()` en `_restore_step_state()` | Búsqueda por tipo y palabras clave |
| Escena `.mrb` existe y es cargable | `slicer.util.loadScene()` | Continuar sin escena (nodos se restauran desde checkpoint) |

### Reglas de consistencia

1. **Un paso en `completed` no se re-ejecuta**: si el código del paso cambió entre ejecuciones, el usuario debe usar `--reset` para forzar re-ejecución.
2. **El checkpoint se guarda después de CADA paso**: en disco inmediatamente después de `mark_completed()`.
3. **SIGINT también guarda**: el checkpoint persiste el estado hasta el último paso `completed` antes de la interrupción.
4. **No hay rollback automático**: si un paso falla, el checkpoint queda en el estado anterior (el paso fallido no se marca como `completed`).
5. **Validación médica forzada**: aunque el checkpoint indique que `validate_segmentation` está completado, si `pipeline.force_validation_on_restore = true` el diálogo de validación se muestra igualmente.

### Limitaciones conocidas

- El checkpoint no guarda el array de datos de los volúmenes (solo nombres de nodos). La restauración exitosa depende de que la escena `.mrb` contenga los datos.
- Si se elimina manualmente la escena `.mrb` pero el checkpoint JSON sobrevive, la restauración de nodos puede fallar (con fallback a búsqueda por tipo).
- El checkpoint versionado (`version: 1`) no tiene migración automática: cambios mayores en el schema requieren `--reset`.
