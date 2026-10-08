// 🔍 Ofertas: analizar una oferta concreta (texto o enlace) y prepararla.
import { api } from "../api.js";
import { button, field, fmtDate, h, icon, list, pageHead, ring, stagger, toast, urgencyChip } from "../ui.js";
import { linkButton } from "./_shared.js";

export async function render(root, ctx) {
  let mode = "text";
  const text = h("textarea", { class: "input", rows: 8, placeholder: "Pega aquí el texto completo de la oferta…" });
  const url = h("input", { class: "input", type: "url", placeholder: "https://…", hidden: true });
  const date = h("input", { class: "input", type: "date", max: new Date().toISOString().slice(0, 10) });
  const applicants = h("input", { class: "input", type: "number", min: 0, placeholder: "—" });

  const seg = h("div", { class: "nav", style: { display: "inline-flex", boxShadow: "none" } });
  const thumb = h("span", { class: "nav-thumb" });
  const segBtn = (id, label) => h("button", { type: "button", "data-mode": id, onClick: () => setMode(id) }, h("span", {}, label));
  seg.append(thumb, segBtn("text", "Pegar texto"), segBtn("url", "Enlace"));
  const setMode = (m) => {
    mode = m;
    text.hidden = m !== "text";
    url.hidden = m !== "url";
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
    const b = seg.querySelector(`[data-mode=${m}]`);
    requestAnimationFrame(() => { thumb.style.width = `${b.offsetWidth}px`; thumb.style.transform = `translateX(${b.offsetLeft}px)`; });
    (m === "text" ? text : url).focus();
  };

  const detail = h("div");
  const recent = h("div");

  const analyze = button("Analizar oferta", {
    kind: "primary", ico: "sparkles",
    onClick: async () => {
      const payload = {
        text: mode === "text" ? text.value.trim() || null : null,
        url: mode === "url" ? url.value.trim() || null : null,
        posted_date: date.value || null,
        applicants_count: applicants.value ? Number(applicants.value) : null,
      };
      if (!payload.text && !payload.url) throw new Error("Pega el texto o el enlace de la oferta");
      const job = await api.post("/api/jobs", payload);
      text.value = url.value = "";
      toast("Oferta analizada");
      await showJob(detail, job, ctx);
      loadRecent(recent, detail, ctx);
    },
  });

  const form = h("section", { class: "card" },
    h("div", { class: "row between", style: { marginBottom: "14px" } }, seg, h("span", { class: "faint small" }, "La IA extrae requisitos, salario y fecha")),
    text, url,
    h("div", { class: "grid-2", style: { marginTop: "14px" } },
      field("Fecha de publicación", date, "Opcional · afina la urgencia"),
      field("Nº de candidatos", applicants, "Opcional")),
    h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "16px" } }, analyze));

  root.replaceChildren(stagger(h("div", {}, pageHead("Ofertas", "Analiza una oferta concreta: encaje, urgencia y candidatura en un clic"), form, detail, recent)));
  setMode("text");
  loadRecent(recent, detail, ctx);
}

async function loadRecent(slot, detail, ctx) {
  const jobs = await api.get("/api/jobs");
  if (!jobs.length) { slot.replaceChildren(); return; }
  const rows = h("div", { class: "card flat", style: { padding: "6px" } }, jobs.slice(0, 15).map((j) =>
    h("button", {
      class: "btn ghost", style: { width: "100%", justifyContent: "flex-start", height: "auto", padding: "10px 12px", textAlign: "left" },
      onClick: () => { showJob(detail, j, ctx); detail.scrollIntoView({ behavior: "smooth", block: "start" }); },
    }, h("span", { style: { flex: 1, minWidth: 0 } }, h("b", {}, j.title), h("span", { class: "muted" }, ` · ${j.company || "—"}`)),
    urgencyChip(j.urgency?.level))));
  slot.replaceChildren(h("h2", { class: "section-title" }, "Recientes"), rows);
}

