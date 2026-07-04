# AI Supervisor

## Propósito

El AI Supervisor es un **revisor inteligente** que analiza el resultado
de cada paso del pipeline y detecta anomalías antes de continuar. No
reemplaza la validación médica, sino que la complementa con verificaciones
automáticas.

## Verificaciones por paso

| Paso | Verificación | Condición de fallo |
|------|-------------|-------------------|
| Carga DICOM | Dimensiones, espaciado, modalidades | CT/PET no detectados |
| Calibración PET | Actividad total > 0 Bq | Actividad cero o negativa |
| Eliminar camilla | Volumen eliminado < 50% volumen total | Se eliminó más de la mitad del paciente |
| Registro PET→CT | Métricas de alineación > umbral | NCC < 0.6 |
| TotalSegmentator | 50+ segmentos generados | < 20 segmentos |
| Validación médica | Verifica que hubo aprobación | No hubo interacción |
| Creación tumor | Volumen > 0.5 cm³ | Tumor dentro del hígado |
| Body segmentation | Body contiene todos los órganos | Órganos fuera del body |
| Export labelmap | Sin solapamiento, todos asignados | Overlap > 0 o voxels sin asignar |

## Flujo

```
Fin de paso N
    │
    ▼
AI Supervisor: analizar resultado
    │
    ├── Normal → continuar
    ├── Warning → log + continuar
    └── Error  → detener pipeline
```

## Ejemplo

```python
def _do_couch_remover(self):
    """Paso 3: Eliminar camilla."""
    # ... ejecución del paso ...
    
    # AI Supervisor: verificar
    removed_pct = (original_voxels - couch_voxels) / original_voxels * 100
    if removed_pct > 50:
        log.error(f"AI Supervisor: se eliminó {removed_pct}% del volumen — "
                   "parece excesivo. Verificar camilla.")
        if self.fail_on_ai_supervisor_warning:
            raise RuntimeError("AI Supervisor detectó anomalía en couch_remover")
```

## Configuración

```jsonc
"ai_supervisor": {
    "fail_on_warning": false,    // true = detener pipeline en warning
    "log_level": "warning",      // "info", "warning", "error"
    "checks": {
        "carga_dicom": true,
        "calibracion_pet": true,
        "couch_remover": true,
        "registro_pet_ct": true,
        "fusion": true,
        "totalsegmentator": true,
        "creacion_tumor": true,
        "body_seg": true,
        "export_labelmap": true
    }
}
```

## Notas

- Los warnings NO detienen el pipeline por defecto
- Los errores (anomalías graves) SIEMPRE detienen el pipeline
- El supervisor guarda un log detallado en `output_dir/logs/ai_supervisor.log`
- Puede desactivarse por paso individual
