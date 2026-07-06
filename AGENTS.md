# 3Dosim v4 - Dosimetria 3D para Medicina Nuclear

## Repositorio contenedor

Este repo (`3Dosim_v4/`) es el repositorio activo de desarrollo, contenido dentro de `C:\programas\3Dosim/`.

| Contexto | Valor |
|----------|-------|
| **Repo raíz** | `C:\programas\3Dosim/` — contenedor sin ramas propias |
| **Repo activo** | `C:\programas\3Dosim/3Dosim_v4/` — rama `mod3` |
| **Rama activa** | `mod3` (recién creada desde `carteles`, contiene todas las features) |
| **Ramas legado** | `carteles` (features previas), `main` (estable) |
| **Entry point real** | `launcher/app.py` (NO los módulos Slicer del dropdown) |
| **Legacy** | `3Dosim_v_3.14/` — NO modificar |

Para comandos coordinados entre ambos repos, ver `CLAUDE.md` en la raíz.

## Stack
- MATLAB (.m) - modulos principales
- Python (.py) - Slicer module, registro
- 3D Slicer integration

## Modulos
1. **modulo 1** - Segmentacion y registro de imagenes (CT/SPECT)
2. **modulo 2** - Generacion de input MCNP (geometria voxelizada, fuentes, materiales)
3. **modulo 3** - Post-procesamiento (dosis, DVH, BED, EUD, NTCP, TCP)
4. **kernel** - Calculo de kernel de dosis
5. **espectro** - Procesamiento de espectros
6. **estep** - Estimacion de step size

## SlicerDosim - Estructura compartimentada (3DSlicerModule)

```
Modules/Scripted/SlicerDosim/
├── SlicerDosimLib/
│   ├── __init__.py              # Exporta todas las clases publicas
│   ├── config.py                # [NUEVO] TissueConfig - carga tissue_config.json
│   ├── phantom_segmentation.py  # [MODIFICADO] Usa TissueConfig en vez de hardcodes
│   ├── segmentation.py          # Sin cambios
│   ├── registration.py          # Sin cambios
│   ├── mcnp_generator.py        # [MODIFICADO] Orquestador, delega a sub-modulos
│   ├── mcnp_materials.py        # [NUEVO] Indice phantom -> material MCNP
│   ├── mcnp_geometry.py         # [NUEVO] LIKE n BUT, RPP, lattice fill
│   ├── mcnp_source.py           # [NUEVO] SDEF desde PET
│   ├── mcnp_tallies.py          # [NUEVO] FMESH4, F6, modo, NPS
│   ├── dosimetry.py             # [MODIFICADO] Usa MCTALParser
│   ├── mctal_parser.py          # [NUEVO] Parseo de output MCNP
│   ├── dvh_analysis.py          # Sin cambios
│   └── utils.py                 # Sin cambios
├── Resources/
│   └── Config/
│       └── tissue_config.json   # [NUEVO] Config unica de tejidos/materiales
└── Testing/
    └── PipelineOrchestrator/    # (ver abajo)
```

## Modulos de Slicer (entradas separadas en dropdown 3Dosim)

| Categoria | Modulo | Funcion |
|---|---|---|
| 3Dosim | SlicerDosim | Modulo 1: Carga, segmentacion, registro |
| 3Dosim | SlicerDosimMod2 | Modulo 2: Generacion MCNP |
| 3Dosim | SlicerDosimMod3 | Modulo 3: Analisis dosimetrico |

Todos los modulos comparten SlicerDosimLib (en SlicerDosim/).

## Estado actual de trabajo

### Refactor SlicerDosim (COMPLETADO)
- Creado `tissue_config.json` con tejidos, colores, HU ranges y composiciones MCNP
- Creado `config.py` (TissueConfig singleton) que centraliza toda la config
- Modulo 2 (MCNP) dividido en 4 sub-modulos compartimentados: materials, geometry, source, tallies
- Modulos separados en dropdown: SlicerDosim (mod1), SlicerDosimMod2 (mod2), SlicerDosimMod3 (mod3)
- `phantom_segmentation.py` ahora usa TissueConfig en vez de dicts hardcodeados
- `dosimetry.py` ahora usa `mctal_parser.py` real en vez de placeholder
- `__init__.py` y `CMakeLists.txt` actualizados

### Pipeline Orchestrator + Features (COMPLETADO - May 2026)
`test_pipeline_orchestrator.py` mejorado con:

| Feature | Descripcion |
|---|---|
| ✅ **CheckpointManager** | Guarda estado en JSON tras cada paso. Si se corta, al reiniciar retoma desde el ultimo checkpoint. `--reset` para empezar fresco. |
| ✅ **Anonimizacion** | Al cargar DICOM, copia a directorio temporal y limpia tags (PatientName, PatientID, etc) con pydicom. Los nodos en Slicer se renombran. |
| ✅ **Sacar camilla + aire** | Threshold HU>-200 + cierre morfologico + componente conectada mas grande + eliminacion de camilla por corte axial. Aplica mascara al CT. |
| ✅ **Barra de progreso** | QProgressDialog durante TotalSegmentator con pasos y mensaje de "esta funcionando". Tambien muestra progreso en status bar de Slicer. |
| ✅ **Validacion medica** | Dialogo modal Qt con botones SI/NO. No continua sin aprobacion medica explicita. Mensaje claro de lo que se va a generar. |
| ✅ **Git commit prompt** | Al finalizar OK, pregunta si hacer commit. Busca el repo git, hace `git add -A` y `git commit -m "mensaje"`. |
| ✅ **Reporte mejorado** | Muestra tiempos, checkpoints reutilizados, errores, directorios de salida. Retorna bool para control de flujo. |

### Flujo actual del pipeline
```
1. check_slicer       → Verifica Slicer + paths de modulos
2. load_dicom         → Carga CT+PET con DB temporal
3. anonymize          → Anonimiza tags DICOM + renombra nodos
4. remove_couch_air   → Elimina camilla y aire del CT
5. segment_phantom    → TotalSegmentator con QProgressDialog
6. validate_segmentation → ⛔ MEDICO DEBE APROBAR
7. export_nifti       → Exporta a NIfTI
8. generate_mcnp      → Genera entrada MCNP + verifica .i
9. report + commit    → Reporte final + opcion de commit git
```

### PipelineOrchestrator - Estructura modular (NUEVA)
El pipeline de test ahora vive en su propia carpeta con arquitectura promocionable:

```
Testing/PipelineOrchestrator/
├── __init__.py              # Exporta API publica
├── main.py                  # Entry point CLI (argparse + --reset)
├── pipeline.py              # PipelineTestOrchestrator (orquestador)
├── checkpoint.py            # CheckpointManager (estado JSON persistente)
├── anonymize.py             # Anonimizacion DICOM con pydicom
├── couch_remover.py         # Eliminacion camilla + aire (threshold + morfologia)
├── segmentation.py          # TotalSegmentator + barra progreso + phantom sintetico
├── validation.py            # Dialogo Qt de validacion medica obligatoria
├── mcnp_builder.py          # Generacion + verificacion entrada MCNP
├── git_commit.py            # Prompt de commit git al finalizar
└── utils.py                 # Logger, paths, show_progress()
```

