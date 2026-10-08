// 📋 Kanban: arrastra las candidaturas entre columnas.
import { api } from "../api.js";
import { openApplication } from "../detail.js";
import { empty, fmtDate, h, icon, pageHead, stagger, toast, urgencyChip } from "../ui.js";

const COLUMNS = [
  { id: "por_aplicar", label: "Por aplicar", dot: "" },
  { id: "aplicado", label: "Aplicado", dot: "ok" },
  { id: "entrevista", label: "Entrevista", dot: "warn" },
  { id: "oferta", label: "Oferta", dot: "ok" },
  { id: "rechazado", label: "Rechazado", dot: "bad" },
];

export async function render(root, ctx) {
  const board = await api.get("/api/applications/board");
  const total = Object.values(board).reduce((n, c) => n + c.length, 0);
  const head = pageHead("Kanban", total ? `${total} candidatura${total > 1 ? "s" : ""} en seguimiento` : null,
    total ? h("a", { class: "btn sm", href: "/api/applications/export.csv", download: "", title: "Para Excel o Numbers: útil como registro de búsqueda activa" },
      icon("download"), h("span", {}, "Exportar CSV")) : null);
  if (!total) {
    root.replaceChildren(head, empty("board", "Sin candidaturas todavía",
      "Cuando apruebes una candidatura en la Bandeja o prepares una oferta, aparecerá aquí."));
    return;
  }
  const grid = h("div", { class: "board" });
  const reload = () => render(root, ctx);
  for (const col of COLUMNS) grid.append(column(col, board[col.id] || [], grid, reload));
  root.replaceChildren(head, stagger(grid));
}

function column(col, items, grid, reload) {
  const count = h("span", { class: "chip" }, String(items.length));
  const body = h("div", {}, items.map((a) => ticket(a, reload)));
  const el = h("section", { class: "column", "data-status": col.id },
    h("div", { class: "column-head" }, h("span", { class: `dot ${col.dot}` }), col.label, count), body);

  el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("over"); });
  el.addEventListener("dragleave", (e) => { if (!el.contains(e.relatedTarget)) el.classList.remove("over"); });
  el.addEventListener("drop", async (e) => {
    e.preventDefault();
    el.classList.remove("over");
    const id = e.dataTransfer.getData("text/plain");
    const card = grid.querySelector(`[data-app="${id}"]`);
    if (!card || card.parentElement === body) return;
    const from = card.parentElement;
    body.prepend(card);  // optimista
    card.animate([{ transform: "scale(0.96)", opacity: 0.6 }, { transform: "none", opacity: 1 }], { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
    recount(grid);
    try {
      await api.patch(`/api/applications/${id}`, { status: col.id });
      toast(`Movida a «${col.label}»`);
    } catch (err) {
      from.prepend(card);
      recount(grid);
      toast(err.message, "error");
    }
  });
  el.count = count;
  return el;
}

function recount(grid) {
  grid.querySelectorAll(".column").forEach((c) => { c.querySelector(".column-head .chip").textContent = c.querySelectorAll(".ticket").length; });
}

function ticket(a, reload) {
  const t = h("div", { class: "ticket", draggable: "true", "data-app": a.id, tabindex: "0", role: "button",
    title: "Abrir la ficha · arrastra para cambiar de columna" },
    h("h4", {}, a.job_title),
    h("p", { class: "muted small" }, a.company || "—"),
    h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } },
      a.match_score != null ? h("span", { class: "chip accent" }, `${Math.round(a.match_score)}%`) : null,
      urgencyChip(a.urgency_level),
      a.interview_at ? h("span", { class: "chip warn" }, icon("calendar"), fmtDate(a.interview_at, true)) : null,
      a.notes ? h("span", { class: "chip", title: "Tiene notas" }, icon("file")) : null));
  const open = () => openApplication(a.id, { onChange: reload });
  t.addEventListener("click", open);
  t.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  t.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", a.id); e.dataTransfer.effectAllowed = "move"; t.classList.add("dragging"); });
  t.addEventListener("dragend", () => t.classList.remove("dragging"));
  return t;
}