async function showJob(slot, job, ctx) {
  const u = job.urgency || {};
  const result = h("div");
  const needCv = () => { if (!ctx.cv) { ctx.go("perfil"); throw new Error("Primero sube tu CV"); } };

  const card = h("section", { class: "card", style: { marginTop: "18px", animation: "enter 260ms var(--ease-out) both" } },
    h("div", { class: "row between", style: { alignItems: "flex-start" } },
      h("div", {}, h("h2", {}, job.title), h("p", { class: "card-sub" }, [job.company, job.location].filter(Boolean).join(" · "))),
      job.source_url ? linkButton("Ver oferta", job.source_url) : null),
    h("div", { class: "row", style: { marginTop: "12px" } }, urgencyChip(u.level),
      job.posted_date ? h("span", { class: "chip" }, icon("clock"), fmtDate(job.posted_date)) : null,
      job.details?.salary_range ? h("span", { class: "chip" }, job.details.salary_range) : null),
    u.message ? h("p", { class: "muted", style: { marginTop: "10px" } }, u.message) : null,
    h("div", { class: "row", style: { marginTop: "18px" } },
      button("Compatibilidad", { ico: "sparkles", onClick: async () => { needCv(); showMatch(result, await api.post(`/api/jobs/${job.id}/match`, null, { cv_id: ctx.cv.id })); } }),
      button("Mejorar CV y carta", { ico: "file", onClick: async () => { needCv(); showOptimization(result, await api.post(`/api/jobs/${job.id}/optimize`, null, { cv_id: ctx.cv.id })); } }),
      button("Preparar candidatura", { kind: "primary", ico: "inbox", onClick: async () => {
        needCv();
        await api.post(`/api/jobs/${job.id}/prepare`, null, { cv_id: ctx.cv.id });
        ctx.refreshCounts();
        toast("Lista en la Bandeja");
      } })),
    result);
  slot.replaceChildren(card);
}

function showMatch(slot, m) {
  const a = m.analysis;
  slot.replaceChildren(stagger(h("div", { style: { marginTop: "22px" } },
    h("hr", { class: "divider" }),
    h("div", { class: "row", style: { gap: "22px", flexWrap: "nowrap" } }, ring(m.score, { size: "lg" }),
      h("div", {}, h("h3", {}, a.verdict ? a.verdict[0].toUpperCase() + a.verdict.slice(1) + " encaje" : "Encaje"),
        h("p", { class: "muted" }, a.summary),
        h("p", { class: "faint small", style: { marginTop: "6px" } },
          `Juicio de la IA ${a.score}% · requisitos cubiertos ${Math.round(m.skills_coverage * 100)}%`))),
    h("div", { class: "grid-2", style: { marginTop: "18px" } },
      h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "Puntos fuertes"), list(a.strengths, "ok")),
      h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "Áreas de mejora"), list(a.gaps, "warn"))),
    a.improvement_tips?.length ? h("div", { style: { marginTop: "16px" } }, h("h3", { style: { marginBottom: "8px" } }, "Cómo cerrar la brecha"), list(a.improvement_tips, "ok")) : null,
    a.missing_keywords?.length ? h("div", { class: "row", style: { marginTop: "14px", gap: "6px" } },
      h("span", { class: "faint small" }, "Keywords que faltan:"), a.missing_keywords.map((k) => h("span", { class: "chip warn" }, k))) : null)));
}

function showOptimization(slot, o) {
  const letter = h("textarea", { class: "input", rows: 12 }, o.cover_letter);
  slot.replaceChildren(stagger(h("div", { style: { marginTop: "22px" } },
    h("hr", { class: "divider" }),
    h("p", { class: "faint small" }, "Titular sugerido"), h("p", { style: { fontWeight: 600, marginBottom: "14px" } }, o.suggested_headline),
    h("div", { class: "stack", style: { gap: "10px" } }, o.bullet_suggestions.map((b) => h("div", { class: "card sunken", style: { padding: "12px 14px" } },
      h("p", { class: "faint small", style: { textDecoration: "line-through" } }, b.original),
      h("p", { style: { marginTop: "4px" } }, b.improved),
      b.keywords_added?.length ? h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } }, b.keywords_added.map((k) => h("span", { class: "chip accent" }, k))) : null))),
    o.honesty_warnings?.length ? h("p", { class: "small faint", style: { marginTop: "12px" } }, `No añadido por falta de evidencia: ${o.honesty_warnings.join(", ")}`) : null,
    h("label", { class: "field", style: { marginTop: "18px" } }, h("span", {}, "Carta de presentación"), letter),
    h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "10px" } },
      button("Copiar carta", { ico: "file", onClick: async () => { await navigator.clipboard.writeText(letter.value); toast("Carta copiada"); } })))));
}

