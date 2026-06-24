"""
ver_dosis.py — Visualizador de resultados dosimetricos en 3D Slicer.

Carga la escena guardada con dosis (3Dosim_dosis_scene.mrb) y configura:
  - Layout medico (axial/sagital/coronal + 3D)
  - Dosis como overlay semitransparente sobre CT
  - DVH en modulo Plots (si existe en la escena)
  - Slices sincronizados (linked)

Uso:
  Slicer.exe --python-script ver_dosis.py
  Slicer.exe --python-script ver_dosis.py --scene "ruta/a/escena.mrb"
  Slicer.exe --python-script ver_dosis.py --dose-opacity 0.6

Referencia:
  - run_from_scene.py (carga escena)
  - run_dosimetry_from_scene.py (DVH + dosis overlay)
"""

import argparse
import numpy as np
import os
import sys
import time

# Log a archivo para debug
_LOG_PATH = r"C:\MAT\3Dosim\ai-pipe\resultados_dosimetria\ver_dosis_debug.log"
_LOG_FILE = None
try:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
    _LOG_FILE = open(_LOG_PATH, "w", encoding="utf-8")
    _LOG_FILE.write(f"=== ver_dosis.py STARTED: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    _LOG_FILE.write(f"sys.argv: {sys.argv}\n")
    _LOG_FILE.flush()
except Exception:
    pass


def log(msg):
    """Escribe a log file y a stderr (visible en consola Slicer)."""
    timestamp = time.strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    if _LOG_FILE:
        _LOG_FILE.write(line + "\n")
        _LOG_FILE.flush()


# ======================================================================
# Paths por defecto
# ======================================================================
DEFAULT_SCENE = r"C:\MAT\3Dosim\ai-pipe\resultados_dosimetria\3Dosim_dosis_scene.mrb"
SCENE_ALT = r"C:\MAT\3Dosim\ai-pipe\resultados_dosimetria\3Dosim_scene.mrb"


def find_node_by_name(name_substring, class_name=None):
    """Busca nodos cuyo nombre contenga un substring."""
    import slicer
    if class_name:
        nodes = slicer.util.getNodesByClass(class_name)
    else:
        nodes = []
        # Buscar en todos los nodos de la escena
        n = slicer.mrmlScene.GetNumberOfNodes()
        for i in range(n):
            nodes.append(slicer.mrmlScene.GetNthNode(i))
    result = []
    for node in nodes:
        if name_substring.lower() in node.GetName().lower():
            result.append(node)
    return result


def print_all_nodes():
    """Imprime todos los nodos de la escena ordenados por clase."""
    import slicer
    scene = slicer.mrmlScene
    
    log("\n" + "=" * 70)
    log(" TODOS LOS NODOS EN LA ESCENA")
    log("=" * 70)
    
    n = scene.GetNumberOfNodes()
    log(f"Total: {n} nodos\n")
    
    # Agrupar por clase
    classes = {}
    for i in range(n):
        node = scene.GetNthNode(i)
        cls = node.GetClassName()
        if cls not in classes:
            classes[cls] = []
        classes[cls].append(node)
    
    for cls, nodes in sorted(classes.items()):
        log(f"\n--- {cls} ({len(nodes)}) ---")
        for node in nodes:
            name = node.GetName()
            nid = node.GetID()
            # Informacion adicional segun clase
            extra = ""
            if cls == "vtkMRMLPlotChartNode":
                extra = f" Title='{node.GetTitle()}' SeriesCount={node.GetNumberOfPlotSeriesNodeIDs()}"
            elif cls == "vtkMRMLPlotSeriesNode":
                table_id = node.GetTableNodeID() or "none"
                x_col = node.GetXColumnName() or "none"
                y_col = node.GetYColumnName() or "none"
                extra = f" Table='{table_id}' X='{x_col}' Y='{y_col}'"
            elif cls == "vtkMRMLTableNode":
                table = node.GetTable()
                if table:
                    extra = f" Columns={table.GetNumberOfColumns()} Rows={table.GetNumberOfRows()}"
            elif cls == "vtkMRMLScalarVolumeNode":
                dims = node.GetImageData().GetDimensions() if node.GetImageData() else (0,0,0)
                extra = f" [{dims[0]}x{dims[1]}x{dims[2]}]"
            elif cls == "vtkMRMLVolumeRenderingDisplayNode":
                extra = f" Visibility={node.GetVisibility()}"
            log(f"  [{nid}] {name}{extra}")


def recreate_dvh(dose_node=None, labelmap_node=None):
    """
    Re-crea DVH desde cero si no existe en la escena.
    Extrae dosis del nodo Dosis_3D_Gy y usa labelmap indices.
    """
    _crash_log = _LOG_PATH.replace(".log", "_recreate.log")
    try:
        with open(_crash_log, "w") as f:
            f.write(f"=== recreate_dvh STARTED at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        
        import slicer
        import vtk
        import numpy as np
        
        # Encontrar nodo dosis si no se pasa
        if dose_node is None:
            dose_node = find_node_by_name("dosis", "vtkMRMLScalarVolumeNode")
            if not dose_node:
                dose_node = find_node_by_name("gy", "vtkMRMLScalarVolumeNode")
            if not dose_node:
                log("ERROR: No se encuentra nodo Dosis_3D_Gy, no se puede recrear DVH")
                return False
        
        # Encontrar labelmap
        if labelmap_node is None:
            label_nodes = find_node_by_name("label", "vtkMRMLLabelMapVolumeNode")
            if not label_nodes:
                label_nodes = find_node_by_name("label", "vtkMRMLScalarVolumeNode")
            if not label_nodes:
                log("ERROR: No se encuentra labelmap, no se puede recrear DVH")
                return False
            labelmap_node = label_nodes[0]
        
        log(f"Recreando DVH desde nodos: dose={dose_node.GetName()}, labelmap={labelmap_node.GetName()}")
        
        # Extraer arrays
        dose_gy = slicer.util.arrayFromVolume(dose_node)
        with open(_crash_log, "a") as f:
            f.write(f"arrayFromVolume(dose) OK: {dose_gy.shape}\n")
        
        labelmap = slicer.util.arrayFromVolume(labelmap_node)
        with open(_crash_log, "a") as f:
            f.write(f"arrayFromVolume(label) OK: {labelmap.shape}\n")
        
        log(f"  Dose shape: {dose_gy.shape}, Labelmap shape: {labelmap.shape}")
    
        with open(_crash_log, "a") as f:
            f.write(f"\n=== Phase 2: Computing DVH ===\n")
        
        # Indices de estructura
        structures = [
            ("Hígado", 90, (0.2, 0.4, 1.0)),
            ("Tumor", 100, (1.0, 0.2, 0.2)),
            ("Peritumoral", 200, (0.8, 0.6, 0.0)),
        ]
        
        chart_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLPlotChartNode", "DVH_Chart"
        )
        chart_node.SetTitle("Cumulative Dose Volume Histogram")
        chart_node.SetXAxisTitle("Dose (Gy)")
        chart_node.SetYAxisTitle("Volume (%)")
        try:
            chart_node.SetYAxisLogScale(1)  # Slicer 5.8
        except AttributeError:
            try:
                chart_node.SetYAxisLog(True)
            except AttributeError:
                chart_node.SetAttribute("ScaleY", "Log10")
        
        with open(_crash_log, "a") as f:
            f.write("Chart node created\n")
        
        series_created = 0
        for name, idx, color in structures:
            with open(_crash_log, "a") as f:
                f.write(f"Processing {name} (idx={idx})...\n")
            
            mask = (labelmap == idx)
            doses = dose_gy[mask]
            n = len(doses)
            
            with open(_crash_log, "a") as f:
                f.write(f"  {name}: mask={np.sum(mask)} True, doses={n}, max={np.max(doses) if n>0 else 0}\n")
            
            if n == 0 or np.max(doses) <= 0:
                log(f"  Saltando {name}: sin voxeles o sin dosis")
                continue
            
            Dmax = float(np.max(doses))
            delta = Dmax / 1000.0
            d_vals = np.arange(0, Dmax + delta, delta)
            a_vals = np.zeros(len(d_vals))
            
            with open(_crash_log, "a") as f:
                f.write(f"  Computing {len(d_vals)} DVH bins...\n")
            
            for i, d in enumerate(d_vals):
                a_vals[i] = np.sum(doses >= d) * 100.0 / n
            
            with open(_crash_log, "a") as f:
                f.write(f"  DVH computed OK\n")
            
            log(f"  {name}: {n} voxels, Dmax={Dmax:.1f} Gy")
            
            # Crear tabla
            table_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLTableNode", f"DVH_Table_{name}"
            )
            table = table_node.GetTable()
            col_x = vtk.vtkFloatArray()
            col_x.SetName("Dose (Gy)")
            col_y = vtk.vtkFloatArray()
            col_y.SetName("Volume (%)")
            for i in range(len(d_vals)):
                col_x.InsertNextValue(float(d_vals[i]))
                col_y.InsertNextValue(float(a_vals[i]))
            table.AddColumn(col_x)
            table.AddColumn(col_y)
            
            # Serie
            series = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLPlotSeriesNode", f"DVH_{name}"
            )
            series.SetAndObserveTableNodeID(table_node.GetID())
            series.SetXColumnName("Dose (Gy)")
            series.SetYColumnName("Volume (%)")
            series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeLine)
            series.SetColor(*color)
            series.SetLineWidth(2)
            
            chart_node.AddAndObservePlotSeriesNodeID(series.GetID())
            series_created += 1
        
        if series_created == 0:
            log("ERROR: No se pudo crear ninguna serie DVH")
            return False
        
        log(f"DVH recreado: {series_created} series")
        
        # Asignar al PlotViewNode (Slicer 5.8 API)
        slicer.util.selectModule("Plots")
        slicer.app.processEvents()
        
        # Usar vtkMRMLPlotViewNode para asignar chart (no plot_view.SetChartNodeID)
        pv_nodes = slicer.util.getNodesByClass("vtkMRMLPlotViewNode")
        if pv_nodes:
            pv_nodes[0].SetPlotChartNodeID(chart_node.GetID())
            log(f"DVH asignado al PlotViewNode: {pv_nodes[0].GetName()}")
        else:
            log("WARNING: No se encontraron PlotViewNodes")
            return False
        
        slicer.app.processEvents()
        log("DVH asignado al PlotView!")
        
        # Guardar escena con DVH incluido
        scene_dir = os.path.dirname(DEFAULT_SCENE)
        dvh_scene = os.path.join(scene_dir, "3Dosim_dosis_dvh_scene.mrb")
        try:
            slicer.util.saveScene(dvh_scene)
            log(f"Escena con DVH guardada: {dvh_scene}")
        except Exception as e:
            log(f"Warning: No se pudo guardar escena: {e}")
        
        # Verificar que los nodos DVH persistan
        post_charts = slicer.util.getNodesByClass("vtkMRMLPlotChartNode")
        post_series = slicer.util.getNodesByClass("vtkMRMLPlotSeriesNode")
        post_tables = slicer.util.getNodesByClass("vtkMRMLTableNode")
        log(f"Post-save: {len(post_charts)} charts, {len(post_series)} series, {len(post_tables)} tables")
        
        return True
        
        return False
    
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log(f"ERROR DENTRO de recreate_dvh: {e}")
        log(tb)
        with open(_crash_log, "a") as f:
            f.write(f"\nCRASH: {e}\n{tb}\n")
        return False


