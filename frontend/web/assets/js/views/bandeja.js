// 📥 Bandeja: candidaturas preparadas por el agente, listas para aprobar.
import { api } from "../api.js";
import { animateOut, button, empty, fmtDate, h, icon, list, pageHead, ring, skeletons, stagger, toast, urgencyChip } from "../ui.js";
import { autofillButton } from "../autofill.js";
import { openApplication } from "../detail.js";
import { agentButton, linkButton, setupBanner, sourceLabel } from "./_shared.js";

const QUICK_REASONS = ["Sueldo bajo", "No me interesa la empresa", "Demasiado junior", "Demasiado senior",
  "Ubicación o modalidad", "Stack que no quiero"];

export async function render(root, ctx) {
  const subtitle = h("p");
  const head = pageHead("Bandeja", null, agentButton("Buscar ahora", () => render(root, ctx)));
  head.querySelector("h1").after(subtitle);
  const list_ = h("div", { class: "stack" });
  const approvedSlot = h("div");
  root.replaceChildren(head, skeletons(2));

  const [pending, approved, banner, digest] = await Promise.all([
    ctx.refreshCounts(), api.get("/api/packages", { status: "aprobada" }), setupBanner(ctx),
    api.get("/api/agent/digest").catch(() => null),
  ]);

  const setSubtitle = () => {
    const n = list_.children.length;
    subtitle.textContent = n ? `${n} candidatura${n > 1 ? "s" : ""} lista${n > 1 ? "s" : ""} para revisar` : "Todo revisado";
    subtitle.className = "";
    if (!n) list_.replaceWith(emptyState(ctx));
  };

  for (const pkg of pending) list_.append(packageCard(pkg, ctx, setSubtitle));
  root.replaceChildren(head, banner || "", todayCard(digest, ctx, () => render(root, ctx)) || "", pending.length ? stagger(list_) : emptyState(ctx), approvedSlot);
  setSubtitle();
  renderApproved(approvedSlot, approved);
}

