// Afinar la búsqueda: perfil ideal, ronda de calibración (👍/👎), búsquedas con IA, sugerencias y
// «¿Por qué no vi esta oferta?».
import { api } from "./api.js";
import { button, field, h, icon, list, tagInput, toast } from "./ui.js";
import { sourceLabel } from "./views/_shared.js";

const CURRENCIES = ["USD", "CRC", "MXN", "COP", "EUR", "ARS", "CLP", "PEN", "GTQ", "BRL"];
const MODALITIES = [["remoto", "Remoto"], ["híbrido", "Híbrido"], ["presencial", "Presencial"]];

// ── Perfil ideal ─────────────────────────────────────────────────
export function idealSection(prefs, { onSaved, onCalibrate }) {
  const i = prefs.ideal || {};
  const f = {
    wanted: tagInput(i.roles_wanted || [], "p. ej. Backend Engineer, Desarrollador Python"),
    avoid: tagInput(i.roles_avoid || [], "p. ej. Soporte, QA manual, Ventas"),
    seniority: tagInput(i.seniority || [], "p. ej. mid, senior"),
    salary: h("input", { class: "input", type: "number", min: 0, step: 100, value: i.min_monthly_salary ?? "", placeholder: "Sin mínimo" }),
    currency: h("select", { class: "input" }, CURRENCIES.map((c) => h("option", { selected: c === (i.salary_currency || "USD") }, c))),
    likeInd: tagInput(i.industries_like || [], "p. ej. fintech, salud, producto"),
    avoidInd: tagInput(i.industries_avoid || [], "p. ej. apuestas, call center"),
    must: tagInput(i.must_haves || [], "p. ej. inglés en el día a día"),
    breakers: tagInput(i.deal_breakers || [], "p. ej. turnos de noche, viajar"),
    notes: h("textarea", { class: "input", rows: 2, placeholder: "Cuéntalo con tus palabras: qué te gustaría hacer, qué tipo de empresa…" }, i.notes || ""),
  };
  const mods = MODALITIES.map(([v, label]) => {
    const cb = h("input", { type: "checkbox", checked: (i.modalities || []).includes(v) });
    const el = h("label", { class: "chip check" }, cb, label);
    el.cb = cb;
    el.value = v;
    return el;
  });
  const collect = () => ({
    roles_wanted: f.wanted.value, roles_avoid: f.avoid.value, seniority: f.seniority.value,
    min_monthly_salary: f.salary.value === "" ? null : Number(f.salary.value), salary_currency: f.currency.value,
    modalities: mods.filter((m) => m.cb.checked).map((m) => m.value), industries_like: f.likeInd.value,
    industries_avoid: f.avoidInd.value, must_haves: f.must.value, deal_breakers: f.breakers.value, notes: f.notes.value.trim(),
  });
  const save = button("Guardar", { kind: "primary", size: "sm", ico: "check", onClick: async () => {
    const saved = await api.post("/api/agent/targeting/apply", { ideal: collect() });
    prefs.ideal = saved.ideal;
    toast("Guardado · la próxima búsqueda lo tendrá en cuenta");
    await onSaved?.(saved);
  } });
  const empty = !i.roles_wanted?.length && !i.notes && !i.min_monthly_salary;
  return h("div", { id: "sec-ideal" },
    h("h2", { class: "section-title" }, "Lo que buscas"),
    h("section", { class: "card stack" },
      h("div", { class: `ideal-hero ${empty ? "empty" : ""}` },
        h("div", { style: { flex: "1 1 280px", minWidth: 0 } },
          h("p", { style: { fontWeight: 600 } }, empty ? "Enséñale al agente lo que quieres" : "Tu búsqueda ideal"),
          h("p", { class: "muted small" }, "Tu CV dice lo que puedes hacer; esto le dice lo que quieres. La forma más rápida: vota 15 ofertas y la IA lo rellena por ti.")),
        button("Calibrar (2 min)", { kind: empty ? "primary" : "", ico: "sparkles", onClick: onCalibrate })),
      h("div", { class: "grid-2" }, field("Puestos que buscas", f.wanted), field("Puestos que NO quieres", f.avoid, "Se descartan por el título, sin gastar IA")),
      h("div", { class: "grid-3" }, field("Nivel", f.seniority),
        field("Salario mínimo (bruto al mes)", h("div", { class: "row", style: { flexWrap: "nowrap", gap: "6px" } }, f.salary, f.currency)),
        field("Modalidad", h("div", { class: "row", style: { gap: "6px" } }, mods))),
      h("div", { class: "grid-2" }, field("Sectores que te gustan", f.likeInd), field("Sectores que evitas", f.avoidInd)),
      h("div", { class: "grid-2" }, field("Imprescindible", f.must), field("Lo que la descarta", f.breakers)),
      field("En tus palabras", f.notes),
      h("div", { class: "row" }, save)));
}

