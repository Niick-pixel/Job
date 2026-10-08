// 🤖 Agente: qué busca, dónde busca, qué ha hecho.
import { api } from "../api.js";
import { button, field, fmtDate, h, icon, pageHead, stagger, tagInput, toast, toggle } from "../ui.js";
import { agentButton, sourceLabel } from "./_shared.js";

const STATUS = {
  "": "Todas", en_bandeja: "En bandeja", candidata: "Candidatas", aprobada: "Aprobadas",
  criba_baja: "Descartadas por IA", filtrada: "Filtradas", descartada: "Descartadas por ti",
};

export async function render(root, ctx) {
  const [prefs, runs] = await Promise.all([api.get("/api/agent/preferences"), api.get("/api/agent/runs", { limit: 1 })]);
  const statusSlot = h("div");
  const funnelSlot = h("div");
  renderStatus(statusSlot, runs[0]);

  const head = pageHead("Agente", "Busca ofertas cada 3 horas, aunque la app esté cerrada",
    agentButton("Buscar ahora", async (run) => { renderStatus(statusSlot, run); loadFunnel(funnelSlot, ""); ctx.refreshCounts(); }));

  root.replaceChildren(stagger(h("div", {}, head, statusSlot, preferencesForm(prefs, root, ctx), funnelSection(funnelSlot))));
  loadFunnel(funnelSlot, "");
}

function renderStatus(slot, run) {
  if (!run) {
    slot.replaceChildren(h("div", { class: "card sunken center" }, h("p", { class: "muted" }, "Aún no se ha ejecutado. Pulsa «Buscar ahora» o espera a la próxima pasada automática.")));
    return;
  }
  const s = run.stats || {};
  const tiles = [["Revisadas", s.descubiertas], ["Nuevas", s.nuevas], ["Filtradas", (s.filtradas || 0) + (s.duplicadas || 0)],
    ["Descartadas IA", s.criba_baja], ["Preparadas", s.preparadas]];
  slot.replaceChildren(h("section", { class: "card" },
    h("div", { class: "row between" },
      h("div", { class: "row" }, h("span", { class: `dot ${run.status === "ok" ? "ok" : run.status === "running" ? "warn pulse" : "bad"}` }),
        h("b", {}, run.status === "running" ? "Buscando ahora…" : "Última búsqueda"),
        h("span", { class: "faint" }, `${fmtDate(run.started_at, true)} · ${run.trigger === "schedule" ? "automática" : "manual"}`)),
      s.autoconfigurado ? h("span", { class: "chip accent" }, icon("sparkles"), "Configurado desde tu CV") : null),
    run.error ? h("p", { class: "chip bad", style: { marginTop: "12px", height: "auto", padding: "6px 10px", whiteSpace: "normal" } }, run.error) : null,
    h("div", { class: "grid-3", style: { gridTemplateColumns: "repeat(5, 1fr)", marginTop: "10px" } },
      tiles.map(([label, v]) => h("div", { class: "stat" }, h("b", {}, v ?? 0), h("span", {}, label)))),
    Object.keys(s.fuentes || {}).length ? h("details", { class: "disclosure" },
      h("summary", {}, icon("chevron", "chev"), "Detalle por fuente"),
      h("div", { class: "body" }, h("table", { class: "table" }, h("tbody", {},
        Object.entries(s.fuentes).map(([k, v]) => h("tr", {}, h("td", {}, k),
          h("td", { class: typeof v === "number" ? "" : "faint" }, typeof v === "number" ? `${v} ofertas` : v))))))) : null));
}

