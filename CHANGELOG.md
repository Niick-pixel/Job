# Changelog

Las notas de cada versión se muestran dentro de la app al ofrecer la actualización.

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
