// Ficha de una candidatura: entrevista (fecha, Calendario, dossier) y seguimiento (correos redactados).
import { api } from "./api.js";
import { button, field, fmtDate, h, icon, list, tagInput, toast, urgencyChip } from "./ui.js";

const STATUS = {
  por_aplicar: ["", "Por aplicar"], aplicado: ["ok", "Aplicado"], entrevista: ["warn", "Entrevista"], oferta: ["ok", "Oferta"],
  rechazado: ["bad", "Rechazado"],
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
    offerSection(d, ctx, redraw),
    interviewSection(d, ctx, redraw),
    prepSection(d, ctx),
    mockSection(d, ctx),
    followSection(d, ctx, redraw),
    notesSection(d, ctx),
    emailsSection(d),
  ];
}

/** Lo que conviene hacer ahora, arriba del todo. */
function hint(d) {
  let text = null;
  if (d.status === "oferta" && !d.offer) text = "¡Enhorabuena! Apunta las condiciones de la oferta para preparar la negociación.";
  else if (d.suggest_thanks) text = "La entrevista ya pasó: envía una nota de agradecimiento hoy, marca la diferencia.";
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
  if (!["aplicado", "entrevista"].includes(d.status)) return null;
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

// ── Oferta: condiciones, negociación y comparación ─────────────
const money = (n, cur = "EUR") => (n || n === 0) ? Number(n).toLocaleString("es-ES", { style: "currency", currency: cur, maximumFractionDigits: 0 }) : "—";

function offerSection(d, ctx, redraw) {
  if (!["entrevista", "oferta"].includes(d.status)) return null;
  const o = d.offer || {};
  const num = (v, ph) => h("input", { class: "input", type: "number", min: 0, step: 500, value: v ?? "", placeholder: ph });
  const txt = (v, ph) => h("input", { class: "input", value: v ?? "", placeholder: ph || "" });
  const f = {
    base: num(o.base_salary, "48000"), variable: num(o.variable, "0"),
    currency: h("select", { class: "input" }, ["EUR", "USD", "GBP", "MXN", "ARS", "COP", "CLP"].map((c) => h("option", { selected: c === (o.currency || "EUR") }, c))),
    modality: txt(o.modality, "remoto, híbrido 2 días…"), vacation: h("input", { class: "input", type: "number", min: 0, max: 60, value: o.vacation_days ?? "" }),
    start: h("input", { class: "input", type: "date", value: o.start_date || "" }), deadline: h("input", { class: "input", type: "date", value: o.deadline || "" }),
    equity: txt(o.equity, "stock options, RSU…"), benefits: txt(o.benefits, "seguro médico, formación, tickets…"),
    notes: h("textarea", { class: "input", rows: 2, placeholder: "Lo que te dijeron en la llamada…" }, o.notes || ""),
  };
  const val = (el) => (el.value === "" ? null : el.type === "number" ? Number(el.value) : el.value.trim() || null);
  const form = h("div", { class: "stack", style: { gap: "12px" } },
    h("div", { class: "grid-3" }, field("Salario fijo bruto anual", f.base), field("Variable anual", f.variable), field("Moneda", f.currency)),
    h("div", { class: "grid-3" }, field("Modalidad", f.modality), field("Días de vacaciones", f.vacation), field("Equity", f.equity)),
    h("div", { class: "grid-3" }, field("Incorporación", f.start), field("Responder antes de", f.deadline), field("Beneficios", f.benefits)),
    field("Notas", f.notes),
    h("div", { class: "row" }, button(d.offer ? "Guardar cambios" : "Guardar oferta", { kind: "primary", size: "sm", ico: "check", onClick: async () => {
      await api.put(`/api/applications/${ctx.id}/offer`, {
        base_salary: val(f.base), variable: val(f.variable), currency: f.currency.value, modality: val(f.modality),
        vacation_days: val(f.vacation), start_date: val(f.start), deadline: val(f.deadline), equity: val(f.equity),
        benefits: val(f.benefits), notes: val(f.notes) });
      ctx.touch();
      toast("Oferta guardada · está en la columna «Oferta»");
      await redraw();
    } })));

  if (!d.offer) {
    if (d.status === "entrevista") {
      const open = button("Me han hecho una oferta", { size: "sm", ico: "sparkles", onClick: () => { open.replaceWith(form); } });
      return section("oferta", "Oferta", open);
    }
    return section("oferta", "Oferta", form);
  }

  const total = (o.base_salary || 0) + (o.variable || 0);
  const summary = h("div", { class: "offer-summary" },
    h("div", {}, h("b", {}, money(total, o.currency)), h("span", {}, "total anual"),
      o.variable ? h("small", {}, `${money(o.base_salary, o.currency)} fijo + ${money(o.variable, o.currency)} variable`) : null),
    h("div", { class: "row", style: { gap: "6px" } },
      o.modality ? h("span", { class: "chip" }, o.modality) : null,
      o.vacation_days ? h("span", { class: "chip" }, `${o.vacation_days} días de vacaciones`) : null,
      o.start_date ? h("span", { class: "chip" }, `empieza ${fmtDate(o.start_date)}`) : null,
      o.deadline ? h("span", { class: "chip warn" }, icon("clock"), `responder antes del ${fmtDate(o.deadline)}`) : null));
  const edit = button("Editar", { kind: "ghost", size: "sm", onClick: () => { edit.remove(); summary.replaceWith(form); } });

  const negoSlot = h("div");
  const target = h("input", { class: "input", placeholder: "Qué te gustaría conseguir (p. ej. 52.000 € y 3 días de remoto)" });
  const prios = tagInput([], "Prioridades: salario, remoto, formación… (Enter)");
  const nego = h("div", { class: "card sunken stack", style: { padding: "14px 16px", gap: "10px", marginTop: "12px" } },
    h("p", { style: { fontWeight: 600 } }, "Preparar la negociación"),
    target, prios,
    h("div", { class: "row" }, button("Preparar", { kind: "primary", size: "sm", ico: "sparkles", onClick: async (_, btn) => {
      btn.querySelector("span").textContent = "Pensando…";
      try {
        const n = await api.post(`/api/applications/${ctx.id}/negotiate`, { target: target.value.trim() || null, priorities: prios.value });
        negoSlot.replaceChildren(negotiationView(n, d, ctx, redraw));
      } finally { btn.querySelector("span").textContent = "Preparar"; }
    } }),
      d.other_offers ? button(`Comparar con tu${d.other_offers > 1 ? "s" : ""} otra${d.other_offers > 1 ? "s" : ""} oferta${d.other_offers > 1 ? "s" : ""}`, {
        size: "sm", ico: "chart", onClick: async () => {
          negoSlot.replaceChildren(comparisonView(await api.post("/api/applications/compare-offers", { priorities: prios.value }), d.id));
        } }) : null));
  return section("oferta", h("span", { class: "row between", style: { width: "100%" } }, "Oferta", edit), summary, nego, negoSlot);
}

function negotiationView(n, d, ctx, redraw) {
  return h("div", { class: "dossier", style: { marginTop: "14px" } },
    h("p", {}, n.assessment),
    n.leverage?.length ? h("div", { class: "dossier-block" }, h("h4", {}, "Tus bazas"), list(n.leverage, "ok")) : null,
    n.asks?.length ? h("div", { class: "dossier-block" }, h("h4", {}, "Qué pedir"), h("div", { class: "stack", style: { gap: "8px" } },
      n.asks.map((a) => h("div", { class: "card flat", style: { padding: "10px 12px" } },
        h("p", {}, h("span", { class: "chip accent", style: { marginRight: "8px" } }, a.item), h("b", {}, a.ask)),
        h("p", { class: "muted small", style: { marginTop: "4px" } }, a.rationale))))) : null,
    n.risks?.length ? h("div", { class: "dossier-block" }, h("h4", {}, "Cuidado con"), list(n.risks, "warn")) : null,
    n.call_script?.length ? h("div", { class: "dossier-block" }, h("h4", {}, "Si es por teléfono"),
      h("ol", { class: "bullets" }, n.call_script.map((x) => h("li", {}, x)))) : null,
    h("div", { class: "dossier-block" }, h("h4", {}, "Correo"), composer({ ...n.email, to: n.to }, "negociacion", d, ctx, redraw)));
}

function comparisonView(c, currentId) {
  return h("div", { style: { marginTop: "14px" } },
    h("div", { class: "compare" }, c.offers.map((o) => h("div", { class: `card flat compare-col ${o.application_id === currentId ? "current" : ""}` },
      h("p", { class: "faint small" }, o.company || "—"), h("b", {}, o.title),
      h("p", { class: "compare-total" }, o.total ? money(o.total, o.currency) : "—", h("small", {}, " / año")),
      o.score ? h("span", { class: "chip accent" }, `${o.score}/10`) : null,
      o.pros?.length ? list(o.pros, "ok") : null, o.cons?.length ? list(o.cons, "warn") : null))),
    h("p", { class: "sheet-hint" }, icon("sparkles"), h("span", {}, c.recommendation)),
    c.questions_to_clarify?.length ? h("div", { class: "dossier-block", style: { marginTop: "10px" } }, h("h4", {}, "Antes de decidir, aclara"),
      h("ul", { class: "bullets" }, c.questions_to_clarify.map((q) => h("li", {}, q)))) : null);
}

// ── Simulacro de entrevista ────────────────────────────────────
function mockSection(d, ctx) {
  if (!["aplicado", "entrevista"].includes(d.status)) return null;
  const slot = h("div");
  const past = d.mocks?.length ? h("div", { class: "row", style: { gap: "6px", marginBottom: "10px" } },
    h("span", { class: "faint small" }, "Anteriores:"),
    d.mocks.slice(-5).map((m) => h("span", { class: `chip ${m.average >= 4 ? "ok" : m.average >= 3 ? "warn" : ""}`, title: fmtDate(m.created_at, true) },
      `${fmtDate(m.created_at)} · ${m.average != null ? String(m.average).replace(".", ",") : "—"}/5`))) : null;
  const total = h("select", { class: "input", style: { width: "auto" } },
    [4, 6, 8].map((n) => h("option", { value: n, selected: n === 6 }, `${n} preguntas`)));
  const start = button("Empezar simulacro", {
    kind: d.prep ? "primary" : "", size: "sm", ico: "play",
    onClick: async (_, btn) => {
      btn.querySelector("span").textContent = "Preparando…";
      try {
        const step = await api.post(`/api/applications/${ctx.id}/mock`, { total: Number(total.value) });
        intro.remove();
        runMock(slot, ctx, step, Number(total.value));
      } finally { btn.querySelector("span").textContent = "Empezar simulacro"; }
    },
  });
  const intro = h("div", {},
    h("p", { class: "muted", style: { marginBottom: "10px" } },
      "La IA hace de entrevistador: una pregunta cada vez, y tras cada respuesta te puntúa (método STAR: situación, tarea, "
      + "acción y resultado) y te propone una versión mejor usando solo tu experiencia real."),
    h("div", { class: "row" }, total, start));
  return section("simulacro", "Simulacro de entrevista", past, intro, slot);
}

function runMock(slot, ctx, first, total) {
  const history = [];
  const log = h("div", { class: "mock-log" });
  const answer = h("textarea", { class: "input", rows: 5, placeholder: "Responde como lo harías en la entrevista… (⌘↵ para enviar)" });
  const progress = h("span", { class: "faint small" });
  let question = first.next_question;
  const ask = (q) => {
    question = q;
    log.append(h("div", { class: "bubble q" }, icon("user"), h("p", {}, q)));
    progress.textContent = `Pregunta ${history.length + 1} de ${total}`;
    answer.value = "";
    answer.focus();
  };
  const send = async (finish = false) => {
    const text = answer.value.trim();
    if (!finish && !text) throw new Error("Escribe tu respuesta");
    const body = { history, total, finish, current_question: text ? question : null, answer: text || null };
    const step = await api.post(`/api/applications/${ctx.id}/mock`, body);
    if (text) {
      log.append(h("div", { class: "bubble a" }, h("p", {}, text)));
      if (step.feedback) log.append(feedbackCard(step.feedback));
      history.push({ question, answer: text, feedback: step.feedback });
    }
    if (step.next_question) ask(step.next_question);
    else {
      ctx.touch();
      composer.remove();
      log.append(h("div", { class: "card sunken mock-summary" },
        h("p", { style: { fontWeight: 600 } }, icon("check"), ` Simulacro terminado`,
          step.average != null ? ` · nota media ${String(step.average).replace(".", ",")}/5` : ""),
        step.summary ? h("p", { style: { marginTop: "8px", whiteSpace: "pre-line" } }, step.summary) : null));
    }
    log.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  const reply = button("Responder", { kind: "primary", size: "sm", ico: "send", onClick: () => send(false) });
  answer.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); reply.click(); } });
  const composer = h("div", { class: "stack", style: { gap: "8px", marginTop: "10px" } }, answer,
    h("div", { class: "row" }, reply, button("Terminar", { kind: "ghost", size: "sm", onClick: () => send(true) }),
      h("span", { class: "spacer" }), progress));
  slot.replaceChildren(log, composer);
  ask(question);
}