// ── Ronda de calibración ─────────────────────────────────────────
export async function openCalibration({ onApplied } = {}) {
  const dlg = h("dialog", { class: "sheet calib", "aria-label": "Calibrar la búsqueda" });
  const body = h("div", { class: "sheet-body" }, h("div", { class: "skeleton skeleton-card" }));
  dlg.append(body);
  document.body.append(dlg);
  const close = () => { dlg.classList.add("out"); setTimeout(() => { dlg.close(); dlg.remove(); }, 260); };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.showModal();

  let jobs;
  try { jobs = (await api.get("/api/agent/calibration")).jobs; } catch (err) { toast(err.message, "error"); close(); return; }
  if (!jobs.length) {
    body.replaceChildren(h("div", { class: "center stack" }, h("h2", {}, "Aún no hay ofertas para votar"),
      h("p", { class: "muted" }, "Configura alguna fuente en «Dónde busca» y pulsa «Buscar ahora»; luego vuelve aquí."),
      button("Cerrar", { onClick: close })));
    return;
  }
  const votes = [];
  let idx = 0;
  const head = h("header", { class: "sheet-head" }, h("div", { style: { flex: 1 } },
    h("h2", {}, "Calibrar tu búsqueda"),
    h("p", { class: "muted" }, "¿Te interesaría esta oferta? No importa si podrías hacerla: lo que importa es si la querrías.")),
  button("", { ico: "x", size: "sm", title: "Cerrar (Esc)", onClick: close }));
  const progress = h("div", { class: "calib-progress" }, h("i"));
  const stage = h("div", { class: "calib-stage" });
  const reason = h("input", { class: "input", placeholder: "¿Por qué? (opcional, ayuda mucho)", maxlength: 200 });

  const vote = (v) => {
    votes.push({ job_id: jobs[idx].id, vote: v, reason: reason.value.trim() || null });
    reason.value = "";
    reason.blur();  // las flechas vuelven a votar
    const card = stage.firstElementChild;
    card?.animate([{ transform: "none", opacity: 1 }, { transform: `translateX(${v === "like" ? 40 : v === "dislike" ? -40 : 0}px) rotate(${v === "like" ? 2 : v === "dislike" ? -2 : 0}deg)`, opacity: 0 }],
      { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" }).finished.then(() => { idx++; draw(); });
  };
  const keys = (e) => {
    if (e.target === reason || e.target.tagName === "TEXTAREA" || idx >= jobs.length) return;  // escribiendo: las flechas mueven el cursor
    if (e.key === "ArrowRight") { e.preventDefault(); vote("like"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); vote("dislike"); }
    else if (e.key === "ArrowDown") { e.preventDefault(); vote("skip"); }
  };
  dlg.addEventListener("keydown", keys);

  const draw = () => {
    progress.firstElementChild.style.width = `${(100 * idx) / jobs.length}%`;
    if (idx >= jobs.length) return finish();
    const j = jobs[idx];
    stage.replaceChildren(h("article", { class: "card calib-card", style: { animation: "enter 260ms var(--ease-out) both" } },
      h("p", { class: "faint small" }, `${idx + 1} de ${jobs.length} · ${sourceLabel(j.source)}${j.score != null ? ` · el agente le dio ${Math.round(j.score)}` : ""}`),
      h("h3", { class: "calib-title" }, j.title),
      h("p", { class: "muted" }, [j.company, j.location, j.remote ? "Remoto" : null, j.salary].filter(Boolean).join(" · ")),
      h("p", { class: "calib-snippet" }, j.snippet),
      j.url ? h("a", { class: "small", href: j.url, target: "_blank", rel: "noopener" }, icon("external"), " Ver la oferta completa") : null));
  };

  const finish = async () => {
    const liked = votes.filter((v) => v.vote !== "skip").length;
    const notes = h("textarea", { class: "input", rows: 3, placeholder: "¿Algo más que deba saber? (p. ej. «quiero salir de la consultoría», «mínimo 2 500 USD»)" });
    stage.replaceChildren(h("div", { class: "stack", style: { animation: "enter 260ms var(--ease-out) both" } },
      h("h3", {}, liked ? `¡Listo! ${liked} votos` : "No votaste ninguna"),
      h("p", { class: "muted" }, "La IA va a deducir qué buscas de verdad y propondrá búsquedas nuevas. Nada se aplica hasta que lo confirmes."),
      notes,
      h("div", { class: "row" },
        liked ? button("Aprender de mis votos", { kind: "primary", ico: "sparkles", onClick: async (_, b) => {
          b.querySelector("span").textContent = "Pensando…";
          try { showProposal(await api.post("/api/agent/calibration", { votes, notes: notes.value })); }
          finally { b.querySelector("span").textContent = "Aprender de mis votos"; }
        } }) : null,
        button("Cerrar", { kind: "ghost", onClick: close }))));
  };

  const showProposal = (r) => {
    const i = r.ideal;
    const line = (label, xs) => xs?.length ? h("p", {}, h("b", {}, `${label}: `), xs.join(", ")) : null;
    stage.replaceChildren(h("div", { class: "stack", style: { animation: "enter 260ms var(--ease-out) both" } },
      h("div", { class: "dossier-block" }, h("h4", {}, "Lo que he aprendido"), list(r.learned, "ok")),
      h("div", { class: "card sunken stack", style: { padding: "14px 16px", gap: "6px" } },
        h("h4", {}, "Tu perfil ideal"),
        line("Buscas", i.roles_wanted), line("No quieres", i.roles_avoid), line("Nivel", i.seniority),
        i.min_monthly_salary ? h("p", {}, h("b", {}, "Salario mínimo: "), `${Number(i.min_monthly_salary).toLocaleString("es-CR")} ${i.salary_currency} al mes`) : null,
        line("Modalidad", i.modalities), line("Sectores", i.industries_like), line("Evitas", i.industries_avoid),
        line("Imprescindible", i.must_haves), line("Lo descarta", i.deal_breakers),
        i.notes ? h("p", { class: "muted small" }, i.notes) : null),
      h("div", { class: "card sunken stack", style: { padding: "14px 16px", gap: "6px" } },
        h("h4", {}, "Búsquedas propuestas"),
        line("Get on Board", r.queries.getonbrd), line("Remotive", r.queries.remotive), line("Adzuna", r.queries.adzuna),
        h("p", { class: "faint small" }, r.queries.explanation)),
      h("div", { class: "row" },
        button("Aplicar todo", { kind: "primary", ico: "check", onClick: async () => {
          await api.post("/api/agent/targeting/apply", { ideal: r.ideal, queries: r.queries });
          toast("Aplicado · pulsa «Buscar ahora» para ver la diferencia");
          close();
          await onApplied?.();
        } }),
        button("Solo el perfil", { onClick: async () => {
          await api.post("/api/agent/targeting/apply", { ideal: r.ideal });
          toast("Perfil ideal guardado");
          close();
          await onApplied?.();
        } }),
        button("Descartar", { kind: "ghost", onClick: close }))));
  };

  body.replaceChildren(head, progress, stage,
    h("div", { class: "calib-actions" },
      reason,
      h("div", { class: "row", style: { justifyContent: "center" } },
        button("No me interesa", { ico: "x", onClick: () => vote("dislike"), title: "← flecha izquierda" }),
        button("Saltar", { kind: "ghost", onClick: () => vote("skip"), title: "↓ flecha abajo" }),
        button("Me interesa", { kind: "primary", ico: "check", onClick: () => vote("like"), title: "→ flecha derecha" })),
      h("p", { class: "faint small center" }, "Atajos de teclado: ← no · ↓ saltar · → sí")));
  draw();
  // al terminar, las acciones de voto sobran
  const obs = new MutationObserver(() => { body.querySelector(".calib-actions").hidden = idx >= jobs.length; });
  obs.observe(stage, { childList: true });
}

// ── Sugerencias para afinar ─────────────────────────────────────
export async function tuningSection(ctx, { onChanged, onCalibrate, onSuggestQueries }) {
  const { suggestions } = await api.get("/api/agent/tuning").catch(() => ({ suggestions: [] }));
  if (!suggestions.length) return null;
  const rows = suggestions.map((s) => {
    const row = h("div", { class: "tune-row" },
      h("span", { class: "chip" }, s.kind),
      h("p", { style: { flex: 1, minWidth: 0 } }, s.text));
    const a = s.action;
    let btn;
    if (a.type === "calibrate") btn = button(a.label, { size: "sm", kind: "primary", ico: "sparkles", onClick: onCalibrate });
    else if (a.type === "suggest_queries") btn = button(a.label, { size: "sm", ico: "sparkles", onClick: onSuggestQueries });
    else if (a.type === "edit_ideal") btn = button(a.label, { size: "sm", onClick: () => document.getElementById("sec-ideal")?.scrollIntoView({ behavior: "smooth" }) });
    else if (a.type === "route") btn = button(a.label, { size: "sm", onClick: () => document.getElementById("sec-donde")?.scrollIntoView({ behavior: "smooth" }) });
    else btn = button(a.label, { size: "sm", onClick: async () => {
      await api.post("/api/agent/tuning/apply", { id: s.id });
      toast("Aplicado");
      row.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200 }).finished.then(() => row.remove());
      await onChanged?.();
    } });
    row.append(btn);
    return row;
  });
  return h("div", {}, h("h2", { class: "section-title" }, "Afinar"),
    h("section", { class: "card", style: { padding: "8px 18px" } }, rows));
}

