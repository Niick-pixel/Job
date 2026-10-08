// 📊 Resultados: qué te está funcionando (fuentes, versiones de CV, tiempos) y cómo trabaja el agente.
import { api } from "../api.js";
import { empty, h, icon, pageHead, stagger } from "../ui.js";

const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);

export async function render(root, ctx) {
  const s = await api.get("/api/stats");
  const f = s.funnel;
  const head = pageHead("Resultados", f.applied
    ? `${f.applied} candidatura${f.applied > 1 ? "s" : ""} enviada${f.applied > 1 ? "s" : ""} · ${pct(f.responses, f.applied)} % con respuesta`
    : null);
  if (!f.applied) {
    root.replaceChildren(head, empty("chart", "Aún no hay resultados",
      "Cuando marques candidaturas como enviadas verás aquí tu tasa de respuesta, qué fuentes y qué versión de tu CV funcionan mejor y cuánto tardan las empresas en contestar."));
    return;
  }
  const manyCvs = s.by_cv.length > 1 || (s.by_cv[0] && s.by_cv[0].key !== null);
  root.replaceChildren(head, stagger(h("div", { class: "stack" },
    kpis(s), funnel(f), weekly(s.weekly),
    breakdown("Por fuente", "Dónde encontraste la oferta", s.by_source, s.source_weights, pct(f.responses, f.applied)),
    manyCvs ? breakdown("Por versión de CV", "Con qué CV aplicaste", s.by_cv, {}, pct(f.responses, f.applied)) : null,
    agent(s.agent))));
}

function kpis(s) {
  const f = s.funnel, d = s.reply_days;
  const kpi = (value, label, sub, kind = "") => h("div", { class: `card kpi ${kind}` },
    h("b", {}, value), h("span", {}, label), sub ? h("small", {}, sub) : null);
  return h("div", { class: "kpis" },
    kpi(f.applied, "Enviadas", f.tracked > f.applied ? `${f.tracked - f.applied} más en «Por aplicar»` : null),
    kpi(`${pct(f.responses, f.applied)} %`, "Con respuesta", `${f.responses} de ${f.applied}`, "accent"),
    kpi(`${pct(f.interviews, f.applied)} %`, "Entrevistas", `${f.interviews} en total`, "warn"),
    kpi(f.offers, "Ofertas", f.rejected ? `${f.rejected} rechazo${f.rejected > 1 ? "s" : ""}` : null, "ok"),
    kpi(d.median != null ? `${d.median} d` : "—", "Tardan en responder", d.count ? `mediana de ${d.count} respuesta${d.count > 1 ? "s" : ""}` : "sin datos aún"));
}

function funnel(f) {
  const steps = [["Enviadas", f.applied, ""], ["Con respuesta", f.responses, "accent"], ["Entrevista", f.interviews, "warn"], ["Oferta", f.offers, "ok"]];
  return h("section", { class: "card" },
    h("h3", { style: { marginBottom: "14px" } }, "Embudo"),
    h("div", { class: "stack", style: { gap: "10px" } }, steps.map(([label, n, kind]) =>
      h("div", { class: "bar-row" }, h("span", { class: "bar-label" }, label),
        h("div", { class: "bar" }, h("i", { class: kind, style: { "--w": `${Math.max(pct(n, f.applied), n ? 3 : 0)}%` } })),
        h("span", { class: "bar-value" }, `${n}`, h("small", {}, ` · ${pct(n, f.applied)} %`))))),
    f.applied < 10 ? h("p", { class: "faint small", style: { marginTop: "12px" } },
      icon("alert"), " Con menos de 10 candidaturas los porcentajes cambian mucho: tómalos como orientación.") : null);
}

function weekly(weeks) {
  const max = Math.max(1, ...weeks.map((w) => w.applied));
  const label = (iso) => new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short" });
  return h("section", { class: "card" },
    h("div", { class: "row between", style: { marginBottom: "14px" } }, h("h3", {}, "Ritmo semanal"),
      h("span", { class: "faint small" }, "candidaturas enviadas · últimas 12 semanas")),
    h("div", { class: "columns-chart" }, weeks.map((w) => h("div", { class: "col", title: `Semana del ${label(w.week)}: ${w.applied}` },
      h("i", { style: { "--h": `${(100 * w.applied) / max}%` } }, w.applied ? h("span", {}, w.applied) : null),
      h("small", {}, label(w.week))))));
}

function breakdown(title, subtitle, groups, weights = {}, overall = 0) {
  if (!groups.length) return null;
  // «La que mejor funciona»: solo con datos suficientes y por encima de tu media
  const best = Math.max(...groups.filter((g) => g.enough && g.response_rate > overall).map((g) => g.response_rate), -1);
  return h("section", { class: "card" },
    h("div", { class: "row between", style: { marginBottom: "12px" } }, h("h3", {}, title), h("span", { class: "faint small" }, subtitle)),
    h("div", { class: "stack", style: { gap: "12px" } }, groups.map((g) => {
      const w = weights[g.key];
      return h("div", {},
        h("div", { class: "row between", style: { marginBottom: "6px" } },
          h("span", {}, h("b", {}, g.label), g.enough && g.response_rate === best && groups.length > 1 ? h("span", { class: "chip ok", style: { marginLeft: "8px" } }, "la que mejor funciona") : null,
            !g.enough ? h("span", { class: "chip", style: { marginLeft: "8px" } }, "pocos datos") : null),
          h("span", { class: "muted small" }, `${g.applied} enviadas · ${g.response_rate} % respuesta · ${g.interview_rate} % entrevista`)),
        h("div", { class: "bar" }, h("i", { class: "accent", style: { "--w": `${Math.max(g.response_rate, g.responses ? 3 : 0)}%` } })),
        w && Math.abs(w - 1) >= 0.02 ? h("p", { class: "faint small", style: { marginTop: "4px" } }, icon("bot"),
          ` El agente la prioriza un ${Math.abs(Math.round((w - 1) * 100))} % ${w > 1 ? "más" : "menos"}`) : null);
    })));
}

function agent(a) {
  if (!a.discovered) return null;
  const item = (n, label) => h("div", { class: "agent-step" }, h("b", {}, n), h("span", {}, label));
  return h("section", { class: "card" },
    h("div", { class: "row between", style: { marginBottom: "12px" } }, h("h3", {}, "El agente"), h("span", { class: "faint small" }, "ofertas que ha revisado por ti")),
    h("div", { class: "agent-steps" },
      item(a.discovered, "encontradas"), icon("chevron"), item(a.filtered + a.low_score, "descartadas solas"), icon("chevron"),
      item(a.in_inbox + a.approved + a.discarded, "llegaron a tu Bandeja"), icon("chevron"), item(a.approved, "aprobaste")),
    a.top_discard_reasons.length ? h("div", { style: { marginTop: "14px" } },
      h("p", { class: "faint small", style: { marginBottom: "6px" } }, "Por qué descartas más (el agente lo aprende):"),
      h("div", { class: "row", style: { gap: "6px" } }, a.top_discard_reasons.map((r) => h("span", { class: "chip" }, `${r.reason} · ${r.count}`)))) : null);
}
