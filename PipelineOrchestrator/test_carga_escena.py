"""
test_carga_escena.py — SOLO carga la escena y LOGUEA a archivo.
NADA de dosimetria, NADA de kernel, NADA de exec_().
"""
import os, sys, time, traceback

LOG = r"C:\tmp\test_scene_log.txt"
SCENE = r"C:\MAT\3Dosim\ai-pipe\scenes\3Dosim.mrb"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    print(msg, flush=True)

log("=" * 60)
log("TEST CARGA ESCENA INICIADO")
log("=" * 60)
log(f"Archivo: {SCENE}")
log(f"Existe: {os.path.exists(SCENE)}")
if os.path.exists(SCENE):
    log(f"Tamanio: {os.path.getsize(SCENE) / 1024 / 1024:.1f} MB")

# Esperar a que Slicer termine de inicializar
time.sleep(3)
log("Espera 3s completa")

try:
    import slicer
    log("[OK] slicer importado")
except Exception as e:
    log(f"[ERROR] No se pudo importar slicer: {e}")
    sys.exit(1)

try:
    import vtk
    log("[OK] vtk importado")
except Exception as e:
    log(f"[ERROR] vtk: {e}")

# Verificar que slicer.app existe
try:
    app = slicer.app
    log(f"[OK] slicer.app existe: {app is not None}")
except Exception as e:
    log(f"[ERROR] slicer.app: {e}")

# Verificar mrmlScene
try:
    scene = slicer.mrmlScene
    log(f"[OK] mrmlScene existe: {scene is not None}")
    log(f"     URL: {scene.GetURL()}")
    log(f"     Nodos actuales: {scene.GetNumberOfNodes()}")
except Exception as e:
    log(f"[ERROR] mrmlScene: {e}")

# 1. Cargar escena
log("\n--- PASO 1: loadScene() ---")
try:
    success = slicer.util.loadScene(SCENE)
    log(f"loadScene() devolvio: {success}")
    log(f"Nodos despues: {slicer.mrmlScene.GetNumberOfNodes()}")
except Exception as e:
    log(f"loadScene() EXCEPCION: {e}")
    log(traceback.format_exc())

# 2. Listar nodos
log("\n--- PASO 2: Nodos en escena ---")
try:
    all_vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
    log(f"ScalarVolumeNodes: {len(all_vols)}")
    for v in all_vols:
        log(f"  - '{v.GetName()}' [ID: {v.GetID()}] dims={v.GetImageData().GetDimensions() if v.GetImageData() else 'NO_DATA'}")

    all_lm = slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")
    log(f"LabelMapVolumeNodes: {len(all_lm)}")
    for v in all_lm:
        log(f"  - '{v.GetName()}' [ID: {v.GetID()}]")

    all_seg = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
    log(f"SegmentationNodes: {len(all_seg)}")
    for v in all_seg:
        log(f"  - '{v.GetName()}' [ID: {v.GetID()}]")
except Exception as e:
    log(f"ERROR listando nodos: {e}")
    log(traceback.format_exc())

# 3. Configurar layout
log("\n--- PASO 3: Layout ---")
try:
    lm = slicer.app.layoutManager()
    if lm:
        lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        log("Layout ConventionalView ACTIVADO")
    else:
        log("layoutManager es None!")
except Exception as e:
    log(f"Layout fallo: {e}")

try:
    slicer.util.resetSliceViews()
    log("resetSliceViews OK")
except Exception as e:
    log(f"resetSliceViews: {e}")

# 4. Fusion CT+PET
log("\n--- PASO 4: Fusion ---")
if len(all_vols) >= 2:
    try:
        ct = all_vols[0]
        pet = all_vols[1]
        slicer.util.setSliceViewerLayers(background=ct, foreground=pet, foregroundOpacity=0.35)
        log(f"Fusion: bg='{ct.GetName()}' fg='{pet.GetName()}'")
    except Exception as e:
        log(f"Fusion fallo: {e}")

# 5. Forzar refresh
log("\n--- PASO 5: Refresh ---")
for _ in range(50):
    slicer.app.processEvents()
    time.sleep(0.1)

log("\n*** Slicer queda abierto 30s para que veas ***")
log("*** MIRA la ventana de Slicer ***")
log("*** Deberias ver CT, PET, layout medico ***")

# Mantener por 30s
for i in range(30):
    slicer.app.processEvents()
    time.sleep(1)
    if i % 10 == 0:
        log(f"  ... esperando {i}s")

log("\n*** TEST COMPLETADO ***")
log("*** CERRANDO SLICER ***")
slicer.app.quit()
