// Shell de la aplicación: navegación, temas, atajos y estado compartido.
import { api } from "./api.js";
import { $, button, h, icon, softly, toast } from "./ui.js";
import { THEMES, setTheme } from "./theme.js";

export const ROUTES = [
  { id: "bandeja", label: "Bandeja", ico: "inbox" },
  { id: "ofertas", label: "Ofertas", ico: "search" },
  { id: "kanban", label: "Kanban", ico: "board", wide: true },
  { id: "correos", label: "Correos", ico: "mail" },
  { id: "resultados", label: "Resultados", ico: "chart" },
  { id: "agente", label: "Agente", ico: "bot" },
  { id: "perfil", label: "Perfil", ico: "user" },
];
const SETTINGS = { id: "ajustes", label: "Ajustes", ico: "settings" };
const ALL = [...ROUTES, SETTINGS];



// Estado compartido entre vistas
export const ctx = {
  api,
  cv: null,          // CV más reciente (o null)
  inboxCount: 0,
  async refreshCv() {
    const cvs = await api.get("/api/cv").catch(() => []);
    ctx.cv = cvs[0] || null;
    return ctx.cv;
  },
  async refreshCounts() {
    const pending = await api.get("/api/packages").catch(() => []);
    ctx.inboxCount = pending.length;
    const badge = $("#nav [data-route=bandeja] .count");
    if (badge) { badge.textContent = ctx.inboxCount; badge.hidden = !ctx.inboxCount; }
    return pending;
  },
  go(route) { location.hash = `#/${route}`; },
};

function themeMenu(anchor) {
  document.querySelector(".theme-menu")?.remove();
  const current = document.documentElement.dataset.theme;
  const menu = h("div", {
    class: "card theme-menu",
    style: { position: "fixed", top: "60px", right: "16px", width: "220px", padding: "6px", zIndex: 40,
      boxShadow: "var(--shadow-md)", animation: "enter 180ms var(--ease-out) both" },
  }, THEMES.map((t) => h("button", {
    class: `btn ghost ${t.id === current ? "active" : ""}`,
    style: { width: "100%", justifyContent: "flex-start", gap: "10px" },
    onClick: () => { setTheme(t.id); menu.remove(); },
  }, h("span", { style: {
    width: "18px", height: "18px", borderRadius: "6px", flex: "none", border: "1px solid var(--border)",
    background: t.bg ? `linear-gradient(135deg, ${t.bg} 50%, ${t.accent} 50%)` : "conic-gradient(#f7f7f5 0 50%, #151517 0)",
  } }), h("span", {}, t.name), t.id === current ? icon("check") : null)));
  document.body.append(menu);
  setTimeout(() => document.addEventListener("click", function close(e) {
    if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener("click", close); }
  }), 0);
}

// ── Navegación ───────────────────────────────────────────────────
function buildNav() {
  const nav = $("#nav");
  for (const r of ROUTES) {
    nav.append(h("button", { type: "button", "data-route": r.id, title: r.label, onClick: () => ctx.go(r.id) },
      icon(r.ico), h("span", { class: "label" }, r.label),
      r.id === "bandeja" ? h("span", { class: "count", hidden: true }, "0") : null));
  }
  $("#brand-mark").append(icon("briefcase"));
  const actions = $("#top-actions");
  const update = h("span", { id: "update-slot" });
  actions.append(
    update,
    button("", { kind: "ghost", ico: "palette", title: "Tema", onClick: (e) => themeMenu(e.currentTarget) }),
    h("button", { class: "btn ghost icon", "data-route": "ajustes", title: "Ajustes (⌘,)", onClick: () => ctx.go("ajustes") }, icon("settings")),
  );
  addEventListener("scroll", () => $(".topbar").classList.toggle("scrolled", scrollY > 4), { passive: true });
  addEventListener("resize", () => moveThumb(current));
}

function moveThumb(route) {
  const thumb = $("#nav-thumb");
  const btn = $(`#nav [data-route="${route}"]`);
  if (!btn) { thumb.style.width = "0px"; return; }
  thumb.style.width = `${btn.offsetWidth}px`;
  thumb.style.transform = `translateX(${btn.offsetLeft - 4}px)`;
  thumb.style.left = "4px";
}

let current = null;
let renderToken = 0;

async function route() {
  const id = (location.hash.match(/^#\/([\w-]+)/) || [])[1] || "bandeja";
  const r = ALL.find((x) => x.id === id) || ROUTES[0];
  current = r.id;
  document.querySelectorAll("[data-route]").forEach((b) => b.classList.toggle("active", b.dataset.route === r.id));
  moveThumb(r.id);
  document.title = `${r.label} · JobTracker AI`;

  const token = ++renderToken;
  const view = $("#view");
  const mod = await import(`./views/${r.id}.js?v=${window.APP_VERSION || ""}`);
  if (token !== renderToken) return;
  const fresh = h("div", { class: `page ${r.wide ? "wide" : ""}`, id: "view" });
  await softly(() => view.replaceWith(fresh));
  scrollTo({ top: 0 });
  try {
    await mod.render(fresh, ctx);
  } catch (e) {
    fresh.replaceChildren(h("div", { class: "empty" }, h("h3", {}, "Algo ha fallado"), h("p", {}, e.message)));
  }
}

// ── Atajos: ⌘1…⌘7 secciones, ⌘, ajustes ─────────────────────────
addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
  if (e.key === ",") { e.preventDefault(); ctx.go("ajustes"); return; }
  const n = Number(e.key);
  if (n >= 1 && n <= ROUTES.length) { e.preventDefault(); ctx.go(ROUTES[n - 1].id); }
});

async function checkUpdate() {
  const info = await api.get("/api/system/version").catch(() => null);
  if (!info) return;
  window.APP_VERSION = info.version;
  const slot = $("#update-slot");
  slot.replaceChildren();
  if (info.update_available) {
    slot.append(button(`Actualizar a ${info.latest}`, {
      kind: "primary", size: "sm", ico: "arrowUp",
      onClick: async () => { await api.post("/api/system/update"); toast("Actualizando… la app se reiniciará sola"); },
    }));
  }
}

// ── Arranque ─────────────────────────────────────────────────────
buildNav();
addEventListener("hashchange", route);
await Promise.all([ctx.refreshCv(), ctx.refreshCounts(), checkUpdate()]);
route();
setInterval(() => ctx.refreshCounts(), 60_000);