// ── ¿Por qué no vi esta oferta? ─────────────────────────────────
export function traceSection(ctx, { onChanged }) {
  const url = h("input", { class: "input", placeholder: "Pega el enlace de una oferta que esperabas ver" });
  const text = h("textarea", { class: "input", rows: 4, placeholder: "…o pega aquí el texto de la oferta (si la web pide iniciar sesión, p. ej. LinkedIn)", hidden: true });
  const out = h("div");
  const go = button("Investigar", { kind: "primary", ico: "search", onClick: async (_, b) => {
    if (!url.value.trim() && !text.value.trim()) throw new Error("Pega un enlace o el texto");
    b.querySelector("span").textContent = "Investigando…";
    try {
      const r = await api.post("/api/agent/trace", { url: url.value.trim() || null, text: text.value.trim() || null });
      out.replaceChildren(traceResult(r, url.value.trim(), ctx, onChanged));
    } finally { b.querySelector("span").textContent = "Investigar"; }
  } });
  return h("div", {}, h("h2", { class: "section-title" }, "¿Por qué no vi esta oferta?"),
    h("section", { class: "card stack" },
      h("p", { class: "muted small" }, "El agente te dice en qué paso se quedó (fuentes, filtros o la IA) y cómo corregirlo."),
      h("div", { class: "row", style: { flexWrap: "nowrap" } }, url, go),
      h("button", { type: "button", class: "btn ghost sm", style: { justifySelf: "start" }, onClick: (e) => { text.hidden = !text.hidden; e.currentTarget.remove(); } }, "Pegar el texto en su lugar"),
      text, out));
}

