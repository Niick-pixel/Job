// «Rellenar formulario»: abre el formulario de la oferta en Chrome, lo rellena y sube tus documentos.
// La app NUNCA pulsa «Enviar»: lo revisas y lo envías tú; después confirmas aquí.
import { api } from "./api.js";
import { button, h, icon, toast } from "./ui.js";

/** Botón + panel en vivo. getLetter: carta editada · onSent: al confirmar que la enviaste. */
export function autofillButton(pkg, { getLetter, onSent, size = "sm", kind = "" } = {}) {
  const panel = h("div", { class: "autofill", hidden: true });
  const btn = button("Rellenar formulario", {
    kind, size, ico: "sparkles", title: "Abre el formulario en el navegador y lo rellena; el envío lo haces tú",
    onClick: async () => {
      try {
        await api.post(`/api/packages/${pkg.id}/autofill`, { cover_letter: getLetter?.() ?? null });
      } catch (err) {
        if (err.status === 412) { showInstall(panel, () => btn.click()); return; }
        throw err;
      }
      toast("Abriendo el formulario en el navegador…");
      follow(pkg, panel, onSent);
    },
  });
  btn.panel = panel;
  return btn;
}

function showInstall(panel, retry) {
  panel.hidden = false;
  const go = button("Descargar navegador (≈150 MB)", {
    kind: "primary", size: "sm", ico: "download",
    onClick: async (_, b) => {
      await api.post("/api/autofill/browser");
      b.querySelector("span").textContent = "Descargando…";
      for (;;) {
        await new Promise((r) => setTimeout(r, 2500));
        const s = await api.get("/api/autofill/browser");
        if (s.available) { toast("Navegador listo"); panel.hidden = true; retry(); return; }
        if (s.failed || !s.installing) throw new Error("No se pudo descargar. Instala Google Chrome y vuelve a probar.");
      }
    },
  });
  panel.replaceChildren(h("div", { class: "card sunken stack", style: { padding: "14px 16px", gap: "10px" } },
    h("p", {}, h("b", {}, "Hace falta Google Chrome o Microsoft Edge."),
      h("span", { class: "muted" }, " Si no quieres instalarlos, la app puede descargar su propio Chromium (solo para rellenar formularios).")),
    h("div", { class: "row" }, go, h("a", { class: "btn sm", href: "https://www.google.com/chrome/", target: "_blank", rel: "noopener" },
      icon("external"), h("span", {}, "Descargar Chrome")))));
}

async function follow(pkg, panel, onSent) {
  panel.hidden = false;
  let lastState = null, shotAt = null;
  for (let i = 0; i < 2000; i++) {  // ~50 min
    let st;
    try { st = await api.get(`/api/packages/${pkg.id}/autofill`); } catch { st = null; }
    if (st && (st.state !== lastState || st.updated_at !== shotAt)) {
      render(panel, pkg, st, onSent);
      lastState = st.state;
      shotAt = st.updated_at;
    }
    if (!st || st.state === "closed" || st.state === "error") return;
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function render(panel, pkg, st, onSent) {
  const filled = st.filled?.length || 0, missing = st.missing || [];
  const steps = {
    starting: ["clock", "Abriendo el navegador…"], filling: ["clock", "Rellenando el formulario…"],
    ready: ["check", "Revísalo en la ventana del navegador y pulsa «Enviar» allí"],
    closed: ["check", st.submitted ? "Parece que la enviaste" : "Cerraste el navegador"], error: ["alert", st.message || "Algo falló"],
  };
  const [ico, title] = steps[st.state] || ["clock", st.message || ""];
  const confirm = st.state === "closed" || st.submitted ? h("div", { class: "row", style: { marginTop: "10px" } },
    h("span", { class: "muted" }, "¿Enviaste la candidatura?"),
    button("Sí, marcar como enviada", { kind: "primary", size: "sm", ico: "send", onClick: async () => {
      await api.post(`/api/packages/${pkg.id}/decision`, { decision: "enviada" });
      toast("Marcada como enviada · pasa a «Aplicado» en el Kanban");
      panel.hidden = true;
      await onSent?.();
    } }),
    button("Todavía no", { kind: "ghost", size: "sm", onClick: () => { panel.hidden = true; } })) : null;
  panel.replaceChildren(h("div", { class: `card sunken autofill-card ${st.state}` },
    h("div", { class: "row", style: { alignItems: "flex-start", flexWrap: "nowrap" } },
      st.screenshot ? h("a", { href: `/api/packages/${pkg.id}/autofill.png?t=${Date.parse(st.updated_at) || 0}`, target: "_blank", rel: "noopener", class: "autofill-shot", title: "Ver la captura completa" },
        h("img", { src: `/api/packages/${pkg.id}/autofill.png?t=${Date.parse(st.updated_at) || 0}`, alt: "Captura del formulario rellenado" })) : null,
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("p", { style: { fontWeight: 600 } }, icon(ico), " ", title),
        st.state !== "starting" && st.state !== "error" ? h("p", { class: "muted small", style: { marginTop: "4px" } },
          `${filled} campo${filled === 1 ? "" : "s"} rellenado${filled === 1 ? "" : "s"}`,
          st.uploaded?.length ? ` · subido: ${st.uploaded.map((u) => (u === "resume" ? "CV" : "carta")).join(" y ")}` : "",
          st.skipped?.length ? ` · ${st.skipped.length} pregunta(s) personal(es) para ti` : "") : null,
        missing.length ? h("div", { style: { marginTop: "8px" } },
          h("p", { class: "small", style: { color: "var(--warn)", fontWeight: 550 } }, `Te toca completar (en naranja en el formulario):`),
          h("ul", { class: "bullets small muted" }, missing.slice(0, 6).map((m) => h("li", {}, m.replace(/\s*\*\s*$/, ""))))) : null,
        st.state === "ready" ? h("p", { class: "faint small", style: { marginTop: "8px" } },
          icon("shield"), " La app nunca envía por ti. Cuando cierres la ventana te preguntaremos si la enviaste.") : null,
        confirm))));
}
