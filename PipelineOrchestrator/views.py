"""
setup_medical_views() - Visualizacion medica automatica para 3D Slicer.

Centraliza la configuracion de slices (axial/sagital/coronal), overlays
CT+PET, navegacion sincronizada y segmentacion 3D para que el pipeline
se comporte como una herramienta clinica navegable.
"""

import logging

logger = logging.getLogger("3DosimTest")


def setup_medical_views(
    ct_node=None,
    pet_node=None,
    ct_masked_node=None,
    segmentation_node=None,
    layout_name: str = "ConventionalView",
    pet_opacity: float = 0.35,
    pet_colormap: str = "vtkMRMLColorTableNodeRainbow",
    ct_window: float = 400.0,
    ct_level: float = 40.0,
    pet_window: float = 40.0,
    pet_level: float = 20.0,
    link_slices: bool = True,
):
    """Configura automaticamente las vistas medicas de Slicer.

    Activa layout medico (axial/sagital/coronal + 3D), toggle de slices
    para CT y PET, slices sincronizados y overlays. Se llama despues de cada
    paso del pipeline para asegurar navegabilidad inmediata.

    Args:
        ct_node: vtkMRMLScalarVolumeNode del CT.
        pet_node: vtkMRMLScalarVolumeNode del PET (opcional).
        ct_masked_node: CT sin camilla/aire (fondo alternativo).
        segmentation_node: vtkMRMLSegmentationNode (opcional).
        layout_name: Nombre del layout de Slicer.
        pet_opacity: Opacidad del overlay PET (0-1).
        pet_colormap: ID del colormap para PET.
        ct_window/ct_level: Window/level para CT.
        pet_window/pet_level: Window/level para PET.
        link_slices: Activar navegacion sincronizada entre cortes.
    """
    try:
        import slicer
    except ImportError:
        logger.warning("  setup_medical_views: no estoy dentro de Slicer")
        return

    logger.info("")
    logger.info("  ========================================================")
    logger.info("  Configurando vistas medicas automaticas")
    logger.info("  ========================================================")

    # --- 1. Layout medico (axial/sagital/coronal + 3D) ---
    lm = slicer.app.layoutManager()
    if lm is None:
        logger.warning("  No hay layout manager (headless mode)")
        return

    try:
        layout_enum = getattr(
            slicer.vtkMRMLLayoutNode,
            f"SlicerLayout{layout_name}",
            slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,
        )
        lm.setLayout(layout_enum)
        logger.info(f"  Layout: {layout_name}")
    except Exception as e:
        logger.warning(f"  No se pudo cambiar layout: {e}")

    # --- 2. Configurar overlays CT/PET en SLICES 2D ---
    bg_node = ct_masked_node if ct_masked_node else ct_node

    if bg_node:
        # Asegurar display node para el fondo (CT)
        bg_dn = bg_node.GetDisplayNode()
        if not bg_dn:
            from slicer import vtkMRMLScalarVolumeDisplayNode

            bg_dn = vtkMRMLScalarVolumeDisplayNode()
            slicer.mrmlScene.AddNode(bg_dn)
            bg_dn.SetDefaultColorMap()
            bg_node.SetAndObserveDisplayNodeID(bg_dn.GetID())

        # Window/level personalizado
        bg_dn.AutoWindowLevelOff()
        bg_dn.SetWindowLevel(ct_window, ct_level)
        logger.info(f"  CT: window={ct_window}, level={ct_level}")

    if pet_node and pet_node.GetImageData():
        # Asegurar display node para PET
        pet_dn = pet_node.GetDisplayNode()
        if not pet_dn:
            from slicer import vtkMRMLScalarVolumeDisplayNode

            pet_dn = vtkMRMLScalarVolumeDisplayNode()
            slicer.mrmlScene.AddNode(pet_dn)
            pet_dn.SetDefaultColorMap()
            pet_node.SetAndObserveDisplayNodeID(pet_dn.GetID())

        # Colormap Rainbow para PET
        pet_dn.SetAndObserveColorNodeID(pet_colormap)
        pet_dn.AutoWindowLevelOff()
        pet_dn.SetWindowLevel(pet_window, pet_level)

        # Mostrar fusion en slices 2D
        if bg_node:
            try:
                slicer.util.setSliceViewerLayers(
                    background=bg_node,
                    foreground=pet_node,
                    foregroundOpacity=pet_opacity,
                )
                logger.info(
                    f"  Fusion CT+PET en slices: fondo=CT, overlay=PET (opacidad={pet_opacity})"
                )
            except Exception as e:
                logger.warning(f"  setSliceViewerLayers fallo: {e}")
    elif bg_node:
        try:
            slicer.util.setSliceViewerLayers(background=bg_node)
            logger.info("  Vista slices: solo CT (sin PET)")
        except Exception as e:
            logger.warning(f"  setSliceViewerLayers fallo: {e}")

    # --- 3. Resetear slices para que se vean inmediatamente ---
    try:
        slicer.util.resetSliceViews()
        logger.info("  Slices reseteados - imagenes visibles")
    except Exception:
        pass

    # --- 4. Mostrar segmentacion en 2D y 3D ---
    if segmentation_node:
        try:
            seg_dn = segmentation_node.GetDisplayNode()
            if not seg_dn:
                segmentation_node.CreateDefaultDisplayNodes()
                seg_dn = segmentation_node.GetDisplayNode()

            if seg_dn:
                seg_dn.SetVisibility(True)
                seg_dn.SetVisibility2D(True)
                seg_dn.SetVisibility3D(True)
                seg_dn.SetSliceIntersectionThickness(1)

            logger.info(
                f"  Segmentacion visible 2D+3D: {segmentation_node.GetName()}"
            )
        except Exception as e:
            logger.warning(
                f"  No se pudo configurar display de segmentacion: {e}"
            )

    # --- 5. Resetear focal point en vista 3D ---
    try:
        three_d_widget = lm.threeDWidget(0)
        if three_d_widget:
            three_d_view = three_d_widget.threeDView()
            three_d_view.resetFocalPoint()
            logger.info("  Vista 3D: focal point reseteado")
    except Exception as e:
        logger.debug(f"  No se pudo resetear focal point 3D: {e}")

    # --- 6. Linkear slices (navegacion sincronizada) ---
    if link_slices:
        try:
            slice_composite_nodes = slicer.util.getNodesByClass(
                "vtkMRMLSliceCompositeNode"
            )
            linked_count = 0
            for node in slice_composite_nodes:
                if hasattr(node, "SetLinkedControl"):
                    was_linked = node.GetLinkedControl()
                    node.SetLinkedControl(True)
                    if not was_linked:
                        linked_count += 1
            if linked_count > 0:
                logger.info(f"  Slices linkeados ({linked_count} nodos)")
            else:
                logger.info("  Slices ya estaban linkeados")
        except Exception as e:
            logger.warning(f"  No se pudieron linkear slices: {e}")

    # --- 7. Refrescar UI ---
    try:
        slicer.app.processEvents()
    except Exception:
        pass

    logger.info("  ========================================================")
    logger.info("  Vistas medicas configuradas")
    logger.info("  ========================================================")
    logger.info("")