/** Tarjeta «Hoy»: entrevistas próximas y candidaturas que necesitan seguimiento. */
function todayCard(d, ctx, reload) {
  if (!d || (!d.interviews.length && !d.stale.length && !d.approved_unsent)) return null;
  const when = (iso) => new Date(iso).toLocaleString("es-ES", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const item = (ico, kind, main, sub, action) => h("button", {
    type: "button", class: "btn ghost", style: { width: "100%", justifyContent: "flex-start", height: "auto", padding: "8px 10px", textAlign: "left", whiteSpace: "normal" },
    onClick: typeof action === "function" ? action : () => ctx.go(action),
  }, h("span", { class: `chip ${kind}`, style: { width: "30px", justifyContent: "center", padding: 0 } }, icon(ico)),
  h("span", { style: { flex: 1, minWidth: 0 } }, h("b", {}, main), h("span", { class: "muted" }, ` · ${sub}`)));
  return h("section", { class: "card", style: { marginBottom: "18px", padding: "14px 16px" } },
    h("p", { class: "faint small", style: { textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600, margin: "0 0 6px 10px" } }, "Hoy"),
    d.interviews.map((i) => item("calendar", "warn", `Entrevista · ${i.company || i.title}`, `${when(i.at)} · prepárala`,
      () => openApplication(i.application_id, { focus: "prep", onChange: reload }))),
    d.approved_unsent ? item("send", "accent", `${d.approved_unsent} aprobada${d.approved_unsent > 1 ? "s" : ""} sin enviar`, "abajo en esta página", "bandeja") : null,
    d.stale.slice(0, 3).map((s) => item("clock", "", `Sin respuesta · ${s.company || s.title}`, `hace ${s.days} días: buen momento para un seguimiento`,
      () => openApplication(s.application_id, { focus: "seguimiento", onChange: reload }))));
}

function emptyState(ctx) {
  return empty("inbox", "Nada pendiente",
    "El agente busca ofertas cada 3 horas y deja aquí las que mejor encajan contigo, con el CV y la carta preparados.",
    button("Ajustar la búsqueda", { ico: "bot", onClick: () => ctx.go("agente") }));
}

function packageCard(pkg, ctx, onGone) {
  const { job } = pkg;
  const match = pkg.match || {};
  const card = h("article", { class: "card hover" });
  const letter = h("textarea", { class: "input", rows: 10 }, pkg.cover_letter || "");

  const decide = async (decision, reason) => {
    await api.post(`/api/packages/${pkg.id}/decision`, { decision, reason: reason || null, cover_letter: letter.value });
    toast({ aprobada: "Aprobada · pasa al Kanban", enviada: "Marcada como enviada", descartada: "Descartada · el agente lo tendrá en cuenta" }[decision]);
    await animateOut(card);
    ctx.refreshCounts();
    onGone();
  };

  // Cabecera
  const header = h("div", { class: "row", style: { alignItems: "flex-start", gap: "16px", flexWrap: "nowrap" } },
    match.score != null ? ring(match.score) : null,
    h("div", { style: { flex: 1, minWidth: 0 } },
      h("h2", {}, job.title),
      h("p", { class: "card-sub" }, [job.company, job.location].filter(Boolean).join(" · ")),
      h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } },
        urgencyChip(job.urgency?.level), h("span", { class: "chip" }, sourceLabel(job.source)),
        job.posted_date ? h("span", { class: "chip" }, icon("clock"), fmtDate(job.posted_date)) : null)));

  const summary = match.summary ? h("p", { class: "muted", style: { marginTop: "14px" } }, match.summary) : null;
  const fit = (match.strengths?.length || match.gaps?.length) ? h("div", { class: "grid-2", style: { marginTop: "16px" } },
    h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "Puntos fuertes"), list((match.strengths || []).slice(0, 3), "ok")),
    h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "A tener en cuenta"), list((match.gaps || []).slice(0, 3), "warn"))) : null;

  // Detalle de la candidatura
  const answered = (pkg.answers || []).filter((a) => a.answer);
  const details = h("details", { class: "disclosure", style: { marginTop: "18px" } },
    h("summary", {}, icon("chevron", "chev"), "Ver candidatura preparada"),
    h("div", { class: "body stack" },
      pkg.headline ? h("div", {}, h("p", { class: "faint small" }, "Titular adaptado"), h("p", { style: { fontWeight: 600 } }, pkg.headline)) : null,
      pkg.bullets?.length ? h("div", { class: "stack", style: { gap: "10px" } },
        h("p", { class: "faint small" }, "Viñetas mejoradas en tu CV"),
        pkg.bullets.map((b) => h("div", { class: "card sunken", style: { padding: "12px 14px" } },
          h("p", { class: "faint small", style: { textDecoration: "line-through" } }, b.original),
          h("p", { style: { marginTop: "4px" } }, b.improved)))) : null,
      h("label", { class: "field" }, h("span", {}, "Carta de presentación"), letter),
      answered.length ? h("div", { class: "stack", style: { gap: "10px" } },
        h("p", { class: "faint small" }, "Respuestas a preguntas de filtro"),
        answered.map((a) => h("div", {}, h("p", { style: { fontWeight: 550 } }, a.question), h("p", { class: "muted" }, a.answer)))) : null,
      pkg.pending_answers?.length ? h("p", { class: "small faint" }, icon("alert"),
        ` Sin respuesta base (complétalas en Perfil): ${pkg.pending_answers.slice(0, 4).join(" · ")}`) : null,
      pkg.honesty_warnings?.length ? h("div", { class: "chip warn", style: { height: "auto", padding: "6px 10px", whiteSpace: "normal" } },
        `No se ha añadido porque tu CV no lo respalda: ${pkg.honesty_warnings.join(", ")}`) : null));

  // Descartar con motivo (aprendizaje)
  const reasonInput = h("input", { class: "input", placeholder: "Motivo (opcional): el agente aprende de esto" });
  const discardPanel = h("div", { class: "stack", hidden: true, style: { marginTop: "14px", gap: "10px", animation: "enter 220ms var(--ease-out) both" } },
    h("div", { class: "row", style: { gap: "6px" } }, QUICK_REASONS.map((r) =>
      h("button", { class: "chip", type: "button", style: { cursor: "pointer" }, onClick: () => { reasonInput.value = r; } }, r))),
    h("div", { class: "row" }, reasonInput,
      button("Descartar", { kind: "danger", onClick: () => decide("descartada", reasonInput.value.trim()) }),
      button("Cancelar", { kind: "ghost", onClick: () => { discardPanel.hidden = true; } })));
  reasonInput.style.flex = "1";

  const fillBtn = job.apply_url ? autofillButton(pkg, { getLetter: () => letter.value, onSent: async () => {
    await animateOut(card);
    ctx.refreshCounts();
    onGone();
  } }) : null;
  const actions = h("div", { class: "row", style: { marginTop: "18px" } },
    h("a", { class: "btn sm", href: `/api/packages/${pkg.id}/cv.pdf`, download: "" }, icon("download"), h("span", {}, "CV adaptado")),
    job.apply_url ? linkButton("Abrir oferta", job.apply_url) : null,
    fillBtn,
    h("span", { class: "spacer" }),
    button("", { kind: "ghost", size: "sm", ico: "trash", title: "Descartar…", onClick: () => { discardPanel.hidden = !discardPanel.hidden; if (!discardPanel.hidden) reasonInput.focus(); } }),
    button("Ya la envié", { size: "sm", ico: "send", onClick: () => decide("enviada") }),
    button("Aprobar", { kind: "primary", size: "sm", ico: "check", onClick: () => decide("aprobada") }));

  card.append(header, summary || "", fit || "", details, actions, fillBtn?.panel || "", discardPanel);
  return card;
}

function renderApproved(slot, approved) {
  if (!approved.length) return;
  const rows = h("div", { class: "card flat", style: { padding: "6px 8px" } });
  for (const pkg of approved) {
    const fill = pkg.job.apply_url ? autofillButton(pkg, { kind: "primary", onSent: () => animateOut(wrap) }) : null;
    const row = h("div", { class: "row", style: { padding: "10px 8px" } },
      h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, pkg.job.title), h("span", { class: "muted" }, ` · ${pkg.job.company || ""}`)),
      pkg.job.apply_url ? linkButton("Abrir", pkg.job.apply_url) : null,
      fill,
      button("Enviada", { size: "sm", ico: "send", onClick: async () => {
        await api.post(`/api/packages/${pkg.id}/decision`, { decision: "enviada" });
        toast("Marcada como enviada");
        await animateOut(wrap);
      } }));
    const wrap = h("div", { style: { borderBottom: "1px solid var(--border)" } }, row,
      fill ? h("div", { style: { padding: "0 8px" } }, fill.panel) : null);
    rows.append(wrap);
  }
  rows.lastElementChild.style.borderBottom = "0";
  slot.replaceChildren(h("h2", { class: "section-title" }, "Aprobadas · pendientes de enviar"), rows);
}