`test_pipeline_orchestrator.py` ahora es un wrapper delgado que importa y ejecuta `PipelineOrchestrator.main.main()`.

### Proximo paso promocion
Cuando el orquestador este maduro, mover la carpeta completa a:
```
SlicerDosimLib/orchestrator/    ← parte oficial de la herramienta
```
Y los modulos de Slicer (SlicerDosim, SlicerDosimMod2, SlicerDosimMod3) lo importaran desde ahi.

### Pendiente
- Agregar ruta en Slicer: Edit > Settings > Modules > Additional paths > `...\Modules\Scripted`
- Probar que los 3 modulos aparezcan bajo "3Dosim"
- Ejecutar `test_pipeline_orchestrator.py` dentro de Slicer con datos reales

## Datos de ejecucion (guardados para no repetir)

| Item | Valor |
|---|---|
| **Slicer.exe** | `C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe` |
| **Paciente 2** | `C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2` |
| **Pipeline entry** | `3DSlicerModule/SlicerDosim/Testing/PipelineOrchestrator/main.py` |
| **Entry legacy** | `3DSlicerModule/SlicerDosim/Testing/Python/test_pipeline_orchestrator.py` |
| **Directorio raiz** | `C:\programas\3Dosim\3Dosim_v_3.14` |
| **Repo git** | En el directorio raiz |
| **Modulos Slicer** | `3DSlicerModule/SlicerDosim/Modules/Scripted/` (SlicerDosim, SlicerDosimMod2, SlicerDosimMod3) |

### Comando para ejecutar el pipeline
```bash
& "C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe" --python-script "C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim\Testing\PipelineOrchestrator\main.py" --data-dir "C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2"
```

### Para reiniciar checkpoints
```bash
& "C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe" --python-script "C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim\Testing\PipelineOrchestrator\main.py" --data-dir "C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2" --reset
```

## Sesion 17-May 14:00 — Checkpoint (Actualizado)

### Log (sesiones acumuladas)
1. **Refactor externo→interno**:
   - `anonymize.py`: Sin pydicom, solo renombra nodos en escena
   - `pipeline.py`: Sin urllib/exec para MCP
2. **Flags**: `--force-cpu` (default True), `--segmenter {simple|totalsegmentator}`
3. **Screenshots + escenas MRB** por cada paso
4. **Consola interactiva** habilitada por defecto
5. **`ejecutar_pipeline.bat`**: launcher que mata Slicer y ejecuta pipeline
6. **BUG TS CORREGIDO**: `slicer.cli.run()` NO funciona con TS (ScriptedLoadableModule). Solucion: `TotalSegmentatorLogic.process()` directa:
   ```python
   from TotalSegmentator import TotalSegmentatorLogic
   logic = TotalSegmentatorLogic()
   logic.setupPythonRequirements()
   logic.process(inputVolume=ct_node, outputSegmentation=seg_node,
                 fast=True, cpu=True, task="total", interactive=False)
   ```
   **TS FUNCIONA** (probado: 173s, segmentacion completa con 104 organos).
7. **PERSISTENCIA AGREGADA**:
   - Cada paso guarda `data_func()` en checkpoint (nodos, paths, parametros)
   - `_restore_step_state()` restaura nodos al retomar desde checkpoint
   - `pipeline_results.json` en output_dir con historial completo de ejecuciones
8. **ESCENA GUARDADA TRAS CADA PASO**: `.mrb` con timestamp en `scenes/` tras carga_dicom, remove_couch, fusion, anonymize, segment, validate, export_nifti, generate_mcnp
9. **`kill_existing_slicer()` REWRITE**: ahora usa PowerShell `Get-Process`/`Stop-Process` en vez de tasklist (mas robusto, captura cualquier Slicer.exe)
10. **TS MODULE VISIBILITY**: `slicer.util.selectModule("TotalSegmentator")` antes de ejecutar TS para que el usuario vea progreso
11. **VALIDACION MEDICA NO MODAL**: El dialogo ya no bloquea Slicer. El medico puede:
    - Navegar slices axial/sagital/coronal
    - Ocultar PET (slider de opacidad)
    - Rotar vista 3D
    - Examinar segmentacion
    Luego hacer clic en APROBAR o RECHAZAR
12. **INSTRUCCIONES STOP-BEFORE-SEGMENT**: Actualizadas para `TotalSegmentatorLogic.process()` en vez de `slicer.cli.run()`

### Archivos modificados en esta sesion

| Archivo | Cambio |
|---|---|
| `segmentation.py` | `slicer.cli.run()` → `TotalSegmentatorLogic.process()` + switch a modulo TS |
| `validation.py` | Dialogo NO modal con instrucciones para medico, sin bloquear Slicer |
| `pipeline.py` | `_save_scene()` tras cada paso, `data_func` en checkpoints, `_restore_step_state()`, `_save_results_json()`, stop-before-segment actualizado |
| `utils.py` | `kill_existing_slicer()` rewrite con PowerShell |
| `AGENTS.md` | Actualizado |

### Pendiente
- Probar pipeline completo con TS y validacion medica (click SI)
- Confirmar `pipeline_results.json` con historial
- Confirmar que escenas .mrb se guardan tras cada paso
- Probar que `kill_existing_slicer()` cierra otros Slicer (correr con Slicer abierto)
- Si OK, git commit

### Lecciones aprendidas
- `TotalSegmentator` NO es CLI module. NO se usa con `slicer.cli.run()`. API correcta: `TotalSegmentatorLogic.process()`
- Dialogo modal bloquea Slicer → el medico no puede navegar. Solucion: `setModal(False)` + `show()` + `processEvents()` loop
- `tasklist` en Slicer a veces no detecta otros procesos Slicer. `PowerShell Get-Process` es mas confiable
- Guardar escena .mrb tras cada paso es esencial para BD futura y debug
- El pipeline termina despues de validacion medica. Los pasos MCNP se agregaran despues.
- Los screenshots se guardan en `resultados_test/screenshots/` y las escenas en `resultados_test/scenes/`
- `pipeline_results.json` en `resultados_test/` con historial completo de ejecuciones

### Archivos generados/fsdfsdfsdf

| Archivo | Proposito |
|---|---|
| `totalsegmentator_config.jsonc` | Config externa de TS (task, fast, force_cpu, subset, etc.) |
| `phantom_builder.py` | Paso futuro: convertir segmentacion TS → phantom tejidos |
| `source_builder.py` | Paso futuro: definir fuente desde PET |
| `geometry_builder.py` | Paso futuro: construir geometria voxelizada |
| `tally_builder.py` | Paso futuro: configurar detectores MCNP |

