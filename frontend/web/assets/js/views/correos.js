// 📬 Correos: respuestas de empresas clasificadas por la IA.
import { api } from "../api.js";
import { button, empty, fmtDate, h, icon, pageHead, stagger, toast } from "../ui.js";

const CATEGORY = {
  entrevista: ["warn", "Entrevista", "calendar"], oferta: ["ok", "Oferta", "sparkles"], rechazo: ["bad", "Rechazo", "x"],
  confirmacion_recepcion: ["", "Recibida", "check"], solicitud_info: ["accent", "Piden información", "file"], otro: ["", "Otro", "mail"],
};

export async function render(root, ctx) {
  const listSlot = h("div");
  const gmail = await api.get("/api/settings/gmail").catch(() => ({ mode: "simulated" }));
  const head = pageHead("Correos",
    gmail.mode === "gmail" ? "Respuestas de empresas leídas de tu Gmail" : "Modo de prueba · conecta Gmail en Ajustes para leer tu correo real",
    button("Sincronizar", {
      kind: "primary", ico: "refresh",
      onClick: async () => {
        const res = await api.post("/api/emails/sync");
        toast(`${res.length} correos procesados`);
        await load(listSlot, ctx);
      },
    }),
    gmail.mode !== "gmail" ? button("Conectar Gmail", { ico: "link", onClick: () => ctx.go("ajustes") }) : null);
  root.replaceChildren(head, listSlot);
  await load(listSlot, ctx);
}

async function load(slot, ctx) {
  const events = await api.get("/api/emails");
  if (!events.length) {
    slot.replaceChildren(empty("mail", "Sin correos todavía",
      "Pulsa «Sincronizar» para leer tu bandeja. Las invitaciones a entrevista mueven la candidatura en el Kanban automáticamente."));
    return;
  }
  const important = events.filter((e) => ["entrevista", "oferta"].includes(e.category));
  const rest = events.filter((e) => !important.includes(e));
  slot.replaceChildren(
    important.length ? h("h2", { class: "section-title" }, "Requieren tu atención") : "",
    important.length ? stagger(h("div", { class: "stack" }, important.map((e) => mailCard(e, true)))) : "",
    rest.length ? h("h2", { class: "section-title" }, "Resto") : "",
    stagger(h("div", { class: "stack" }, rest.map((e) => mailCard(e, false)))));
}

function mailCard(e, highlight) {
  const [kind, label, ico] = CATEGORY[e.category] || ["", e.category, "mail"];
  const a = e.analysis || {};
  return h("article", { class: "card hover", style: highlight ? { borderColor: "var(--accent)", boxShadow: "0 0 0 3px var(--accent-soft)" } : {} },
    h("div", { class: "row between", style: { alignItems: "flex-start" } },
      h("div", { style: { minWidth: 0, flex: 1 } }, h("h3", {}, e.subject), h("p", { class: "muted small" }, e.sender)),
      h("div", { class: "row", style: { gap: "6px" } },
        h("span", { class: `chip ${kind}` }, icon(ico), label),
        e.received_at ? h("span", { class: "faint small" }, fmtDate(e.received_at)) : null)),
    a.summary ? h("p", { style: { marginTop: "10px" } }, a.summary) : null,
    a.interview_datetime ? h("p", { class: "chip warn", style: { marginTop: "10px" } }, icon("calendar"), fmtDate(a.interview_datetime, true)) : null,
    a.action_required ? h("p", { class: "muted small", style: { marginTop: "10px" } }, icon("alert"), " ", a.action_required) : null,
    h("p", { class: "faint small", style: { marginTop: "10px" } },
      e.application_id ? "Vinculado a una candidatura del Kanban" : "Sin candidatura asociada",
      ` · confianza ${Math.round((e.confidence || 0) * 100)}%`));
}
