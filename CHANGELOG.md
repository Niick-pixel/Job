# Changelog

Las notas de cada versión se muestran dentro de la app al ofrecer la actualización.

## 0.6.0

- **Ficha de cada candidatura**: haz clic en una tarjeta del Kanban (o en la tarjeta «Hoy» o en un correo)
  para ver todo junto: estado, fecha de entrevista, preparación, seguimiento, notas y correos de la empresa.
- **Entrevistas**: apunta la fecha y añádela a Calendario de macOS con un clic (con aviso 1 h antes).
  Cuando llega un correo de entrevista recibes una notificación.
- **Dossier de preparación**: la IA cruza la oferta con tu CV y te da preguntas probables con un esquema
  de respuesta basado solo en tu experiencia real, temas técnicos a repasar, tus puntos débiles y cómo
  abordarlos, qué preguntar tú y una lista para el día.
- **Seguimiento**: si llevas 7 días sin respuesta, la app te propone un correo de seguimiento; tras la
  entrevista, una nota de agradecimiento. Se redactan con tus datos, los revisas y se abren en Mail con un
  clic. «Marcar como enviado» evita que te lo vuelva a recordar en una semana.
- Corregido: las fechas de entrevista sin zona horaria que extraía la IA de un correo podían fallar al guardarse.

## 0.5.0

- **Descubrir empresas**: escribe nombres («Glovo, Cabify») o pega la URL de su página de empleo y la
  app encuentra si publican en Greenhouse, Lever o Ashby, con nº de ofertas y ejemplos. Un clic y quedan
  vigiladas por el agente.
- **Guardar desde el navegador**: un botón en la barra de favoritos de Safari o Chrome envía a la app la
  oferta que estés viendo (LinkedIn, InfoJobs, Indeed o cualquier web), con confirmación antes de guardar.
  Instálalo en Ajustes → Navegador.
- **Resumen diario**: aviso cada mañana (hora configurable en Agente) con entrevistas próximas,
  candidaturas nuevas, aprobadas sin enviar y candidaturas sin respuesta desde hace más de 7 días.
  También aparece como tarjeta «Hoy» en la Bandeja.

## 0.4.1

- **Modo económico por defecto**: Claude Haiku en todo con el razonamiento mínimo (≈ 0,50 $ al mes con
  uso normal). Las instalaciones con la configuración de fábrica anterior (Opus) pasan a él solas.
- Perfiles de gasto en Ajustes → Inteligencia artificial: Económico, Equilibrado y Máxima calidad,
  con su coste estimado. Si eliges otro, se respeta y no se vuelve a cambiar.

## 0.4.0

**Aplicación de escritorio**
- JobTracker AI se abre en su propia ventana nativa de macOS, ya no en el navegador.
- Interfaz nueva, minimalista y centrada, con animaciones sutiles (se pueden reducir en Ajustes).
- 8 temas: Porcelana, Grafito, Océano, Bosque, Atardecer, Lavanda, Medianoche y Arena, más «Automático».
- Kanban con arrastrar y soltar, CV por arrastre y atajos de teclado (⌘1…⌘6 secciones, ⌘, ajustes).

**Ajustes**
- Claves API desde la app: Claude, Adzuna y cualquier otra clave personalizada, con botón «Probar»
  y guía de cómo conseguir cada una. Se guardan en privado y nunca se muestran completas.
- Elección de modelo de IA y nivel de razonamiento, y conexión con Gmail sin usar la terminal.

**Seguridad**
- Protección frente a peticiones de otras webs al motor local de la app.

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