### Directorios de salida
- **Screenshots**: `resultados_test/screenshots/` — 6 PNG por ejecucion
- **Escenas MRB**: `resultados_test/scenes/` — 6 .mrb con timestamp
- **Checkpoints**: `resultados_test/.checkpoints/pipeline_checkpoint.json`
- **Historial BD**: `resultados_test/pipeline_results.json` (historial acumulado)

### Comandos
```bash
# Via batch (cierra Slicer automaticamente)
C:\programas\3Dosim\3Dosim_v_3.14\ejecutar_pipeline.bat

# Directo (segmentacion simple - rapido)
& "C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe" --python-script "C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim\Testing\PipelineOrchestrator\main.py" --data-dir "C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2" --segmenter simple --reset

# Directo (TotalSegmentator via TotalSegmentatorLogic.process())
& "C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe" --python-script "C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim\Testing\PipelineOrchestrator\main.py" --data-dir "C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2" --segmenter totalsegmentator --force-cpu --reset

# Reiniciar checkpoints
& "C:\Users\Sebastian\AppData\Local\slicer.org\Slicer 5.8.1\Slicer.exe" --python-script "C:\programas\3Dosim\3Dosim_v_3.14\3DSlicerModule\SlicerDosim\Testing\PipelineOrchestrator\main.py" --data-dir "C:\MAT\3Dosim\pacientes-\pacientes\Paciente_2" --reset --segmenter simple
```

## AI Supervisor (NUEVO - May 2026)
Revisión inteligente paso a paso del pipeline usando DeepSeek/OpenRouter.

### Funcionamiento
- Despues de cada paso exitoso, se recolecta el estado actual del pipeline
- Se envian metricas a la IA para obtener feedback
- La respuesta aparece en **cyan** en la consola (no bloquea, va en paralelo)
- **Pre-verificacion**: reglas duras detectan anomalias antes de consultar a la IA

### Pre-verificacion (reglas de calidad inmediatas)
| Regla | Que detecta |
|---|---|
| Metodo simple (threshold) | Advertir que no es suficiente para dosimetria |
| Pocos segmentos (<=2) | Threshold sin etiquetado de organos |
| Voxels fuera del cuerpo | Segmentacion incluye aire/camilla |

### Archivos
- `ai_supervisor.py` - modulo principal (pre-verificacion + consulta IA)
- `deepseek_client.py` - cliente OpenRouter (multi-modelo)
- `comandos.py` - comandos `ai`, `modelo`, `modelos` en consola interactiva

### Archivos nuevos/modificados en rama `ai`
| Archivo | Cambio |
|---|---|
| `ai_supervisor.py` | NUEVO - revision IA post-paso |
| `comandos.py` | Agregados comandos IA + color cyan para respuestas |
| `deepseek_client.py` | Agregado timeout 30s |
| `pipeline.py` | Integrado AI supervisor en cada paso |
| `quick_test.py` | Script para prueba rapida solo CT+PET + consola |

## Sesion 19-May 15:00 — Cambios realizados

### Resumen de cambios

| Archivo | Cambio |
|---|---|
| `tumor_segmentation.py` | Refactor completo: sacado SUV threshold. Nueva funcion `prepare_tumor_segmentation()`: extrae higado de TS, calcula bounding box + padding 10mm, crea nodo de tumor vacio "Tumor_MONAI", cambia al modulo MONAI Label. |
| `tumor_validation.py` | Dialogo actualizado: instrucciones para usar MONAI Label (DeepEdit) en vez de solo revisar mascara. |
| `pipeline.py` | Eliminada validacion medica de fusion + eliminados builders (phantom_builder, source_builder, geometry_builder, tally_builder, mcnp_builder) + imports, atributos y steps correspondientes. `_segment_tumor()` ahora llama a `prepare_tumor_segmentation()`. |
| `agente.py` | Fix corte abrupto: `_load()` detecta status "busy"/"waiting_approval" y resetea a "idle" con flag `interrupted=True`. Agregado campo `interrupted` al estado inicial. |
| `__init__.py` (PipelineOrchestrator) | Documentacion actualizada. |

### Flujo actual del pipeline
```
1. check_slicer
2. load_dicom
3. remove_couch_air
4. resample_pet (Elastix rigid)
5. show_fusion
6. anonymize
7. segment_phantom (TotalSegmentator)
8. validate_segmentation (medico)
9. prepare_tumor (crop ROI hepatica + nodo vacio + MONAI Label)
10. validate_tumor (medico usa MONAI + APROBAR)
```

### Pendiente
- Probar pipeline completo dentro de Slicer con Paciente_2
- MONAI Label debe estar instalado como extension de Slicer + server corriendo
- Si OK, git commit

## Sesion 19-May 16:30 — Bugfixes post-segunda-prueba

### Cambios realizados

| Archivo | Cambio |
|---|---|
| `comandos.py` | Agregado metodo `log_ai()` para mostrar respuestas de IA en color cyan. Antes `ai_supervisor.py:175` tiraba `AttributeError: 'ConsolaComandos' object has no attribute 'log_ai'`. |
| `pipeline.py` | `_save_scene()`: workaround para error NRRD write por path muy largo en Windows. Antes de guardar, setea TMP/TEMP a `C:\tmp` (path corto), restaura despues. |

### Estado actual
- **Bug #1 (log_ai)**: RESUELTO — `ConsolaComandos.log_ai()` agregado
- **Bug #2 (scene MRB)**: RESUELTO — workaround TMP path corto
- Pipeline listo para prueba completa con `--segmenter totalsegmentator` (sin `--stop-before-segment`)

## Sesion 19-May 12:00 — MONAI Label server auto-start + simplificacion

### Problema
`tumor_segmentation.py` intentaba usar `MONAILabelWidget` de Slicer, que **no esta instalado**
(no hay extension MONAI Label en Slicer, solo MONAIAuto3DSeg). Ademas, el servidor MONAI Label
debia iniciarse manualmente.

### Solucion
1. **`monailabel_server.py`** (NUEVO): wrapper pragmatico que:
   - Verifica si el servidor ya corre via `check_server()` (HTTP GET `/info/`)
   - Si no, crea app minima funcional (`main.py` con `MONAILabelApp` subclass)
   - Lanza `PythonSlicer.exe -m monailabel.main start_server` como subproceso
   - Espera hasta timeout a que responda
   - Devuelve gracefulmente si falla (no bloquea el pipeline)