function preferencesForm(p, root, ctx) {
  const src = p.sources || {};
  const f = {
    enabled: toggle(p.enabled),
    titles: tagInput(p.target_titles, "p. ej. Backend Developer"),
    exclude: tagInput(p.exclude_keywords, "p. ej. prácticas, guardias"),
    locations: tagInput(p.locations, "p. ej. Madrid, España"),
    blacklist: tagInput(p.blacklist_companies, "Empresas a evitar"),
    remoteOk: toggle(p.remote_ok),
    remoteOnly: toggle(p.remote_only),
    minSalary: h("input", { class: "input", type: "number", min: 0, step: 1000, value: p.min_salary || "", placeholder: "Sin mínimo" }),
    maxAge: h("input", { class: "input", type: "number", min: 1, value: p.max_age_days }),
    triage: range(p.triage_threshold), prepare: range(p.prepare_threshold),
    topN: h("input", { class: "input", type: "number", min: 1, max: 50, value: p.deep_match_top_n }),
    greenhouse: tagInput(src.greenhouse, "identificador, p. ej. airbnb"),
    lever: tagInput(src.lever, "identificador"),
    ashby: tagInput(src.ashby, "identificador"),
    remotive: tagInput(src.remotive_queries, "p. ej. python backend"),
    adzuna: tagInput(src.adzuna_queries, "p. ej. desarrollador python"),
    country: h("input", { class: "input", value: src.adzuna_country || "es", maxlength: 2 }),
    alerts: toggle(src.email_alerts),
    digest: toggle(p.digest_enabled ?? true),
    digestHour: h("select", { class: "input", style: { width: "auto" } },
      Array.from({ length: 24 }, (_, i) => h("option", { value: i, selected: i === (p.digest_hour ?? 9) }, `${String(i).padStart(2, "0")}:00`))),
  };
  const row = (label, hint, ctrl) => h("div", { class: "row between", style: { padding: "10px 0" } },
    h("div", {}, h("p", { style: { fontWeight: 550 } }, label), hint ? h("p", { class: "faint small" }, hint) : null), ctrl);

  const collect = () => ({
    ...p, enabled: f.enabled.input.checked, target_titles: f.titles.value, exclude_keywords: f.exclude.value,
    locations: f.locations.value, blacklist_companies: f.blacklist.value, remote_ok: f.remoteOk.input.checked,
    remote_only: f.remoteOnly.input.checked, min_salary: Number(f.minSalary.value) || null,
    max_age_days: Number(f.maxAge.value) || 30, triage_threshold: f.triage.value, prepare_threshold: f.prepare.value,
    deep_match_top_n: Number(f.topN.value) || 10,
    digest_enabled: f.digest.input.checked, digest_hour: Number(f.digestHour.value),
    sources: { ...src, greenhouse: f.greenhouse.value, lever: f.lever.value, ashby: f.ashby.value,
      remotive_queries: f.remotive.value, adzuna_queries: f.adzuna.value,
      adzuna_country: (f.country.value || "es").toLowerCase(), email_alerts: f.alerts.input.checked },
  });
  const save = button("Guardar cambios", {
    kind: "primary", ico: "check",
    onClick: async () => { await api.put("/api/agent/preferences", collect()); toast("Preferencias guardadas"); },
  });
  const addBoard = async (b) => {
    if (!f[b.provider].add(b.slug)) { toast(`${b.slug} ya estaba en ${PROVIDER[b.provider]}`); return; }
    await api.put("/api/agent/preferences", collect());
    toast(`${b.query} añadida (${PROVIDER[b.provider]} · ${b.slug})`);
  };

  return h("div", {},
    h("h2", { class: "section-title" }, "Qué buscas"),
    h("section", { class: "card stack" },
      row("Agente activado", "Busca y prepara candidaturas en segundo plano", f.enabled),
      row("Resumen diario", "Un aviso cada mañana con entrevistas, candidaturas nuevas y seguimientos pendientes",
        h("div", { class: "row", style: { flexWrap: "nowrap" } }, f.digestHour, f.digest)),
      h("hr", { class: "divider", style: { margin: "4px 0" } }),
      h("div", { class: "grid-2" },
        field("Puestos objetivo", f.titles, "Vacío = deja que la IA decida con tu CV"),
        field("Excluir si contiene", f.exclude)),
      h("div", { class: "grid-2" }, field("Ubicaciones", f.locations), field("Empresas a evitar", f.blacklist)),
      h("div", { class: "grid-2" }, row("Acepto remoto", null, f.remoteOk), row("Solo remoto", null, f.remoteOnly)),
      h("div", { class: "grid-3" }, field("Salario mínimo anual", f.minSalary), field("Antigüedad máxima (días)", f.maxAge),
        field("Análisis completos por pasada", f.topN)),
      h("div", { class: "grid-2" },
        field("Umbral de criba rápida", f.triage, "Por debajo, la IA la descarta sin gastar más"),
        field("Umbral para preparar candidatura", f.prepare, "A partir de aquí llega a tu Bandeja"))),

    h("h2", { class: "section-title" }, "Dónde busca"),
    h("section", { class: "card stack" },
      discoverBox(addBoard),
      h("hr", { class: "divider", style: { margin: "4px 0" } }),
      h("p", { class: "muted small" }, "O añádelas a mano: el identificador está en la URL de la página de empleo de la empresa, p. ej. boards.greenhouse.io/",
        h("b", {}, "airbnb"), ", jobs.lever.co/", h("b", {}, "empresa"), ", jobs.ashbyhq.com/", h("b", {}, "empresa"), "."),
      h("div", { class: "grid-3" }, field("Greenhouse", f.greenhouse), field("Lever", f.lever), field("Ashby", f.ashby)),
      h("div", { class: "grid-3" }, field("Remotive (remoto)", f.remotive), field("Adzuna", f.adzuna, "Requiere clave en Ajustes"), field("País Adzuna", f.country)),
      row("Alertas de empleo de tu correo", "LinkedIn, InfoJobs, Indeed… (la vía segura para LinkedIn)", f.alerts)),

    h("div", { class: "row", style: { justifyContent: "center", marginTop: "20px" } },
      button("Rellenar desde mi CV", { ico: "sparkles", onClick: async () => {
        if (!ctx.cv) { ctx.go("perfil"); throw new Error("Primero sube tu CV"); }
        await api.post("/api/agent/preferences/auto");
        toast("Ubicación y búsquedas deducidas de tu CV");
        await render(root, ctx);
      } }),
      save));
}

