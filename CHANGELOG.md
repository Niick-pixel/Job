# Changelog

Las notas de cada versión se muestran dentro de la app al ofrecer la actualización.

## 0.3.0

**Agente de búsqueda automática**
- Busca ofertas solo cada 3 h (aunque la app esté cerrada) en Greenhouse, Lever, Ashby, Remotive,
  Adzuna y en tus alertas de empleo por correo (LinkedIn, InfoJobs, Indeed…).
- Elimina duplicados entre portales y aplica tus filtros (puestos, ubicación, remoto, salario,
  antigüedad, empresas a evitar) antes de gastar en IA.
- Criba rápida y barata con Claude Haiku y análisis completo solo de las mejores.
- Aprende de los motivos con los que descartas ofertas.
- Sin configuración: la primera vez deduce de tu CV la ubicación, las búsquedas y las exclusiones,
  y en la app instalada lanza la primera búsqueda en cuanto subes el CV.

**Candidaturas listas para enviar**
- 📥 Bandeja: revisa y aprueba en segundos cada candidatura preparada.
- CV en PDF adaptado a cada oferta (sin inventar nada) y carta de presentación editable.
- Banco de respuestas para preguntas de filtro: las respondes una vez y se adaptan a cada oferta.

**Seguridad**
- Las actualizaciones OTA pasan a estar firmadas con Ed25519: a partir de esta versión la app
  rechaza cualquier actualización que no lleve una firma válida de JobTracker AI.

## 0.2.0

- Instalador para macOS (`install.sh` y `.pkg`) que no requiere Homebrew ni permisos de administrador.
- Actualizaciones OTA firmadas (Ed25519): comprobación cada 6 h, health check antes de activar y rollback automático.
- Aviso de nueva versión y botón «Actualizar ahora» en la barra lateral.
- Icono propio y lanzador «JobTracker AI.app».

## 0.1.0

- Primera versión: análisis de CV, compatibilidad con ofertas, filtro de urgencia, optimización de viñetas y carta, clasificación de correos y Kanban.