2. **`tumor_segmentation.py`** (SIMPLIFICADO):
   - ❌ Eliminado `_configure_monailabel_widget()` (dependia de MONAILabelWidget)
   - ❌ Eliminado `_check_monailabel_server()` (redundante con `check_server()`)
   - ✅ Llama `start_server(timeout=30)` al inicio
   - ✅ Crea nodo de tumor vacio directamente (sin widget)
   - ✅ Muestra URL http://localhost:8000 si el server arranco
   - ✅ Da instrucciones manuales si no

3. **`main.py`**: Agregado `'simple'` a `choices` de `--segmenter`

### Server MONAI Label funcional
```json
GET http://127.0.0.1:8000/info/
{
  "name": "3Dosim DeepEdit",
  "description": "Liver tumor segmentation with DeepEdit",
  "labels": ["tumor"],
  "models": {}
}
```
- **Modelos vacios** (sin DeepEdit real) — suficiente para interfaz web
- Para DeepEdit real: descargar pesos entrenados y agregar a `init_infers()`
- Server arranca en **~7 segundos** (testeado)

### Cambios realizados

| Archivo | Cambio |
|---|---|
| `monailabel_server.py` | NUEVO — wrapper inicio automatico MONAI Label |
| `tumor_segmentation.py` | Simplificado: integra `start_server()`, elimina widget |
| `main.py` | Agregado `'simple'` a segmenter choices |
| `__init__.py` | Documentacion actualizada |

### Bug conocido
- **MONAILabelWidget no existe en Slicer**: solo MONAIAuto3DSeg instalado como extension.
  Para integracion nativa Slicer-MONAILabel, la extension debe instalarse desde Extension Manager.
  Mientras tanto, el pipeline crea nodo vacio y da instrucciones web.

### Pendiente
- Probar pipeline completo dentro de Slicer con Paciente_2
- Para DeepEdit real: descargar modelo pre-entrenado y agregar `InferTask`
- Si se necesita integracion nativa Slicer: instalar extension MONAI Label

## Sesion 21-May 12:00 — Limpieza general del proyecto

### Resumen de cambios
Commit: `aed4462` - "cleanup: eliminar builders huerfanos, docs duplicados, pycache, basura"

| Fase | Accion | Archivos |
|------|--------|----------|
| Seguridad | `.gitignore` actualizado | Ahora ignora `.env`, `*.mat`, `*.asv`, `*.xlsx`, `*.docx`, `*.pdf`, `*.jpg`, `*.log` |
| Seguridad | Eliminar `deepseek.env` | Duplicado exacto de `.env` |
| Seguridad | Eliminar `nul` | Archivo accidental de redireccion shell |
| Seguridad | Eliminar `pipeline_run.log` | Vacio (0 bytes) |
| Python | Eliminar 5 builders huerfanos | `phantom_builder.py`, `source_builder.py`, `geometry_builder.py`, `tally_builder.py`, `mcnp_builder.py` |
| Python | Eliminar wrapper legacy | `Testing/Python/test_pipeline_orchestrator.py` |
| Python | Remover `__pycache__` de git | 34 archivos `.pyc` eliminados del tracking |
| Docs | Eliminar MD duplicado | `pipeline_monai_total_segmentator_slicer_dosimetria_hepatica-2.md` (+97 lines extras nada mas) |
| Docs | Eliminar doc personal | `notebooklm_deepseek_conexion.md` (notas no tecnicas) |

### Pendiente (no resuelto)
- API key en `.env` expuesta en git history — considerar rotarla en OpenRouter
- Los directorios MATLAB (`modulo 1/2/3`, `otros/`, `kernel/`, etc.) no se tocaron

### Pendiente (no resuelto)
- API key en `.env` expuesta en git history — considerar rotarla en OpenRouter
- Los directorios MATLAB (`modulo 1/2/3`, `otros/`, `kernel/`, etc.) no se tocaron

Commit: `b6aa7a8` - "eliminar test extras fusion_test, fusion_simple, test_ts_standalone, quick_test"
- Eliminados 4 test extras de PipelineOrchestrator
- Trackeados ai_supervisor.py, pet_registration.py, pipeline_fusion.py (nuevos)
- Committed cambios pendientes de sesiones anteriores (8 archivos .py)

## Reglas importantes

- **NO modificar archivos dentro de `3Dosim_v_3.14/`** — esa versión es estable/legacy. Todo el desarrollo activo es en `3Dosim_v4/`.

## Comandos utiles
- `/remember [tag] mensaje` - Guardar progreso en memoria persistente
# UPDATE_PIPELINE_VISUALIZATION_AND_SCENES.md

## Objetivo

Actualizar el pipeline de `3Dosim` para mejorar persistencia visual, navegacion medica y coherencia del flujo post-TotalSegmentator.

---

# Decision arquitectonica

## IMPORTANTE

NO crear un nuevo `.md`.

Integrar estos cambios dentro de:

* `AGENTS.md`

Porque:

* ya contiene el estado real del proyecto
* el pipeline evoluciona rapidamente
* evita divergencia entre documentos
* el modelo ya usa AGENTS.md como contexto operativo principal

Agregar una nueva seccion:

```md
## Sesion 22-May — Visualizacion 3D + escenas + validacion
```

---

# Cambios requeridos

## 1. Persistencia de escenas en JSONC

### Objetivo

Las escenas `.mrb` deben guardarse en:

```txt
C:\MAT\3Dosim\ai-pipe\imagenes
```

NO usar rutas hardcodeadas separadas del sistema de configuracion.

La ruta debe integrarse dentro del JSONC global/configuracion persistente del pipeline.

---

## Requerimiento tecnico

Agregar variable nueva:

```jsonc
{
  "scene_output_dir": "C:/MAT/3Dosim/ai-pipe/imagenes"
}
```

Integrarla en:

* config loader
* checkpoint manager
* save_scene()
* pipeline_results.json
* escenas automaticas

NO duplicar configuraciones.

Toda ruta debe salir del JSONC central.

---

# 2. Visualizacion 3D automatica de cortes

## Objetivo

Despues de:

* carga DICOM
* fusion PET/CT
* segmentacion
* validacion

el usuario debe ver:

* rendering 3D activo
* slices visibles
* cortes sincronizados

---

## Requerimientos

Activar automaticamente:

```python
threeDView.resetFocalPoint()
```

Mostrar:

* axial
* sagittal
* coronal
* vista 3D

NO dejar solo slices 2D.

---

## Comportamiento esperado

El medico debe poder:

* rotar anatomia
* navegar cortes
* inspeccionar organos
* ver superposicion PET/CT
* validar segmentacion

sin configuracion manual.

---

# 3. Activar Link Slice View automaticamente

## Objetivo

Sincronizar navegacion entre cortes.

Cuando el medico cambie:

* axial
* sagittal
* coronal

las vistas deben mantenerse sincronizadas.

---

## Requerimiento tecnico

Activar automaticamente:

```python
sliceCompositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
for node in sliceCompositeNodes:
    node.SetLinkedControl(True)
```

