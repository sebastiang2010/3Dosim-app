# Mejoras pendientes para la aplicación

## Objetivo

Implementar las siguientes mejoras de usabilidad, configuración y robustez de la aplicación.

---

# 1. Verificación de modalidad al cargar estudios

## Problema

Actualmente la aplicación carga los estudios PET y CT sin verificar que la modalidad DICOM corresponda al tipo esperado.

## Requerimiento

Al cargar un estudio debe verificarse el campo **Modality** del DICOM.

### Comportamiento esperado

- Si se carga un PET:
  - verificar que `Modality == PT`
- Si se carga un CT:
  - verificar que `Modality == CT`

Si la modalidad no coincide:

- mostrar un mensaje claro al usuario;
- cancelar la carga de ese estudio;
- evitar que continúe el pipeline con datos incorrectos.

---

# 2. Versión de la aplicación en el archivo JSON de configuración

## Problema

La versión de la aplicación está definida en el código.

## Requerimiento

Mover la versión al archivo de configuración JSON.

Ejemplo:

```json
{
    "appVersion": "1.2.0"
}
```

La aplicación deberá leer la versión desde este archivo en tiempo de ejecución.

Objetivos:

- evitar modificar el código para cambiar la versión;
- centralizar toda la configuración.

---

# 3. Mostrar los paths configurados por defecto

## Problema

Al abrir la ventana de configuración los paths aparecen vacíos aunque existan valores configurados.

## Requerimiento

Cuando se abre la ventana de configuración deben mostrarse automáticamente todos los paths actualmente almacenados en la configuración.

El usuario debe poder visualizar inmediatamente:

- directorio de trabajo;
- directorio temporal;
- demás rutas configurables.

No debe ser necesario volver a seleccionarlas para conocer su valor.

---

# 4. Unificar los carteles de progreso

## Problema

El módulo 1 posee un sistema de mensajes de progreso más consistente que los módulos restantes.

## Requerimiento

Los tres módulos deben utilizar el mismo sistema de carteles de progreso que actualmente utiliza el módulo 1.

### Regla

Todo proceso cuya duración estimada sea mayor a aproximadamente **5 segundos** deberá mostrar un cartel de progreso.

Esto incluye cualquier operación larga, como por ejemplo:

- carga de estudios;
- segmentaciones;
- resampleos;
- registros;
- fusiones;
- cálculos;
- exportaciones;
- cualquier otra tarea que pueda generar la impresión de que la aplicación quedó bloqueada.

El comportamiento visual debe ser uniforme en toda la aplicación.

---

# 5. Corregir la barra de progreso

## Problema

Actualmente algunos carteles muestran una barra de progreso que permanece estática durante toda la ejecución.

Esto genera la impresión de que la aplicación se encuentra congelada.

## Requerimiento

Revisar la implementación de los diálogos de progreso.

La barra debe:

- actualizarse correctamente cuando exista información de progreso;
- o utilizar un indicador indeterminado (busy indicator) cuando no sea posible conocer el porcentaje real.

No deben mostrarse barras aparentando un progreso que nunca cambia.

---

# 6. El cartel de fusión no debe bloquear el pipeline

## Problema

Durante el proceso de fusión aparece un cartel que bloquea la ejecución del pipeline.

## Requerimiento

Revisar el mecanismo utilizado para mostrar este diálogo.

El cartel debe actuar únicamente como indicador visual para el usuario y no debe:

- bloquear la ejecución del pipeline;
- detener tareas en segundo plano;
- impedir la continuación automática de las etapas siguientes.

La ejecución completa del pipeline debe continuar normalmente mientras el usuario visualiza el estado del proceso.

---

# Resultado esperado

Después de implementar estas mejoras:

- se validará correctamente la modalidad PET/CT antes de procesar estudios;
- la versión será configurable desde el JSON;
- la ventana de configuración mostrará correctamente los paths actuales;
- los tres módulos tendrán un comportamiento homogéneo respecto a los mensajes de progreso;
- las barras de progreso reflejarán correctamente el estado de ejecución;
- el proceso de fusión dejará de interferir con la ejecución automática del pipeline.