function traceResult(r, url, ctx, onChanged) {
  const ico = { ok: ["ok", "check"], warn: ["warn", "alert"], error: ["bad", "x"] };
  const actions = [];
  for (const s of r.steps) {
    if (s.action?.type === "add_source") actions.push(button(s.action.label, { size: "sm", ico: "plus", onClick: async (_, b) => {
      const prefs = await api.get("/api/agent/preferences");
      const list_ = prefs.sources[s.action.provider] || [];
      if (!list_.includes(s.action.slug)) list_.push(s.action.slug);
      await api.put("/api/agent/preferences", { ...prefs, sources: { ...prefs.sources, [s.action.provider]: list_ } });
      b.replaceWith(h("span", { class: "chip ok" }, icon("check"), "Añadida a tus fuentes"));
      await onChanged?.();
    } }));
  }
  if (r.can_prepare) actions.push(button("Añadirla y preparar candidatura", { size: "sm", kind: "primary", ico: "sparkles", onClick: async (_, b) => {
    if (!ctx.cv) throw new Error("Sube primero tu CV");
    let jobId = r.job_id;
    if (!jobId) jobId = (await api.post("/api/jobs", r.text ? { text: r.text, url: url || null } : { url })).id;
    await api.post(`/api/agent/jobs/${jobId}/vote`, { vote: "like" });
    await api.post(`/api/jobs/${jobId}/prepare`, null, { cv_id: ctx.cv.id });
    b.replaceWith(h("span", { class: "chip ok" }, icon("check"), "En tu Bandeja · el agente aprende de esto"));
    ctx.refreshCounts();
  } }));
  return h("div", { class: "stack", style: { gap: "10px", animation: "enter 260ms var(--ease-out) both" } },
    h("div", { class: "trace" }, r.steps.map((s) => {
      const [kind, i] = ico[s.status] || ["", "clock"];
      return h("div", { class: "trace-step" }, h("span", { class: `diag-ico ${kind}` }, icon(i)),
        h("div", {}, h("b", {}, s.stage), h("p", { class: "muted small" }, s.detail),
          s.hint ? h("p", { class: "small", style: { color: "var(--accent)" } }, s.hint) : null));
    })),
    h("p", { class: "sheet-hint", style: { marginTop: 0 } }, icon("sparkles"), h("span", {}, r.verdict)),
    actions.length ? h("div", { class: "row" }, actions) : null);
}