Debe ejecutarse:

* luego de cargar estudios
* luego del registro PET/CT
* luego de segmentacion
* luego de restaurar checkpoints

---

# 4. Restaurar validacion luego de TS

## Objetivo

Despues de generar anatomia con TotalSegmentator:

* SIEMPRE ejecutar validacion medica

NO continuar automaticamente.

---

## Flujo correcto

```txt
segment_phantom (TS)
↓
visualizacion automatica 3D + slices
↓
link slice enabled
↓
validate_segmentation (obligatoria)
↓
prepare_tumor
```

---

## IMPORTANTE

La validacion:

* NO debe eliminarse
* NO debe quedar opcional
* NO debe bypassarse por checkpoints corruptos
* debe ejecutarse incluso al restaurar estado

---

# 5. NO avanzar con modulo MCNP

## Decision temporal

NO implementar:

* MCNP builder
* geometry builder
* tally builder
* source builder
* export MCNP
* pipelines MCNP

Todo el desarrollo debe enfocarse en:

* visualizacion clinica
* segmentacion
* flujo medico
* validacion
* persistencia
* navegacion
* MONAI workflow

---

## Reglas

Si existe codigo legacy MCNP:

* mantenerlo aislado
* no expandirlo
* no integrarlo nuevamente al pipeline actual

No agregar nuevos pasos MCNP.

---

# Recomendaciones de implementacion

## Crear helper centralizado

```python
setup_medical_views()
```

Responsabilidades:

* activar layout medico
* activar 3D
* activar linked slices
* reset focal point
* mostrar segmentaciones
* restaurar overlays PET/CT

Llamarlo desde:

* load_dicom
* resample_pet
* show_fusion
* segment_phantom
* validate_segmentation
* restore checkpoint

---

# Resultado esperado

El pipeline debe comportarse como una herramienta clinica navegable:

* escenas persistentes
* recuperacion estable
* visualizacion automatica
* slices sincronizados
* validacion medica obligatoria
* workflow orientado a segmentacion/anatomia
* sin dependencia MCNP

## Sesion 22-May — Visualizacion 3D + escenas + validacion

### Cambios realizados

| Archivo | Cambio |
|---------|--------|
| `pipeline_config.jsonc` | NUEVO — Config central con `scene_output_dir: C:/MAT/3Dosim/ai-pipe/imagenes`, config de vistas (`layout`, `pet_opacity`, `link_slices`, window/level), flags de pipeline |
| `views.py` | NUEVO — `setup_medical_views()`: helper centralizado que activa layout medico, volume rendering 3D para CT y PET, fusion CT+PET en slices, slices linkeados y reset de focal point. `_enable_volume_rendering()` activa el volume rendering 3D con RayCast para que las imagenes sean visibles en la vista 3D. Tambien `load_pipeline_config()`: carga JSONC con merge profundo y defaults. |
| `pipeline.py` | MODIFICADO — Importa `views`, carga config al init, usa `scene_output_dir` del JSONC en `_save_scene()`, llama `setup_medical_views()` tras cada paso critico (load_dicom, resample_pet, segment, validate), y al restaurar checkpoint. `_do_validation()` AHORA llama a `validation.validate_segmentation()` real (no mas auto-approve). Eliminadas referencias a tumor (tumor_segmentation, tumor_validation, MONAI). `_save_scene()` ahora usa un solo archivo fijo `3Dosim_scene.mrb` que se sobrescribe en cada save (incremental). |
| `__init__.py` | Actualizada documentacion con views.py y pipeline_config.jsonc |

### Flujo actual con visualizacion medica
```
1. check_slicer
2. load_dicom          → setup_medical_views() [CT+PET con volume rendering 3D]
3. remove_couch_air
4. resample_pet        → setup_medical_views() [fusion actualizada]
5. show_fusion
6. anonymize
7. segment_phantom     → setup_medical_views() [con segmentacion 3D]
8. validate_segmentation → setup_medical_views() [post-validacion]
```

### Persistencia
- `scene_output_dir` configurado en `pipeline_config.jsonc`: `C:/MAT/3Dosim/ai-pipe/imagenes`
- Una sola escena `.mrb` (`3Dosim_scene.mrb`) que se sobrescribe en cada save point
- `pipeline_results.json` sigue en `resultados_test/`
- Config central evita rutas hardcodeadas

### Archivos del sistema de config
| Archivo | Proposito |
|---------|-----------|
| `pipeline_config.jsonc` | Config global del pipeline (rutas, vistas, flags) |
| `totalsegmentator_config.jsonc` | Config exclusiva de TotalSegmentator (task, fast, subset) |
| `views.py` | `setup_medical_views()` + `load_pipeline_config()` |

### Volumen rendering 3D
- `_enable_volume_rendering()` activa automaticamente el volume rendering RayCast para CT y PET
- Las imagenes son visibles en la vista 3D desde el primer `setup_medical_views()` post-carga
- Segmentacion visible en 2D (slices) y 3D simultaneamente
- Layout: ConventionalView (axial/sagital/coronal + 3D)

## Sesion 26-May — Tumor sintetico esferico + higado sano

### Cambios realizados

| Archivo | Cambio |
|---------|--------|
| `tumor_creator.py` | NUEVO — `add_synthetic_tumor()`: extrae higado de TS, calcula centroide, crea esfera de 1 cm radio (configurable via `tumor_radius_mm`), agrega segmento rojo "Tumor_Sintetico", y crea "higado_sano" = higado - tumor como segmento verde. Usa `_compute_centroid()`, `_find_nearest_liver_voxel()`, `_create_sphere_mask()` (distancia euclidiana en mm con spacing real), `_add_mask_as_segment()` (vtkOrientedImageData). |
| `pipeline.py` | MODIFICADO — Agregados pasos `STEP_ADD_TUMOR` y `STEP_HEALTHY_LIVER`. Metodos `_add_synthetic_tumor()` y `_create_healthy_liver()` integrados post-validacion medica. Cada paso con checkpoint, save_scene, screenshot, y setup_medical_views(). |
| `__init__.py` | Documentacion actualizada con tumor_creator.py |

### Flujo actual del pipeline
```
1. check_slicer
2. load_dicom
3. remove_couch_air
4. resample_pet (Elastix rigid)
5. show_fusion
6. anonymize
7. segment_phantom (TotalSegmentator)
8. validate_segmentation (medico)
9. add_synthetic_tumor (esfera 1 cm radio en higado → "Tumor_Sintetico" rojo)
10. create_healthy_liver ("higado_sano" verde = higado - tumor)
```

