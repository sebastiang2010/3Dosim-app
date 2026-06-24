# 3Dosim v4 — Dosimetria 3D para Medicina Nuclear

Pipeline completo de dosimetria interna para radioembolizacion hepatica con Y-90 y otros radionucleidos.

## Arquitectura

```
3Dosim_v4/
├── pipeline/                  ← Pipeline Orquestador (Python)
│   ├── main.py                ← Entry point CLI
│   ├── pipeline_mod1.py       ← Mod1: Carga DICOM + segmentacion + tumor
│   ├── pipeline_mod2.py       ← Mod2: Generacion MCNP desde escena
│   ├── pipeline_mod3.py       ← Mod3: Analisis dosimetrico (DVH, MIRD, PDF)
│   ├── ai_supervisor.py       ← Supervisor IA (DeepSeek/OpenRouter)
│   ├── comandos.py            ← Consola interactiva Qt
│   ├── checkpoint.py          ← CheckpointManager (persistencia JSON)
│   ├── ... (20+ modulos de soporte)
│
├── slicer_modules/            ← Modulos 3D Slicer
│   ├── SlicerDosim/           ← Modulo 1 (segmentacion + registro)
│   │   ├── SlicerDosim.py     ← Widget Slicer
│   │   └── SlicerDosimLib/    ← Libreria compartida (14 modulos)
│   ├── SlicerDosimMod2/       ← Modulo 2 (MCNP)
│   ├── SlicerDosimMod3/       ← Modulo 3 (analisis)
│   └── wrappers/              ← Flat wrappers (SegMod, DosimetriaMod, AnalisisMod)
│
├── launcher/                  ← Interfaz grafica standalone
│   ├── main.py                ← Entry point PyQt5
│   └── app.py                 ← Ventana principal con 3 botones
│
├── matlab/                    ← Codigo MATLAB original
│   ├── modulo_1_segmentacion/ ← 32 funciones + registro
│   ├── modulo_2_mcnp/         ← 45 funciones de generacion MCNP
│   ├── modulo_3_dosimetria/   ← 39 funciones dosimetricas
│   ├── kernel/                ← Calculo de kernel de dosis
│   ├── ICRP110/               ← Fantomas computacionales ICRP-110
│   └── ... (check_registro, validacion)
│
├── config/                    ← Configuraciones
│   └── pipeline_config.jsonc
│
├── scripts/                   ← Batch files
│   ├── lanzador_3Dosim.bat
│   └── ver_dosis.bat
│
└── docs/
    └── AGENTS.md              ← Documentacion de desarrollo
```

## Requisitos

- Python 3.9+
- 3D Slicer 5.8.1+
- TotalSegmentator (extension Slicer)
- Opcional: DeepSeek/OpenRouter API key para AI Supervisor

## Uso Rapido

```bash
# Lanzador grafico
python launcher/main.py

# Mod1: Carga DICOM + segmentacion
Slicer.exe --python-script pipeline/main.py --modulo 1 --data-dir "C:/ruta/datos"

# Mod2: Generacion MCNP
Slicer.exe --python-script pipeline/main.py --modulo 2 --scene "C:/ruta/escena.mrb"

# Mod3: Analisis dosimetrico
Slicer.exe --python-script pipeline/main.py --modulo 3 --scene "C:/ruta/escena.mrb" --mctal "C:/ruta/mctal.m"
```

## Configuracion Inicial

1. Copiar `.env.template` como `.env` y configurar API key de OpenRouter
2. En Slicer: Edit > Settings > Modules > Additional paths > `.../slicer_modules`
3. Los 3 modulos apareceran bajo categoria "3Dosim"
