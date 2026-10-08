// Código del botón «Guardar en JobTracker» para la barra de favoritos del navegador.
// Lee la oferta de la página (texto seleccionado o el bloque de descripción de los portales
// conocidos) y abre la página de captura de la app con los datos en el fragmento (#): no viajan
// por la red ni dependen de la política de seguridad (CSP) del portal.
export function bookmarkletCode(origin = location.origin) {
  const body = `(()=>{const S=String(getSelection()).trim();const Q=['.jobs-description__content','.jobs-search__job-details--container','.jobs-details','#jobDescriptionText','.jobsearch-JobComponent','[data-automation=jobAdDetails]','.description__text','.job-description','[class*=jobDescription]','article','main'];let t=S;if(t.length<200){for(const c of Q){const e=document.querySelector(c);if(e&&e.innerText.trim().length>200){t=e.innerText;break}}}if(t.length<200)t=document.body.innerText;const d={u:location.href,t:document.title,x:t.trim().slice(0,15000)};window.open('${origin}/capture#'+encodeURIComponent(JSON.stringify(d)),'_blank')})()`;
  return `javascript:${body}`;
}

/** Enlace arrastrable a la barra de favoritos. */
export function bookmarkletHref(origin) {
  const code = bookmarkletCode(origin);
  return "javascript:" + encodeURIComponent(code.slice("javascript:".length));
}