### Algoritmo del tumor sintetico
1. Extraer mascara del higado desde TS via `_extract_segment_mask()`
2. Calcular centroide con `_compute_centroid()` (promedio de coordenadas de voxeles)
3. Si centroide cae fuera del higado, `_find_nearest_liver_voxel()` busca el mas cercano
4. Crear esfera con `_create_sphere_mask()`: distancia euclidiana en mm desde el centro, usando espaciado real del CT (sx, sy, sz)
5. Intersectar esfera con higado (tumor solo dentro del parenquima hepatico)
6. Agregar "Tumor_Sintetico" (rojo) como segmento via vtkOrientedImageData
7. Calcular "higado_sano" = higado & ~tumor, agregar como segmento verde

## Sesion 26-May 17:00 — Pipeline completo: validacion tumor + body TS + labelmap

### Cambios realizados

| Archivo | Cambio |
|---------|--------|
| `tumor_validation.py` | MODIFICADO — `_show_tumor_validation_dialog()` ahora acepta `context` parameter para mostrar instrucciones de tumor sintetico vs manual. `validate_tumor_segmentation(context="sintetico")` pasa contexto al dialogo. |
| `pipeline.py` | MODIFICADO — Agregados 3 pasos: `STEP_VALIDATE_TUMOR` (paso 9 - validacion medica del tumor sintetico), `STEP_SEGMENT_BODY` (paso 11 - TS task='body' para contorno corporal), `STEP_EXPORT_LABELMAP` (paso 12 - exportar NIfTI+NRRD con IDs de tissue_config). Nuevos métodos: `_validate_tumor()`, `_segment_body()`, `_export_labelmap()`. Agregados `self.body_node` y `self.labelmap_dir` a `__init__`. |
| `AGENTS.md` | Documentacion actualizada |

### Flujo actual del pipeline (12 pasos)
```
 1. check_slicer
 2. load_dicom
 3. remove_couch_air
 4. resample_pet (Elastix rigid)
 5. show_fusion
 6. anonymize
 7. segment_phantom (TotalSegmentator task='total')
 8. validate_segmentation (medico)
 9. add_synthetic_tumor (esfera 1 cm radio en higado → "Tumor_Sintetico" rojo)
10. validate_tumor (medico revisa tumor + MONAI)
11. create_healthy_liver ("higado_sano" verde = higado - tumor)
12. segment_body (TotalSegmentator task='body' → "Body_Segmentation")
13. export_labelmap (NIfTI + NRRD con indices tissue_config)
```

### Detalles de implementacion

**validate_tumor (`_validate_tumor`)**:
- Llama `tumor_validation.validate_tumor_segmentation(context="sintetico")`
- Dialogo NO modal: medico navega slices, 3D, opacidad PET
- Si rechaza: pipeline se detiene con error
- Guarda checkpoint, escena, screenshot, views

**segment_body (`_segment_body`)**:
- Segundo TotalSegmentator con task='body' (config en `totalsegmentator_config_body.jsonc`)
- Crea nodo `Body_Segmentation` separado (no mezcla con nodo organos)
- Guarda como `self.body_node` para labelmap_exporter
- Si falla TS: warning, continua sin body

**export_labelmap (`_export_labelmap`)**:
- Carga `tissue_config.json` desde SlicerDosim/Resources/Config/
- Asigna indices phantom a cada segmento (30=Tejido_blando, 50=Pulmon, 80=Hueso, 90=Higado, 100=Tumor, etc.)
- Detecta y resuelve overlaps: ganador = indice mas alto
- Si body_node disponible, lo incorpora como contorno externo
- Exporta `3Dosim_labelmap.nii` y `3Dosim_labelmap.nrrd` en `output_dir/labelmaps/`

### Pendiente
- Probar pipeline completo con `--reset` para verificar todos los cambios
- Verificar que `setup_medical_views` no acepta `body_node` (confirmado: no lo usa)
- Si OK, commit

### Archivos modificados en esta sesion
| Archivo | Cambio |
|---------|--------|
| `PipelineOrchestrator/tumor_validation.py` | `_show_tumor_validation_dialog(context)` parameter agregado |
| `PipelineOrchestrator/pipeline.py` | 3 nuevos pasos + nuevos metodos + atributos `body_node`, `labelmap_dir` |

## Sesion 20-Jun — Tumor configurable: synthetic / load_file / manual

### Cambios realizados

| Archivo | Cambio |
|---------|--------|
| `pipeline_config.jsonc` | Nueva seccion `"tumor"` con mode, synthetic_radius_mm, load_file_path, manual_segment_name, create_healthy_liver |
| `tumor_creator.py` | Refactor completo: `create_tumor()` orquesta 3 modos. Nuevas funciones `_do_synthetic()`, `_do_load_file()`, `_do_manual()`, `_add_healthy_liver_segment()`, `_show_manual_tumor_dialog()`. |
| `tumor_validation.py` | Instrucciones contextuales por modo (sintetico, load_file, manual) |
| `pipeline.py` | `_add_synthetic_tumor()` reemplazado por `_add_tumor()` que lee `self.tumor_config`. `_validate_tumor(context)` acepta contexto. `_create_healthy_liver()` verifica nombres de segmento flexibles. |

### Modos de tumor

| Modo (`mode`) | Descripcion | Config clave |
|---------------|-------------|--------------|
| `"synthetic"` (default) | Esfera de N mm radio en el centroide del higado | `synthetic_radius_mm`, `liver_segment_name` |
| `"load_file"` | Carga tumor desde archivo NIfTI | `load_file_path`, `load_segment_name` |
| `"manual"` | Usuario segmenta en Slicer con Segment Editor | `manual_segment_name` |

### Configuracion ejemplo

```jsonc
"tumor": {
    "mode": "load_file",
    "load_file_path": "C:/MAT/3Dosim/pacientes-/pacientes/Paciente_2/segmentation liver/tumor.nii",
    "load_segment_name": "Tumor_Cargado",
    "create_healthy_liver": true
}
```

### Modo manual: flujo
1. Pipeline crea segmento vacio "Tumor_Manual" en la segmentacion
2. Activa modulo Segment Editor
3. Muestra dialogo NO MODAL con instrucciones
4. Medico dibuja el tumor con Paint/Scissors/Level Tracing
5. Medico hace clic en APROBAR
6. Pipeline extrae mascara y crea higado_sano

### Bug conocido
- El modo `load_file` con NIfTI de distintas dimensiones al CT intenta re-muestreo con BRAINSResample. Si falla, se muestra warning y se continua con la mascara original (puede estar desalineada).

## Sesion 29-Jun — PET DICOM reader + Fusion info dialog + TS liver_lesions setup

### Objetivo
Agregar lectura de actividad PET desde DICOM raw (replicando MATLAB `f_Rescale_Bq.m`) y mostrar diálogo informativo post-fusión con actividad en Bq, GBq, mCi, Bq/mL. También configurar TS v2.13.0 para modo `ts_liver_lesions`.

