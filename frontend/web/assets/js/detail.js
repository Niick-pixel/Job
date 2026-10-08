// Ficha de una candidatura: entrevista (fecha, Calendario, dossier) y seguimiento (correos redactados).
import { api } from "./api.js";
import { button, fmtDate, h, icon, list, toast, urgencyChip } from "./ui.js";

const STATUS = {
  por_aplicar: ["", "Por aplicar"], aplicado: ["ok", "Aplicado"], entrevista: ["warn", "Entrevista"], rechazado: ["bad", "Rechazado"],
};
const MAIL = { entrevista: "warn", oferta: "ok", rechazo: "bad", solicitud_info: "accent" };

/** Abre la ficha. onChange se llama al cerrar si algo cambió (para refrescar la vista de detrás). */
export async function openApplication(id, { onChange, focus } = {}) {
  const dlg = h("dialog", { class: "sheet", "aria-label": "Ficha de la candidatura" });
  const body = h("div", { class: "sheet-body" }, h("div", { class: "skeleton skeleton-card" }), h("div", { class: "skeleton skeleton-card" }));
  dlg.append(body);
  document.body.append(dlg);
  let changed = false;
  let closing = false;
  const close = () => {
    if (closing) return;
    closing = true;
    dlg.classList.add("out");
    const done = () => { if (!dlg.isConnected) return; dlg.close(); dlg.remove(); if (changed) onChange?.(); };
    dlg.addEventListener("animationend", done, { once: true });
    setTimeout(done, 400);  // por si no hay animación
  };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });  // clic en el fondo
  addEventListener("hashchange", close, { once: true });  // ⌘1…⌘6 cambia de sección
  dlg.showModal();

  const ctx = { id, close, touch: () => { changed = true; } };
  const draw = async () => {
    const d = await api.get(`/api/applications/${id}/detail`);
    body.replaceChildren(...sheet(d, ctx, draw).filter(Boolean));
    if (focus) body.querySelector(`[data-section="${focus}"]`)?.scrollIntoView({ block: "start" });
    focus = null;
  };
  try { await draw(); } catch (err) { toast(err.message, "error"); close(); }
}

function sheet(d, ctx, redraw) {
  const [kind, label] = STATUS[d.status] || ["", d.status];
  const head = h("header", { class: "sheet-head" },
    h("div", { style: { minWidth: 0, flex: 1 } },
      h("h2", {}, d.job_title),
      h("p", { class: "muted" }, [d.company, d.job.location].filter(Boolean).join(" · ") || "—"),
      h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } },
        h("span", { class: `chip ${kind}` }, h("span", { class: `dot ${kind}` }), label),
        d.match_score != null ? h("span", { class: "chip accent" }, `${Math.round(d.match_score)}% encaje`) : null,
        urgencyChip(d.urgency_level),
        d.days_since_applied != null ? h("span", { class: "chip" }, icon("clock"), `aplicaste hace ${d.days_since_applied} d`) : null,
        d.job.salary ? h("span", { class: "chip" }, d.job.salary) : null)),
    h("div", { class: "row", style: { gap: "6px", alignSelf: "flex-start" } },
      d.job.url ? h("a", { class: "btn sm", href: d.job.url, target: "_blank", rel: "noopener" }, icon("external"), h("span", {}, "Oferta")) : null,
      button("", { ico: "x", size: "sm", title: "Cerrar (Esc)", onClick: ctx.close })));

  return [
    head,
    hint(d, ctx),
    interviewSection(d, ctx, redraw),
    prepSection(d, ctx),
    followSection(d, ctx, redraw),
    notesSection(d, ctx),
    emailsSection(d),
  ];
}

/** Lo que conviene hacer ahora, arriba del todo. */
function hint(d) {
  let text = null;
  if (d.suggest_thanks) text = "La entrevista ya pasó: envía una nota de agradecimiento hoy, marca la diferencia.";
  else if (d.status === "entrevista" && !d.interview_at) text = "Apunta la fecha de la entrevista para recibir el aviso y añadirla a Calendario.";
  else if (d.status === "entrevista" && !d.prep) text = "Prepara la entrevista: preguntas probables, temas técnicos y qué preguntar tú.";
  else if (d.suggest_follow_up) text = `Llevas ${d.days_since_applied} días sin respuesta: es buen momento para un seguimiento breve.`;
  return text ? h("p", { class: "sheet-hint" }, icon("sparkles"), h("span", {}, text)) : null;
}

function section(id, title, ...children) {
  return h("section", { class: "sheet-section", "data-section": id }, h("h3", { class: "section-title" }, title), ...children);
}

