// Página de captura: recibe una oferta desde el botón del navegador y la guarda tras confirmar.
import { api } from "./api.js";
import { bookmarkletCode, bookmarkletHref } from "./bookmarklet.js";
import { button, field, h, icon, pageHead, stagger, toast, urgencyChip } from "./ui.js";

const view = document.getElementById("view");

function readCapture() {
  if (!location.hash.length) return null;
  try {
    const d = JSON.parse(decodeURIComponent(location.hash.slice(1)));
    if (typeof d.x !== "string" || typeof d.u !== "string") return null;
    return { url: d.u.slice(0, 2000), title: String(d.t || "").slice(0, 300), text: d.x.slice(0, 15000) };
  } catch { return null; }
}

function installGuide() {
  const link = h("a", { class: "btn primary", href: bookmarkletHref(location.origin), title: "Arrástrame a la barra de favoritos",
    onClick: (e) => { e.preventDefault(); toast("Arrástralo a la barra de favoritos (no hace falta hacer clic)"); } },
    icon("plus"), h("span", {}, "Guardar en JobTracker"));
  return stagger(h("div", {},
    pageHead("Guarda ofertas desde el navegador", "Un botón en tu barra de favoritos envía la oferta que estés viendo a JobTracker AI"),
    h("section", { class: "card center stack" },
      h("p", { class: "muted" }, "1. Muestra la barra de favoritos (Safari: ⌘⇧B · Chrome: ⌘⇧B)"),
      h("p", { class: "muted" }, "2. Arrastra este botón hasta ella:"),
      h("div", { style: { padding: "8px 0" } }, link),
      h("p", { class: "muted" }, "3. En cualquier oferta (LinkedIn, InfoJobs, Indeed, la web de la empresa…) pulsa el favorito."),
      h("p", { class: "faint small" }, "Consejo: si la página tiene mucho texto, selecciona la descripción de la oferta antes de pulsar. JobTracker AI debe estar abierta.")),
    h("details", { class: "disclosure", style: { marginTop: "16px" } },
      h("summary", {}, icon("chevron", "chev"), "¿No puedes arrastrarlo? Créalo a mano"),
      h("div", { class: "body stack" },
        h("p", { class: "muted small" }, "Añade un favorito cualquiera, edítalo y pega esto como dirección (URL):"),
        h("textarea", { class: "input mono", rows: 4, readonly: true }, bookmarkletCode(location.origin)),
        button("Copiar código", { ico: "file", onClick: async () => {
          await navigator.clipboard.writeText(bookmarkletCode(location.origin)); toast("Código copiado");
        } })))));
}

function captureForm(data) {
  let host = "";
  try { host = new URL(data.url).hostname.replace(/^www\./, ""); } catch { /* URL rara: se muestra tal cual */ }
  const text = h("textarea", { class: "input", rows: 14 }, data.text);
  const result = h("div");
  const save = button("Guardar oferta", {
    kind: "primary", ico: "check",
    onClick: async (_, btn) => {
      if (text.value.trim().length < 80) throw new Error("El texto es demasiado corto: selecciona la descripción de la oferta y vuelve a pulsar el favorito");
      const job = await api.post("/api/jobs", { text: text.value, url: data.url });
      history.replaceState(null, "", location.pathname);  // evita guardarla dos veces al recargar
      btn.remove();
      toast("Oferta guardada");
      const cvs = await api.get("/api/cv");
      result.replaceChildren(h("section", { class: "card", style: { marginTop: "16px", animation: "enter 260ms var(--ease-out) both" } },
        h("div", { class: "row between" }, h("div", {}, h("h2", {}, job.title), h("p", { class: "card-sub" }, [job.company, job.location].filter(Boolean).join(" · "))),
          urgencyChip(job.urgency?.level)),
        job.urgency?.message ? h("p", { class: "muted", style: { marginTop: "10px" } }, job.urgency.message) : null,
        h("div", { class: "row", style: { marginTop: "16px" } },
          cvs.length ? button("Preparar candidatura", { kind: "primary", ico: "inbox", onClick: async (_, b2) => {
            await api.post(`/api/jobs/${job.id}/prepare`, null, { cv_id: cvs[0].id });
            b2.replaceWith(h("span", { class: "chip ok" }, icon("check"), "Lista en la Bandeja de la app"));
          } }) : h("span", { class: "faint small" }, "Sube tu CV en la app para preparar la candidatura"),
          h("a", { class: "btn", href: "/#/ofertas" }, icon("external"), h("span", {}, "Ver en JobTracker")))));
    },
  });
  return stagger(h("div", {},
    pageHead("Guardar oferta", host ? `Desde ${host}` : null),
    h("section", { class: "card stack" },
      h("div", {}, h("p", { style: { fontWeight: 600 } }, data.title || "Oferta sin título"),
        h("a", { class: "small", href: data.url, target: "_blank", rel: "noopener", style: { wordBreak: "break-all" } }, data.url)),
      field("Texto de la oferta", text, "Revísalo: puedes borrar lo que no sea parte de la oferta"),
      h("div", { class: "row", style: { justifyContent: "flex-end" } },
        h("a", { class: "btn ghost", href: "/#/bandeja" }, "Cancelar"), save)),
    result));
}

const data = readCapture();
view.replaceChildren(data ? captureForm(data) : installGuide());