// ── Búsquedas con IA ─────────────────────────────────────────────
export async function suggestQueries(onApplied) {
  const q = await api.post("/api/agent/queries/suggest");
  const parts = [["Get on Board", q.getonbrd], ["Remotive", q.remotive], ["Adzuna", q.adzuna]].filter(([, xs]) => xs.length)
    .map(([n, xs]) => `${n}: ${xs.join(", ")}`).join(" · ");
  if (!confirm(`Búsquedas propuestas por la IA:\n\n${parts}\n\n${q.explanation}\n\n¿Aplicarlas? (sustituyen a las actuales)`)) return;
  await api.post("/api/agent/targeting/apply", { queries: q });
  toast("Búsquedas actualizadas");
  await onApplied?.();
}

// ── 👍/👎 ────────────────────────────────────────────────────────
export function voteButtons(jobId, current, { onPrepare } = {}) {
  const wrap = h("span", { class: "votes" });
  const draw = (v) => {
    wrap.replaceChildren(
      h("button", { type: "button", class: `vote ${v === "like" ? "on" : ""}`, title: "Más como esta", onClick: () => cast("like") }, "👍"),
      h("button", { type: "button", class: `vote ${v === "dislike" ? "on" : ""}`, title: "Menos como esta", onClick: () => cast("dislike") }, "👎"));
  };
  const cast = async (v) => {
    const r = await api.post(`/api/agent/jobs/${jobId}/vote`, { vote: v });
    draw(v);
    toast(v === "like" ? "👍 Buscará más como esta" : "👎 Evitará ofertas como esta");
    if (r.can_prepare && onPrepare) onPrepare();
  };
  draw(current);
  return wrap;
}