// ── Entrevista ─────────────────────────────────────────────────
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function interviewSection(d, ctx, redraw) {
  if (!["aplicado", "entrevista"].includes(d.status) && !d.interview_at) return null;
  const input = h("input", { type: "datetime-local", class: "input", value: toLocalInput(d.interview_at), style: { maxWidth: "240px" } });
  const save = button("Guardar fecha", {
    kind: d.status === "entrevista" && !d.interview_at ? "primary" : "", size: "sm", ico: "check",
    onClick: async () => {
      if (!input.value) throw new Error("Elige día y hora");
      // el campo es hora local: se envía con zona para que no haya dudas
      await api.patch(`/api/applications/${ctx.id}`, { status: "entrevista", interview_at: new Date(input.value).toISOString() });
      ctx.touch();
      toast("Entrevista guardada · te avisaremos el día antes");
      await redraw();
    },
  });
  const calendar = d.interview_at ? button("Añadir a Calendario", {
    kind: "primary", size: "sm", ico: "calendar",
    onClick: async () => {
      const r = await api.post(`/api/applications/${ctx.id}/calendar`);
      if (r.opened) toast("Abierto en Calendario · confirma el evento allí");
      else location.href = r.url;  // fuera del Mac: descarga el .ics
    },
  }) : null;
  const clear = d.interview_at ? button("Quitar fecha", {
    kind: "ghost", size: "sm",
    onClick: async () => { await api.patch(`/api/applications/${ctx.id}`, { clear_interview: true }); ctx.touch(); await redraw(); },
  }) : null;
  const when = d.interview_at
    ? new Date(d.interview_at).toLocaleString("es-ES", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
    : null;
  return section("entrevista", "Entrevista",
    when ? h("p", { style: { marginBottom: "10px" } }, icon("calendar"), " ", h("b", {}, when))
      : d.status === "aplicado" ? h("p", { class: "muted small", style: { marginBottom: "10px" } }, "¿Te han citado? Apunta la fecha y la candidatura pasa a «Entrevista».") : null,
    h("div", { class: "row" }, input, save, calendar, clear));
}

// ── Dossier de preparación ─────────────────────────────────────
function prepSection(d, ctx) {
  if (!["aplicado", "entrevista"].includes(d.status) && !d.prep) return null;
  const slot = h("div", {}, d.prep ? dossier(d.prep) : h("p", { class: "muted" },
    "La IA cruza la oferta con tu CV y te da preguntas probables con un esquema de respuesta basado en tu experiencia real, "
    + "temas técnicos a repasar, tus puntos débiles y qué preguntar tú. Tarda unos 20-40 segundos."));
  const run = button(d.prep ? "Rehacer" : "Preparar entrevista", {
    kind: d.prep ? "ghost" : d.status === "entrevista" ? "primary" : "", size: "sm", ico: "sparkles",
    onClick: async (_, btn) => {
      btn.querySelector("span").textContent = "Preparando…";
      try {
        const prep = await api.post(`/api/applications/${ctx.id}/prep`);
        slot.replaceChildren(dossier(prep));
        slot.firstElementChild.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" });
        btn.querySelector("span").textContent = "Rehacer";
        btn.className = "btn ghost sm";
      } catch (err) {
        btn.querySelector("span").textContent = d.prep ? "Rehacer" : "Preparar entrevista";
        throw err;
      }
    },
  });
  return section("prep", h("span", { class: "row between", style: { width: "100%" } }, "Preparación", run), slot);
}

function dossier(p) {
  const block = (title, content) => (content && (!Array.isArray(content) || content.length))
    ? h("div", { class: "dossier-block" }, h("h4", {}, title), content) : null;
  const bullets = (items) => items?.length ? h("ul", { class: "bullets" }, items.map((t) => h("li", {}, t))) : null;
  return h("div", { class: "dossier" },
    p.company_summary ? h("p", {}, p.company_summary) : null,
    block("En qué se fijarán", bullets(p.role_focus)),
    block("Preguntas probables", p.likely_questions?.length ? h("div", { class: "qa" }, p.likely_questions.map((q) =>
      h("details", {}, h("summary", {}, q.question),
        h("p", { class: "faint small" }, q.why), h("p", {}, q.answer_outline)))) : null),
    block("Temas técnicos a repasar", p.technical_topics?.length ? h("div", { class: "row", style: { gap: "6px" } },
      p.technical_topics.map((t) => h("span", { class: "chip" }, t))) : null),
    block("Tus puntos débiles (y cómo abordarlos)", p.weak_spots?.length ? list(p.weak_spots, "warn") : null),
    block("Qué preguntar tú", bullets(p.questions_to_ask)),
    block("Antes de empezar", p.checklist?.length ? list(p.checklist, "ok") : null));
}

// ── Seguimiento y agradecimiento ───────────────────────────────
function followSection(d, ctx, redraw) {
  const canFollow = d.status === "aplicado";
  const canThank = d.status === "entrevista";
  if (!canFollow && !canThank) return null;
  const slot = h("div");
  const draft = (kind) => async (_, btn) => {
    const span = btn.querySelector("span"), label = span.textContent;
    span.textContent = "Redactando…";
    try { slot.replaceChildren(composer(await api.post(`/api/applications/${ctx.id}/message`, { kind }), kind, d, ctx, redraw)); }
    finally { span.textContent = label; }
  };
  const followed = d.follow_up_at ? h("p", { class: "faint small", style: { marginBottom: "10px" } },
    icon("check"), ` Último seguimiento: ${fmtDate(d.follow_up_at)}`) : null;
  return section("seguimiento", "Seguimiento", followed,
    h("div", { class: "row" },
      canFollow ? button("Redactar seguimiento", { kind: d.suggest_follow_up ? "primary" : "", size: "sm", ico: "mail", onClick: draft("seguimiento") }) : null,
      canThank ? button("Redactar agradecimiento", { kind: d.suggest_thanks ? "primary" : "", size: "sm", ico: "mail", onClick: draft("agradecimiento") }) : null),
    slot);
}

function composer(msg, kind, d, ctx, redraw) {
  const to = h("input", { class: "input", value: msg.to || "", placeholder: "correo@empresa.com" });
  const subject = h("input", { class: "input", value: msg.subject });
  const text = h("textarea", { class: "input", rows: 9 }, msg.body);
  const mailto = () => `mailto:${encodeURIComponent(to.value.trim()).replace("%40", "@")}?subject=${encodeURIComponent(subject.value)}&body=${encodeURIComponent(text.value)}`;
  const open = h("a", { class: "btn primary sm", target: "_blank", rel: "noopener", href: mailto() }, icon("send"), h("span", {}, "Abrir en Mail"));
  for (const el of [to, subject, text]) el.addEventListener("input", () => { open.href = mailto(); });
  return h("div", { class: "card sunken composer" },
    h("label", { class: "field" }, h("span", {}, "Para"), to,
      msg.to ? null : h("small", { class: "hint" }, "No hay un contacto en los correos de esta empresa: búscalo en la oferta o en LinkedIn.")),
    h("label", { class: "field" }, h("span", {}, "Asunto"), subject),
    h("label", { class: "field" }, h("span", {}, "Mensaje"), text,
      h("small", { class: "hint" }, "Revísalo y personalízalo: la IA solo usa datos de tu CV y la oferta.")),
    h("div", { class: "row" }, open,
      button("Copiar", { size: "sm", ico: "file", onClick: async () => {
        await navigator.clipboard.writeText(`${subject.value}\n\n${text.value}`);
        toast("Copiado");
      } }),
      kind === "seguimiento" ? button("Marcar como enviado", { kind: "ghost", size: "sm", ico: "check", onClick: async () => {
        await api.post(`/api/applications/${ctx.id}/follow-up-sent`);
        ctx.touch();
        toast("Hecho · no volveremos a recordártelo en una semana");
        await redraw();
      } }) : null));
}

// ── Notas y correos ────────────────────────────────────────────
function notesSection(d, ctx) {
  const area = h("textarea", { class: "input", rows: 3, placeholder: "Nombre del entrevistador, salario hablado, siguientes pasos…" }, d.notes || "");
  let saved = d.notes || "";
  area.addEventListener("blur", async () => {
    if (area.value === saved) return;
    try {
      await api.patch(`/api/applications/${ctx.id}`, { notes: area.value });
      saved = area.value;
      ctx.touch();
      toast("Notas guardadas");
    } catch (err) { toast(err.message, "error"); }
  });
  return section("notas", "Notas", area,
    h("small", { class: "hint faint" }, "Se guardan solas al salir del campo. La IA las tiene en cuenta al redactar correos."));
}

function emailsSection(d) {
  if (!d.emails.length) return null;
  return section("correos", "Correos de la empresa", h("div", { class: "stack", style: { gap: "8px" } }, d.emails.map((e) =>
    h("div", { class: "mail-line" },
      h("span", { class: `dot ${MAIL[e.category] || ""}` }),
      h("div", { style: { minWidth: 0, flex: 1 } },
        h("b", {}, e.subject), h("span", { class: "faint small" }, ` · ${fmtDate(e.received_at)}`),
        e.summary ? h("p", { class: "muted small" }, e.summary) : null)))));
}
