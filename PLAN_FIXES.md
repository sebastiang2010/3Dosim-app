# Plan de correcciones — 3Dosim v4

## Problemas detectados

### 🔴 P1: Launcher — Filtros genéricos en `_browse_file()`

**Archivo:** `launcher/app.py` líneas 652-662

**Síntoma:** Al hacer clic en "Browse..." para cualquier campo (escena, MCTAL, labelmap),
el diálogo muestra SIEMPRE la misma lista genérica:
- "Archivos soportados (\*.mrb \*.mctal ...)"
- "Escenas (\*.mrb)"
- "Output MCNP (\*.mctal \*.mctall \*.m)"
- "Imagenes (\*.nii \*.nii.gz \*.nrrd)"

Cuando se carga un MCTAL, solo debería aparecer "Output MCNP".

**Solución:** Mapear cada `key` del formulario a su filtro específico:

```python
_FILE_FILTERS = {
    "scene_path": "Escenas (*.mrb)",
    "mctal_path": "Output MCNP (*.mctal *.mctall *.m)",
}

def _browse_file(self, key: str):
    filtro = self._FILE_FILTERS.get(key, "All (*)")
    path, _ = QFileDialog.getOpenFileName(
        self, "Seleccionar archivo", "", filtro
    )
    if path and key in self._widgets:
        if isinstance(self._widgets[key], QLineEdit):
            self._widgets[key].setText(path)
```

---

### 🔴 P2: Launcher — Slicer se cierra al ejecutar Mod3

**Archivo:** `launcher/app.py` líneas 1194-1232

**Síntoma:** Al hacer clic en "Ejecutar Mod3", Slicer se abre y se cierra
inmediatamente sin mensaje de error.

**Causa probable:** El comando se construye con comillas dobles anidadas
y se ejecuta con `shell=True`. Si `scene_path` o `mctal_path` tienen
espacios o están vacíos, el shell interpreta mal los argumentos.

**Solución:**
1. Cambiar `shell=True` → `shell=False` pasando lista de argumentos limpia
2. Validar que los archivos existan antes de lanzar
3. Capturar `stderr` del subproceso para diagnóstico

```python
# En _launch_slicer, línea 1194-1207:
elif mod_id == 3:
    script = _RUN_DOSIMETRY
    cmd = [_SLICER_EXE, "--python-script", script]
    scene = config.get("scene_path", "")
    if scene:
        if not os.path.exists(scene):
            QMessageBox.warning(self, "Error", f"Escena no existe:\n{scene}")
            return
        cmd += ["--scene", scene]
    mctal = config.get("mctal_path", "")
    if mctal:
        if not os.path.exists(mctal):
            QMessageBox.warning(self, "Error", f"MCTAL no existe:\n{mctal}")
            return
        cmd += ["--mctal", mctal]
    act = config.get("activity_gbq", -1.0)
    if act > 0:
        cmd += ["--activity", str(act)]
```

Y en el `run()`:
```python
proc = subprocess.Popen(
    cmd,  # lista, no string
    shell=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
```

---

### 🟡 P3: `run_dosimetry_from_scene.py` — Sin validación de archivos

**Archivo:** `PipelineOrchestrator/run_dosimetry_from_scene.py` líneas 1456-1460

**Síntoma:** Si `--scene` apunta a un archivo inexistente, el script
intenta cargarlo igual y Slicer muestra error poco claro.

**Solución:** Validar existencia al inicio de `main()`:

```python
def main():
    args, _ = parser.parse_known_args()
    scene_path = args.scene or SCENE_DEFAULT
    mctal_path = args.mctal or MCTAL_DEFAULT

    if not os.path.exists(scene_path):
        log(f"ERROR: Escena no encontrada: {scene_path}")
        return 1
    if not os.path.exists(mctal_path):
        log(f"ERROR: MCTAL no encontrado: {mctal_path}")
        return 1
    ...
```

---

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `launcher/app.py` | Filtros dinámicos + `shell=False` + validación paths |
| `PipelineOrchestrator/run_dosimetry_from_scene.py` | Validar existencia de archivos al inicio |
