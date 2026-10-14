// Actualizaciones: comprobar, instalar con pantalla de progreso y «Novedades» tras actualizar.
import { api } from "./api.js";
import { button, h, icon, toast } from "./ui.js";

const SEEN_KEY = "jt.lastSeenVersion";
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento: no pasa nada */ } },
};

/** Comprueba ahora (el actualizador descarga y verifica el manifiesto firmado). */
export async function checkNow() {
  return api.post("/api/system/check");
}

/** ¿Hace más de una hora de la última comprobación? */
export function isStale(info, minutes = 60) {
  if (!info?.installed) return false;
  if (!info.last_check) return true;
  return Date.now() - Date.parse(info.last_check) > minutes * 60_000;
}

/** Botón «Actualizar a x.y.z» en la barra superior (o nada si estás al día). */
export function showUpdateButton(info) {
  const slot = document.getElementById("update-slot");
  if (!slot) return;
  slot.replaceChildren();
  if (info?.update_available) {
    slot.append(button(`Actualizar a ${info.latest}`, {
      kind: "primary", size: "sm", ico: "arrowUp", title: info.notes || "",
      onClick: () => startUpdate(info.latest),
    }));
  }
}

/** Instala la actualización y muestra el progreso hasta que la app nueva responde. */
export async function startUpdate(latest) {
  const from = window.APP_VERSION;
  await api.post("/api/system/update");
  const msg = h("p", { class: "muted" }, "Descargando y verificando la firma…");
  const overlay = h("div", { class: "updating" }, h("div", { class: "card center stack" },
    h("div", { class: "spinner" }), h("h3", {}, `Actualizando a ${latest || "la última versión"}`), msg,
    h("p", { class: "faint small" }, "Tus datos no se tocan. Si algo falla, la app vuelve sola a la versión anterior.")));
  document.body.append(overlay);
  const started = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 2500));
    const secs = Math.round((Date.now() - started) / 1000);
    let info = null;
    try { info = await api.get("/api/system/version"); } catch { msg.textContent = `Reiniciando la app… (${secs} s)`; continue; }
    if (info.version !== from) { location.reload(); return; }
    if (info.rolled_back_from === latest) {
      overlay.remove();
      toast(`No se pudo instalar ${latest}: se mantiene ${from}. Lo veremos en Ajustes → Estado.`, "error", 8000);
      return;
    }
    msg.textContent = info.updating ? `Instalando… (${secs} s)` : `Preparando… (${secs} s)`;
    if (secs > 600) {
      overlay.remove();
      toast("La actualización está tardando más de lo normal; seguirá en segundo plano", "error", 8000);
      return;
    }
  }
}

// ── Novedades ────────────────────────────────────────────────────
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");

/** Markdown mínimo del CHANGELOG: párrafos, listas (con niveles), negritas y código. */
export function renderNotes(md) {
  const root = h("div", { class: "notes" });
  const stack = [{ indent: -1, el: root }];
  let para = null;
  for (const raw of md.split("\n")) {
    if (!raw.trim()) { para = null; continue; }
    const m = raw.match(/^(\s*)- (.*)$/);
    if (m) {
      para = null;
      const indent = m[1].length;
      while (stack.length > 1 && stack.at(-1).indent >= indent && stack.at(-1).list) stack.pop();
      let top = stack.at(-1);
      if (!top.list || top.indent < indent) {
        const ul = h("ul", { class: "bullets" });
        (top.li || top.el).append(ul);
        top = { indent, el: ul, list: true };
        stack.push(top);
      }
      const li = h("li", { html: inline(m[2]) });
      top.el.append(li);
      top.li = li;
      continue;
    }
    const cont = raw.match(/^\s{2,}(\S.*)$/);
    if (cont && stack.at(-1).li) { stack.at(-1).li.insertAdjacentHTML("beforeend", " " + inline(cont[1])); continue; }
    while (stack.length > 1) stack.pop();
    if (para) para.insertAdjacentHTML("beforeend", " " + inline(raw.trim()));
    else { para = h("p", { html: inline(raw.trim()) }); root.append(para); }
  }
  return root;
}

export async function openWhatsNew(since) {
  const data = await api.get("/api/system/changelog", since ? { since } : { limit: 1 });
  if (!data.sections.length) return;
  const dlg = h("dialog", { class: "sheet", "aria-label": "Novedades" });
  const close = () => { dlg.classList.add("out"); setTimeout(() => { dlg.close(); dlg.remove(); }, 260); };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  dlg.append(h("div", { class: "sheet-body" },
    h("header", { class: "sheet-head" }, h("div", { style: { flex: 1 } },
      h("p", { class: "faint small" }, icon("sparkles"), " Novedades"),
      h("h2", {}, `JobTracker AI ${data.version}`)),
    button("", { ico: "x", size: "sm", title: "Cerrar (Esc)", onClick: close })),
    data.sections.map((s) => h("section", { class: "sheet-section" },
      data.sections.length > 1 || s.title ? h("h3", { class: "section-title" }, s.title ? `${s.version} · ${s.title}` : s.version) : null,
      renderNotes(s.body))),
    h("div", { class: "row", style: { marginTop: "18px" } }, button("Entendido", { kind: "primary", onClick: close }))));
  document.body.append(dlg);
  dlg.showModal();
}

/** Tras actualizar, enseña una vez las novedades de lo que ha cambiado desde la última versión vista. */
export async function maybeShowWhatsNew(version) {
  const seen = store.get(SEEN_KEY);
  store.set(SEEN_KEY, version);
  if (seen && seen !== version) await openWhatsNew(seen).catch(() => {});
}