function feedbackCard(f) {
  const dots = h("span", { class: "score-dots", title: `${f.score} de 5` },
    [1, 2, 3, 4, 5].map((i) => h("i", { class: i <= f.score ? "on" : "" })));
  const star = f.star ? h("div", { class: "row", style: { gap: "4px" } },
    [["situation", "Situación"], ["task", "Tarea"], ["action", "Acción"], ["result", "Resultado"]].map(([k, l]) =>
      h("span", { class: `chip ${f.star[k] ? "ok" : "warn"}` }, icon(f.star[k] ? "check" : "x"), l))) : null;
  return h("div", { class: "card mock-feedback" },
    h("div", { class: "row between" }, h("b", {}, "Valoración"), dots),
    star,
    f.strengths?.length ? list(f.strengths, "ok") : null,
    f.improve?.length ? list(f.improve, "warn") : null,
    f.better_answer ? h("details", {}, h("summary", { class: "small" }, "Ver una respuesta mejorada"),
      h("p", { class: "muted", style: { marginTop: "6px", whiteSpace: "pre-line" } }, f.better_answer)) : null);
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
      d.gmail ? button("Borrador en Gmail", { size: "sm", ico: "mail", title: "Lo deja como borrador dentro del hilo de la empresa; lo envías tú desde Gmail",
        onClick: async (_, btn) => {
          const r = await api.post(`/api/applications/${ctx.id}/gmail-draft`, { to: to.value.trim(), subject: subject.value, body: text.value });
          btn.replaceWith(h("a", { class: "btn sm", href: r.url, target: "_blank", rel: "noopener" }, icon("external"), h("span", {}, "Abrir borrador")));
          toast(r.thread_id ? "Borrador creado en el hilo de la empresa" : "Borrador creado en Gmail");
        } }) : null,
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
