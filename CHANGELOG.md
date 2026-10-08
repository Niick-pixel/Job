# Changelog

Las notas de cada versión se muestran dentro de la app al ofrecer la actualización.

## 0.2.1

- Las actualizaciones OTA pasan a estar firmadas con Ed25519: a partir de esta versión la app
  rechaza cualquier actualización que no lleve una firma válida de JobTracker AI.
- Publicación de versiones desde la pestaña Actions de GitHub.

## 0.2.0

- Instalador para macOS (`install.sh` y `.pkg`) que no requiere Homebrew ni permisos de administrador.
- Actualizaciones OTA firmadas (Ed25519): comprobación cada 6 h, health check antes de activar y rollback automático.
- Aviso de nueva versión y botón «Actualizar ahora» en la barra lateral.
- Icono propio y lanzador «JobTracker AI.app».

## 0.1.0

- Primera versión: análisis de CV, compatibilidad con ofertas, filtro de urgencia, optimización de viñetas y carta, clasificación de correos y Kanban.