### Contexto técnico
- Proyecto activo: **v4** (`C:\programas\3Dosim\3Dosim_v4\`)
- Slicer 5.8.1 usa Python 3.9.10 — TS ≥ 2.13.0 requiere parches de compatibilidad Python 3.10.
- `liver_lesions` NO soporta modo `--fast`.
- Actividad PET debe leerse desde DICOM raw con pydicom (no confiar en nodo Slicer, que no aplica RescaleSlope/Intercept por slice).

### Instalación TS v2.13.0 + parches
- TS v2.14.0 conflictúa con nnunetv2 → se instaló v2.13.0.
- **3 parches de compatibilidad Python 3.9 aplicados**:
  1. `totalsegmentator/dicom_io.py`: `from __future__ import annotations` (sintaxis `str | None` requiere Python 3.10).
  2. `nnunetv2/training/dataloading/data_loader.py`: shim `nnUNetDataLoader` → `nnUNetDataLoaderBase`.
  3. `acvl_utils` forzado a 0.2.5 para evitar `blosc2>=3.0.0b4`.
- `tumor_creator.py`: `fast=True` → `fast=False` (liver_lesions no soporta --fast). Fix labelmap export: `ExportAllSegmentsToLabelmapNode` → `GenerateMergedLabelmapForAllSegments`.
- Slicer module GUI actualizado: dropdown TS incluye "liver: lesions" y "liver: lesions (MR)".

### Archivos nuevos

| Archivo | Descripción |
|---------|-------------|
| `PipelineOrchestrator/pet_dicom_reader.py` | Lee DICOM PET raw por slice con pydicom, aplica RescaleSlope/Intercept solo si `RescaleType == 'BQML'`, convierte mm³ → cm³, retorna actividad total Bq/GBq + estadísticas. Replica `f_Rescale_Bq.m` de MATLAB. |
| `PipelineOrchestrator/fusion_dialog.py` | QDialog NO modal con info paciente, CT, PET, actividad (Bq, GBq, mCi, Bq/mL), verificaciones (Units, rango, solapamiento, consistencia). No bloquea el pipeline. |

### Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `PipelineOrchestrator/pipeline_mod1.py` | `_show_fusion()` ahora lee actividad PET via `pet_dicom_reader.read_pet_dicom_activity()` y muestra `fusion_dialog.show_fusion_info_dialog()` NO modal. Agregado `self.pet_activity` en `__init__`. |
| `PipelineOrchestrator/pipeline_config.jsonc` | Agregado `patient_weight_kg: null` (opcional, se muestra en diálogo fusion). |
| `PipelineOrchestrator/tumor_creator.py` | `fast=True` → `fast=False` para liver_lesions. Fix labelmap export API. |
| `PipelineOrchestrator/requirements.txt` | Instrucciones de parches Python 3.9 documentadas. |
| `docs/AGENTS.md` | Actualizado. |

### Flujo actual del pipeline Mod1 (con actividad PET)
```
 1. check_slicer
 2. load_dicom
 3. remove_couch_air
 4. resample_pet (Elastix rigid + conservación actividad)
 5. show_fusion  ← AHORA: lee DICOM PET raw + muestra diálogo NO modal con actividad
 6. anonymize
 7. export_dicom_info
 8. segment_phantom (TotalSegmentator task='total')
 9. validate_segmentation_auto
10. validate_segmentation (médico)
11. add_tumor (mode: ts_liver_lesions / synthetic / load_file / manual)
12. validate_tumor (médico)
13. create_healthy_liver
14. segment_body (TotalSegmentator task='body')
15. export_labelmap (NIfTI + NRRD con IDs tissue_config)
```

### Variables de configuración nuevas
```jsonc
{
  "patient_weight_kg": null,
  "tumor": {
    "mode": "ts_liver_lesions",
    "ts_liver_lesions_segment_name": "Tumor_TS",
    "ts_liver_lesions_min_volume_cc": 1.0,
    "timeout_minutes": 0
  }
}
```

### Verificaciones del diálogo de fusión
- ✅ Unidades PET (RescaleType == 'BQML')
- ✅ Rango de actividad (0.1-50 GBq = normal)
- ✅ Dimensiones CT/PET similares
- ✅ Voxeles activos (> 100)
- ⚠️ Warnings del reader (RescaleType no BQML, errores de lectura)

## Sesion 29-Jun — Fix kernel dosis: A en GBq + sin T_mean

### Correccion critica
La dosis por convolucion con kernel **NO multiplica por T_mean** despues. El kernel.mat
ya incluye `t * Actividad` (t = 1/lambda = 332916 s, Actividad = 1e9 = 1 GBq).

### Flujo exacto MATLAB
```matlab
Kernel = Kernel / sum(Kernel(:));        % normalizar
DosisK = imfilter(A, Kernel, ...);       % convolucion
DosisK = DosisK .* IND_liver_tumor;      % mascara
% NO hay DosisK * t
```
donde `A = PET .* 1e-9` (GBq/voxel).

### Cambios

| Archivo | Cambio |
|---------|--------|
| `run_dosimetry_from_scene.py` | A en GBq/voxel (`activity_gbq` en vez de `activity_bq`). Sin T_mean post-convolucion. |
| `dose_kernel.py` | Creado. Separacion de carga de kernel. Docstring con flujo MATLAB completo. |
| `fft_dose.py` | Creado. Convolucion FFT optimizada (rfftn + float32 + workers=-1). Docstring actualizada: sin T_mean. |

### Indices de segmentacion
- `LIVER_INDEX = 90`, `TUMOR_INDEX = 100`, `PRETUMOR_INDEX = 200`
- La mascara post-convolucion incluye los tres: `liver_tumor_mask = (liver \| tumor \| pretumor)`

## Sesion 29-Jun (2) — Fix isodosis + DVH

### Isodosis (identico MATLAB)
| MATLAB | Python |
|--------|--------|
| `v=10:10:100` (10 niveles) | `DEFAULT_ISODOSE_LEVELS_PCT = [10,20,...,100]` |
| `colormap(jet)` | `_get_jet_colors(10)` — jet 10 muestras |
| `D31=floor(D31.*100./maximo)` | `smooth3` con `gaussian_filter(sigma=1)` |

### DVH Slicer
- Puntos reducidos de 1000 a 200 (evita saturacion plot)
- Eje X forzado con `SetXAxisRange(0, Dmax*1.05)`

### Percentiles DVH corregidos
| Antes (mal) | Ahora (bien) |
|-------------|--------------|
| `np.percentile(doses_pos, ajuste)` sobre no-cero | `np.percentile(doses, p)` sobre TODOS los voxeles |
| d98 con formula erronea | d98 = `np.percentile(doses, 2)` |

### Archivos modificados
| Archivo | Cambio |
|---------|--------|
| `isodose_contours.py` | 10 niveles 10-100%, jet colormap, smooth3 |
| `run_dosimetry_from_scene.py` | DVH: 200 puntos en vez de 1000. Percentiles sobre todos los voxeles |
| `pipeline_config.jsonc` | isodose.levels_pct = [10..100] (10 niveles) |

## Sesion 29-Jun (3) — Fix SlicerDosimMod3: modulo no cargaba escena

### Problema
El Modulo 3 dentro de Slicer **no cargaba la escena ni computaba nada**, solo mostraba "terminado exitosamente". Causa raiz:
- V4 NO tenia `Modules/Scripted/SlicerDosimMod3/` — el modulo solo existia en v_3.14
- El modulo de v_3.14 era **manual** (boton MCTAL, boton dosis, etc.) y no auto-procesaba nada
- `setup()` corria sin errores → Slicer deci "modulo cargado", pero sin escena ni dosis

### Solucion
Creado `SlicerDosimMod3` en V4 como modulo ScriptedLoadableModule completo:

| Archivo | Contenido |
|---------|-----------|
| `__init__.py` | Exporta SlicerDosimMod3 |
| `CMakeLists.txt` | Build system |
| `SlicerDosimMod3.py` | **NUEVO** — modulo V4 con pipeline automatico |
| `Resources/UI/SlicerDosimMod3.ui` | UI actualizado para V4 |
| `Resources/UI/Icons/SlicerDosimMod3.svg` | Icono |

### Que hace el nuevo Modulo 3
1. **Al abrir el modulo**: auto-detecta escena .mrb en `resultados_test/`
2. **Auto-ejecuta pipeline**: carga escena → encuentra CT/PET/labelmap → kernel FFT → dosis → DVH → isodosis → guarda escena
3. **Botones individuales**: Cargar escena, Calcular dosis, DVH, Isodosis, MIRD, Guardar escena, Exportar PDF
4. **Log en tiempo real**: todos los mensajes aparecen en el txtReporte del UI

### Configuracion para usuario
Para usar el nuevo modulo:
1. Slicer → Edit → Settings → Modules → Additional paths:
   `C:\programas\3Dosim\3Dosim_v4\slicer_modules\SlicerDosim\Modules\Scripted`
2. Restart Slicer
3. Los 3 modulos aparecen bajo "3Dosim": SlicerDosim, SlicerDosimMod2, SlicerDosimMod3

### Archivos nuevos
| Archivo | Ruta |
|---------|------|
| `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/__init__.py` | V4/modules |
| `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/CMakeLists.txt` | V4/modules |
| `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/SlicerDosimMod3.py` | V4/modules (890 lines) |
| `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/Resources/UI/SlicerDosimMod3.ui` | V4/modules |

### Pendiente
- Configurar Slicer para usar V4 module path (en vez de v_3.14)
- Probar modulo 3 dentro de Slicer con escena real de Paciente_2
- Verificar que dosis Y-90 coincida con MATLAB
- Si falta SlicerDosimMod2 en V4, crearlo analogamente

## ⚠️ CORRECCION CRITICA — Sesion 03-Jul — El usuario NO usa el modulo Slicer, usa el launcher

### Error grave de AGENTS.md y del agente

**El AGENTS.md completo asume que el usuario usa SlicerDosimMod3 desde el dropdown de Slicer. ESTO ES FALSO.**

El flujo real es:
1. Usuario ejecuta `C:\programas\3Dosim\3Dosim_v4\scripts\lanzador_3Dosim.bat`
2. Eso lanza `launcher/app.py` (ventana Qt con 3 botones: Mod1, Mod2, Mod3)
3. Mod3 abre dialogo: escena .mrb + metodo (Kernel/MCTAL) + kernel.mat + actividad GBq
4. Al aceptar, `app.py:_launch_slicer()` ejecuta:
   ```
   Slicer.exe --python-script PipelineOrchestrator/run_dosimetry_from_scene.py
              --scene-path <path> --kernel <path> [--activity <n>] [--no-pdf] --show
   ```
5. **NUNCA** se usa `SlicerDosimMod3.py` desde el dropdown de Slicer
6. El launcher mata Slicer previo antes de lanzar uno nuevo

### Implicaciones
- Cualquier fix en `slicer_modules/SlicerDosim/Modules/Scripted/SlicerDosimMod3/SlicerDosimMod3.py` es **IRRELEVANTE** — el usuario nunca corre ese modulo
- El unico archivo relevante para Mod3 es **`PipelineOrchestrator/run_dosimetry_from_scene.py`**
- `main.py` (en PipelineOrchestrator) se usa para Mod1 (segmentacion) y Mod2 (MCNP)

### Launcher: modos de ejecucion

| Modo | Script que lanza | Args principales |
|------|-----------------|------------------|
| Mod1 | `PipelineOrchestrator/main.py --modulo 1` | `--data-dir <dir> --segmenter totalsegmentator --reset` |
| Mod2 | `PipelineOrchestrator/main.py --modulo 2` | `--scene-path <path> --isotope <iso> --n-particles <n>` |
| Mod3 | `PipelineOrchestrator/run_dosimetry_from_scene.py` | `--scene-path <path> --kernel <path> [--activity <n>] --show` |

### Comportamiento observado (trace.log)
- Mod3 corre 1-6 min (carga escena + computa dosis)
- `rc=0` = exito, `rc=1` = crash
- Muchas ejecuciones crashean o no muestran overlay de dosis
- El fix real debe ir en `run_dosimetry_from_scene.py` (lineas ~2410-2530: configurar overlay + isodosis)

### Mod3: crash por labelmap sin datos de imagen

**Problema:** `run_dosimetry_from_scene.py` crashea con:
```
AttributeError: 'NoneType' object has no attribute 'GetDimensions'
```
en `get_labelmap_array()` → `slicer.util.arrayFromVolume()`.

**Causa:** El labelmap existe como nodo en la escena (no es `None`) pero `GetImageData()` devuelve `None` — el nodo no tiene datos de imagen reales.

**Reglas:**
1. El NIfTI externo (`C:\MAT\3Dosim\ai-pipe\3Dosim_labelmap.nii`) NO se usa para Mod3 — es solo para otros programas
2. El labelmap debe estar DENTRO de la escena .mrb y tener `GetImageData() != None`
3. Si el nodo en escena tiene `GetImageData() = None` (nodo corrupto/vacío), el código actual (v4) lo detecta y trata de recrearlo desde segmentation o cargar NIfTI

**Fix aplicado en `run_dosimetry_from_scene.py:1984`:** antes de usar `nodes["labelmap"]`, verifica `node.GetImageData() is not None`. Si no tiene datos, lo marca como ausente y el fallback (NIfTI o segmentation→labelmap) se activa.

### Regla de oro para futuras sesiones
> **ANTES de modificar cualquier archivo, verificar en `launcher/app.py` y `trace.log` cual es el punto de entrada real. No asumir que el usuario usa los modulos de Slicer desde el dropdown.**