def show_dvh_in_plots():
    """
    Busca nodos DVH en la escena y los muestra en el modulo Plots.
    
    Estrategia:
    1. Buscar vtkMRMLPlotChartNode con nombre "DVH_Chart"
    2. Activar modulo Plots
    3. Asignar chart al PlotView
    """
    import slicer
    
    # 1. Buscar chart node
    chart_nodes = find_node_by_name("DVH", "vtkMRMLPlotChartNode")
    if not chart_nodes:
        # Buscar cualquier plot chart
        chart_nodes = slicer.util.getNodesByClass("vtkMRMLPlotChartNode")
    
    if not chart_nodes:
        log("  ERROR: No se encontraron PlotChartNodes en la escena")
        log("  El DVH no fue guardado en la escena o no se creo correctamente.")
        return False
    
    chart_node = chart_nodes[0]
    log(f"\n  Chart encontrado: '{chart_node.GetName()}' — '{chart_node.GetTitle()}'")
    log(f"  Series en chart: {chart_node.GetNumberOfPlotSeriesNodeIDs()}")
    
    # Listar series
    for i in range(chart_node.GetNumberOfPlotSeriesNodeIDs()):
        series_id = chart_node.GetPlotSeriesNodeID(i)
        series_node = slicer.mrmlScene.GetNodeByID(series_id)
        if series_node:
            table_id = series_node.GetTableNodeID()
            x_col = series_node.GetXColumnName()
            y_col = series_node.GetYColumnName()
            log(f"    Serie {i+1}: '{series_node.GetName()}'")
            log(f"      TableID={table_id}, X='{x_col}', Y='{y_col}'")
            
            # Verificar si la tabla existe
            if table_id:
                table_node = slicer.mrmlScene.GetNodeByID(table_id)
                if table_node:
                    table = table_node.GetTable()
                    if table:
                        log(f"      Tabla OK: {table.GetNumberOfRows()} rows, {table.GetNumberOfColumns()} cols")
                    else:
                        log(f"      ERROR: Tabla es None")
                else:
                    log(f"      ERROR: TableNode no encontrado por ID")
    
    # 2. Activar modulo Plots
    slicer.util.selectModule("Plots")
    slicer.app.processEvents()
    
    # 3. Asignar chart al PlotViewNode (Slicer 5.8 API)
    pv_nodes = slicer.util.getNodesByClass("vtkMRMLPlotViewNode")
    if pv_nodes:
        pv_nodes[0].SetPlotChartNodeID(chart_node.GetID())
        log(f"\n  DVH asignado al PlotViewNode!")
        slicer.app.processEvents()
        return True
    else:
        log("  ERROR: No se encontraron PlotViewNodes")
    
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Visualizador de resultados dosimetricos en 3D Slicer"
    )
    parser.add_argument("--scene", type=str, default=None,
                        help=f"Ruta a escena .mrb (default: {DEFAULT_SCENE})")
    parser.add_argument("--dose-opacity", type=float, default=0.4,
                        help="Opacidad overlay dosis (0-1)")
    parser.add_argument("--list-nodes", action="store_true",
                        help="Solo listar nodos y salir")
    
    args, _ = parser.parse_known_args()
    
    # ==============================================================
    # 1. Determinar escena
    # ==============================================================
    scene_path = args.scene or DEFAULT_SCENE
    if not os.path.exists(scene_path):
        if os.path.exists(SCENE_ALT):
            scene_path = SCENE_ALT
            log(f"Usando escena alternativa: {scene_path}")
        else:
            log(f"ERROR: Escena no encontrada:\n  {scene_path}")
            return 1
    
    log(f"Cargando escena: {scene_path}")
    log(f"  Tamano: {os.path.getsize(scene_path) / 1024 / 1024:.0f} MB")
    
    # ==============================================================
    # 2. Cargar escena en Slicer
    # ==============================================================
    import slicer
    
    # Limpiar escena actual
    slicer.mrmlScene.Clear(0)
    slicer.app.processEvents()
    
    success = slicer.util.loadScene(scene_path)
    if not success:
        log("ERROR: No se pudo cargar la escena")
        return 1
    
    slicer.app.processEvents()
    log("  Escena cargada correctamente")
    
    # ==============================================================
    # 3. Listar nodos (opcional) o diagnosticar
    # ==============================================================
    if args.list_nodes:
        print_all_nodes()
        return 0
    
    # Mostrar resumen de nodos
    vol_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
    log(f"\nVolumenes ({len(vol_nodes)}):")
    for n in vol_nodes:
        dims = n.GetImageData().GetDimensions() if n.GetImageData() else (0,0,0)
        log(f"  {n.GetName()} [{dims[0]}x{dims[1]}x{dims[2]}]")
    
    chart_nodes = slicer.util.getNodesByClass("vtkMRMLPlotChartNode")
    series_nodes = slicer.util.getNodesByClass("vtkMRMLPlotSeriesNode")
    table_nodes = slicer.util.getNodesByClass("vtkMRMLTableNode")
    log(f"\nPlots: {len(chart_nodes)} charts, {len(series_nodes)} series, {len(table_nodes)} tablas")
    log("[DEBUG] Buscando CT y dosis en volumenes...")
    
    # ==============================================================
    # 4. Encontrar CT y dosis
    # ==============================================================
    ct_node = None
    dose_node = None
    
    for node in vol_nodes:
        name = node.GetName()
        if "ct" in name.lower():
            ct_node = node
            log(f"[DEBUG] CT encontrado: {name}")
        if "dosis" in name.lower() or "gy" in name.lower():
            dose_node = node
            log(f"[DEBUG] Dosis encontrada: {name}")
    
    log(f"[DEBUG] ct_node={ct_node.GetName() if ct_node else 'None'}, dose_node={dose_node.GetName() if dose_node else 'None'}")
    
    # ==============================================================
    # 5. Configurar vistas
    # ==============================================================
    log("[DEBUG] Configurando layout FourUpView...")
    layout_manager = slicer.app.layoutManager()
    log("[DEBUG] layoutManager OK")
    layout_manager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    log("[DEBUG] setLayout OK")
    slicer.app.processEvents()
    log("[DEBUG] processEvents OK")
    
    # Configurar slices con CT + dosis overlay
    if dose_node:
        log(f"[DEBUG] Configurando slices overlay...")
        slice_composite_nodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
        log(f"[DEBUG] {len(slice_composite_nodes)} slice composite nodes")
        for scn in slice_composite_nodes:
            if ct_node:
                scn.SetBackgroundVolumeID(ct_node.GetID())
            scn.SetForegroundVolumeID(dose_node.GetID())
            scn.SetForegroundOpacity(args.dose_opacity)
            scn.SetLinkedControl(True)
        log(f"\nDosis overlay activado: {dose_node.GetName()} ({args.dose_opacity:.0%})")
    
    # Resetear vista 3D
    log("[DEBUG] Resetear vista 3D...")
    try:
        threeD_widget = layout_manager.threeDWidget(0)
        if threeD_widget:
            threeD_widget.threeDView().resetFocalPoint()
            log("[DEBUG] 3D view reset OK")
    except Exception as e:
        log(f"[DEBUG] 3D reset excepcion (no critica): {e}")
    
    slicer.app.processEvents()
    # Forzar ventana Slicer al frente
    log("[DEBUG] Forzando ventana Slicer al frente...")
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd_fg = user32.GetForegroundWindow()
        # Intentar encontrar HWND de Slicer por titulo
        hwnd_slicer = user32.FindWindowW(None, "3D Slicer")
        if hwnd_slicer:
            user32.ShowWindow(hwnd_slicer, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd_slicer)
            log(f"[DEBUG] Slicer window found, restored+foreground")
        else:
            log(f"[DEBUG] Slicer window not found via FindWindowW")
            # Buscar por nombre de clase
            hwnd_slicer = user32.FindWindowW("slicer3DMainWindow", None)
            if hwnd_slicer:
                user32.ShowWindow(hwnd_slicer, 9)
                user32.SetForegroundWindow(hwnd_slicer)
                log(f"[DEBUG] Slicer window found via class name")
            else:
                log(f"[DEBUG] Slicer window not found via class name either")
    except Exception as e:
        log(f"[DEBUG] Window-front excepcion (no critica): {e}")
    
    log("[DEBUG] Todo OK hasta aqui. Mostrando DVH...")
    
    # ==============================================================
    # 6. Mostrar DVH en Plots
    # ==============================================================
    log("\n--- Mostrando DVH en modulo Plots ---")
    dvh_ok = show_dvh_in_plots()
    
    if not dvh_ok:
        log("\n[!] DVH no encontrado en escena. Re-creando desde nodos...")
        try:
            dvh_ok = recreate_dvh(dose_node=dose_node)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log(f"ERROR en recreate_dvh: {e}")
            log(tb)
            # Escribir a archivo directamente
            with open(_LOG_PATH.replace(".log", "_crash.log"), "w") as f:
                f.write(f"CRASH: {e}\n{tb}\n")
            dvh_ok = False
    
    # ==============================================================
    # 7. Mantener Slicer abierto
    # ==============================================================
    log("\n" + "=" * 60)
    log(" VISUALIZACION LISTA")
    log("=" * 60)
    log("  Deberias ver en Slicer:")
    log("  - Axial/Sagital/Coronal con CT + dosis semitransparente")
    log("  - Vista 3D (puedes rotar con el mouse)")
    log("  - Modulo Plots activado con el DVH" if dvh_ok else "  - Modulo Plots: REVISAR (sin DVH)")
    log("")
    if dose_node:
        log(f"  Nodo dosis: {dose_node.GetName()}")
    log("  Cierra Slicer para salir.")
    log("=" * 60)
    
    sys.stderr.flush()
    
    try:
        while True:
            slicer.app.processEvents()
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    except SystemExit:
        pass
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