def load_pipeline_config(config_path=None) -> dict:
    """Carga la configuracion global del pipeline desde pipeline_config.jsonc.

    Args:
        config_path: Ruta al .jsonc. Si es None, busca en el directorio del script.

    Returns:
        dict con toda la configuracion del pipeline.
    """
    import json
    import os
    import re

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "pipeline_config.jsonc",
        )

    defaults = {
        "scene_output_dir": "C:/MAT/3Dosim/ai-pipe/scenes",
        "screenshot_output_dir": "C:/MAT/3Dosim/ai-pipe/screenshots",
        "image_output_dir": "C:/MAT/3Dosim/ai-pipe/exports",
        "output_dir_rel": "../resultados_test",
        "views": {
            "layout": "ConventionalView",
            "pet_opacity": 0.35,
            "pet_colormap": "vtkMRMLColorTableNodeRainbow",
            "ct_window": 400.0,
            "ct_level": 40.0,
            "pet_window": 40.0,
            "pet_level": 20.0,
            "link_slices": True,
        },
        "pipeline": {
            "force_validation_on_restore": True,
            "config_version": 1,
        },
    }

    if not os.path.exists(config_path):
        logger.info(f"  Config JSONC no encontrado: {config_path}")
        logger.info(f"  Usando valores por defecto")
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Remover comentarios // y /* */
        content = re.sub(r'//.*', "", content)
        content = re.sub(r'/\*.*?\*/', "", content, flags=re.DOTALL)
        config = json.loads(content)

        # Merge profundo con defaults (config sobrescribe defaults)
        def deep_merge(base, override):
            result = base.copy()
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = deep_merge(defaults, config)
        logger.info(f"  Config pipeline cargada desde: {config_path}")
        logger.info(f"    scene_output_dir: {merged['scene_output_dir']}")
        logger.info(f"    views.layout: {merged['views']['layout']}")
        logger.info(f"    views.link_slices: {merged['views']['link_slices']}")
        return merged

    except Exception as e:
        logger.warning(f"  Error cargando pipeline_config.jsonc: {e}")
        logger.info(f"  Usando valores por defecto")
        return defaults
