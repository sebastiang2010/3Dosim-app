"""
PipelineOrchestrator - Orchestrador del pipeline 3Dosim para 3D Slicer.

Estructura modular que luego se promocionara a SlicerDosimLib/orchestrator/:

  checkpoint.py          - CheckpointManager: estado persistente entre ejecuciones
  anonymize.py           - Anonimizacion DICOM (pydicom)
  couch_remover.py       - Eliminacion de camilla y aire del CT
  segmentation.py        - TotalSegmentator (TotalSegmentatorLogic.process())
    validation.py          - Dialogo de validacion medica obligatoria
    tumor_creator.py       - Tumor sintetico esferico (1 cm radio) en higado + higado_sano
    tumor_segmentation.py  - Preparacion ROI hepatica + MONAI Label (tumor)
    tumor_validation.py    - Dialogo de validacion medica del tumor
   git_commit.py          - Prompt de commit git al finalizar
   pipeline.py            - PipelineTestOrchestrator: orquesta todos los pasos
   comandos.py            - Consola interactiva de comandos (lenguaje natural)
   main.py                - Entry point con argparse
   views.py               - setup_medical_views() + load_pipeline_config()
    pipeline_config.jsonc           - Configuracion central (scene_output_dir, vistas, etc.)
    ai_supervisor.py                - Revision IA paso a paso (DeepSeek/OpenRouter)
    pipeline_mcnp_from_scene.py     - MCNPFromScenePipeline: carga .mrb y genera MCNP
    main_mcnp_from_scene.py         - Entry point CLI para pipeline MCNP desde escena
    deepseek_client.py     - Cliente OpenRouter multi-modelo
    monailabel_server.py   - Wrapper para iniciar servidor MONAI Label
    pipeline_mod1.py       - Pipeline Mod1: carga, segmentacion, tumor
    pipeline_mod2.py       - Pipeline Mod2: generacion MCNP desde escena
    pipeline_mod3.py       - Pipeline Mod3: analisis dosimetrico desde MCTAL
    isodose_contours.py    - Curvas/superficies de isodosis (SlicerRT o VTK fallback)

Todos los imports internos son ABSOLUTOS (from PipelineOrchestrator.xxx)
para compatibilidad con 3D Slicer --python-script.
"""