const PROVIDER = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };

function discoverBox(addBoard) {
  const names = tagInput([], "Escribe empresas o pega la URL de su página de empleo");
  const results = h("div", { class: "stack", style: { gap: "8px" } });
  const search = button("Buscar portales", {
    kind: "primary", ico: "search",
    onClick: async () => {
      const companies = names.value;
      if (!companies.length) throw new Error("Escribe al menos una empresa");
      results.replaceChildren(h("div", { class: "skeleton", style: { height: "44px" } }));
      const r = await api.post("/api/agent/discover", { companies });
      results.replaceChildren(
        ...r.found.map((b) => h("div", { class: "card sunken row between", style: { padding: "10px 14px", animation: "enter 240ms var(--ease-out) both" } },
          h("div", { style: { minWidth: 0, flex: 1 } },
            h("b", {}, b.query), h("span", { class: "chip", style: { marginLeft: "8px" } }, `${PROVIDER[b.provider]} · ${b.slug}`),
            h("p", { class: "faint small", style: { marginTop: "4px" } },
              b.jobs ? `${b.jobs} ofertas · p. ej. ${b.sample.slice(0, 2).join(" · ")}` : "Sin ofertas publicadas ahora mismo")),
          h("a", { class: "btn ghost sm", href: b.url, target: "_blank", rel: "noopener" }, icon("external")),
          button("Añadir", { size: "sm", ico: "plus", onClick: async (_, btn) => { await addBoard(b); btn.replaceWith(h("span", { class: "chip ok" }, icon("check"), "Añadida")); } }))),
        r.missing.length ? h("p", { class: "faint small" }, `Sin portal en Greenhouse, Lever ni Ashby: ${r.missing.join(", ")}. `,
          "Puede que usen otro sistema (Workday, InfoJobs…): sus ofertas te llegarán por las alertas de correo.") : "");
    },
  });
  return h("div", { class: "stack", style: { gap: "10px" } },
    h("div", {}, h("p", { style: { fontWeight: 600 } }, "Descubrir empresas"),
      h("p", { class: "faint small" }, "Escribe las empresas que te interesan y la app encuentra sus portales de empleo. Revisa los resultados antes de añadirlos.")),
    h("div", { class: "row", style: { flexWrap: "nowrap", alignItems: "flex-start" } }, h("div", { style: { flex: 1 } }, names), search),
    results);
}

function range(value) {
  const out = h("span", { class: "chip accent", style: { minWidth: "44px", justifyContent: "center" } }, String(value));
  const input = h("input", { type: "range", min: 0, max: 100, value, style: { flex: 1, accentColor: "var(--accent)" } });
  input.addEventListener("input", () => { out.textContent = input.value; });
  const wrap = h("div", { class: "row", style: { flexWrap: "nowrap" } }, input, out);
  Object.defineProperty(wrap, "value", { get: () => Number(input.value) });
  return wrap;
}

function funnelSection(slot) {
  return h("div", {}, h("h2", { class: "section-title" }, "Ofertas descubiertas"), slot);
}

async function loadFunnel(slot, status) {
  const jobs = await api.get("/api/agent/jobs", { status });
  const filters = h("div", { class: "row", style: { justifyContent: "center", gap: "6px", marginBottom: "14px" } },
    Object.entries(STATUS).map(([id, label]) => h("button", {
      class: `chip ${id === status ? "accent" : ""}`, type: "button", style: { cursor: "pointer" },
      onClick: () => loadFunnel(slot, id),
    }, label)));
  const body = jobs.length
    ? h("section", { class: "card flat", style: { padding: "4px 8px", overflowX: "auto" } }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, ["Puesto", "Fuente", "Encaje", "Motivo"].map((t) => h("th", {}, t)))),
      h("tbody", {}, jobs.map((j) => h("tr", {},
        h("td", {}, j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title) : j.title,
          h("div", { class: "faint small" }, [j.company, j.location].filter(Boolean).join(" · "))),
        h("td", { class: "small" }, sourceLabel(j.source)),
        h("td", {}, j.score != null ? h("span", { class: "chip" }, `${Math.round(j.score)}`) : ""),
        h("td", { class: "small muted", style: { maxWidth: "320px" } }, j.reason || STATUS[j.status] || j.status))))))
    : h("p", { class: "center faint", style: { padding: "20px" } }, "Nada por aquí todavía.");
  slot.replaceChildren(filters, body);
}
