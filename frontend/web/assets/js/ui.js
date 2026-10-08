// Utilidades de interfaz: DOM, iconos, avisos, anillos de puntuación, etiquetas y animaciones.

// ── DOM ──────────────────────────────────────────────────────────
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") {
      for (const [prop, val] of Object.entries(v)) {
        if (prop.startsWith("--")) el.style.setProperty(prop, val);  // variables CSS
        else el.style[prop] = val;
      }
    }
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const $ = (sel, root = document) => root.querySelector(sel);

/** Escalona la animación de entrada de los hijos directos. */
export function stagger(container) {
  container.classList.add("enter");
  [...container.children].forEach((c, i) => c.style.setProperty("--i", Math.min(i, 12)));
  return container;
}

/** Saca un elemento con fundido + colapso de altura y lo elimina. */
export async function animateOut(el) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "reduce") {
    el.remove();
    return;
  }
  const height = el.offsetHeight;
  const anim = el.animate(
    [
      { opacity: 1, transform: "none", height: `${height}px`, marginBottom: getComputedStyle(el).marginBottom },
      { opacity: 0, transform: "translateX(24px) scale(0.98)", height: `${height}px`, offset: 0.55 },
      { opacity: 0, height: "0px", marginBottom: "0px", paddingTop: "0px", paddingBottom: "0px" },
    ],
    { duration: 420, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" },
  );
  await anim.finished.catch(() => {});
  el.remove();
}

/** Cambio suave (View Transitions si el motor lo soporta). */
export function softly(fn) {
  if (document.startViewTransition && document.documentElement.dataset.motion !== "reduce") {
    return document.startViewTransition(fn).finished;
  }
  fn();
  return Promise.resolve();
}

// ── Iconos (trazo 1.7, estilo uniforme) ──────────────────────────
const P = {
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  board: '<rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="10" rx="1.5"/><rect x="17" y="4" width="4" height="13" rx="1.5"/>',
  mail: '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="m3 7 9 6 9-6"/>',
  bot: '<path d="M12 3v3"/><rect x="4" y="7" width="16" height="12" rx="4"/><circle cx="9" cy="13" r="1.2" fill="currentColor"/><circle cx="15" cy="13" r="1.2" fill="currentColor"/><path d="M2 12v2M22 12v2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2.5"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7"/><path d="M3 12.5h18"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/>',
  download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
  upload: '<path d="M12 20V9"/><path d="m7 14 5-5 5 5"/><path d="M5 4h14"/>',
  trash: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 9.2-9.2"/><path d="m17 6 3 3"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4A4.6 4.6 0 0 0 22 9.8C22 5.9 17.5 3 12 3z"/><circle cx="7.5" cy="11" r="1.2" fill="currentColor"/><circle cx="10.5" cy="7" r="1.2" fill="currentColor"/><circle cx="15" cy="7.5" r="1.2" fill="currentColor"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  sparkles: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  shield: '<path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  arrowUp: '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M3 10h18M8 3v4M16 3v4"/>',
};

export function icon(name, cls = "") {
  const span = document.createElement("span");
  span.style.display = "contents";
  span.innerHTML = `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ""}</svg>`;
  return span.firstElementChild;
}

// ── Botones ──────────────────────────────────────────────────────
export function button(label, { kind = "", ico, onClick, title, size = "" } = {}) {
  const b = h("button", { class: `btn ${kind} ${size}`.trim(), type: "button", title: title || null },
    ico ? icon(ico) : null, label ? h("span", {}, label) : null);
  if (!label) b.classList.add("icon");
  if (onClick) b.addEventListener("click", async (e) => {
    if (b.classList.contains("busy")) return;
    b.classList.add("busy");
    try { await onClick(e, b); } catch (err) { toast(err.message || String(err), "error"); }
    finally { b.classList.remove("busy"); }
  });
  return b;
}

// ── Avisos ───────────────────────────────────────────────────────
export function toast(message, kind = "ok", ms = 3200) {
  const el = h("div", { class: `toast ${kind === "error" ? "error" : ""}`, role: "status" },
    icon(kind === "error" ? "alert" : "check"), h("span", {}, message));
  document.getElementById("toasts").append(el);
  setTimeout(() => { el.classList.add("out"); el.addEventListener("animationend", () => el.remove(), { once: true }); }, ms);
}

// ── Puntuación ───────────────────────────────────────────────────
export function ring(value, { size = "" } = {}) {
  const r = 24, c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const el = h("div", { class: `ring ${size}`, title: `${Math.round(v)}% de encaje` });
  el.innerHTML = `<svg viewBox="0 0 58 58"><circle class="track" cx="29" cy="29" r="${r}"/><circle class="value" cx="29" cy="29" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c}"/></svg><span>${Math.round(v)}</span>`;
  const arc = el.querySelector(".value");
  arc.style.stroke = v >= 75 ? "var(--accent)" : v >= 55 ? "var(--warn)" : "var(--bad)";
  requestAnimationFrame(() => requestAnimationFrame(() => { arc.style.strokeDashoffset = c * (1 - v / 100); }));
  return el;
}

const URGENCY = {
  ideal: ["ok", "Recién publicada"], buena: ["ok", "A tiempo"], competida: ["warn", "Competida"],
  "tardía": ["warn", "Tardía"], probablemente_cerrada: ["bad", "Probablemente cerrada"], desconocida: ["", "Fecha desconocida"],
};
export function urgencyChip(level) {
  if (!level) return null;
  const [kind, label] = URGENCY[level] || ["", level];
  return h("span", { class: `chip ${kind}` }, h("span", { class: `dot ${kind}` }), label);
}

// ── Estados ──────────────────────────────────────────────────────
export function empty(glyph, title, text, ...actions) {
  return h("div", { class: "empty" },
    h("div", { class: "glyph" }, icon(glyph)), h("h3", {}, title), h("p", {}, text),
    actions.length ? h("div", { class: "actions" }, actions) : null);
}

export function skeletons(n = 3) {
  return h("div", { class: "stack" }, Array.from({ length: n }, () => h("div", { class: "skeleton skeleton-card" })));
}

export function pageHead(title, subtitle, ...actions) {
  return h("header", { class: "page-head" }, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null,
    actions.length ? h("div", { class: "actions" }, actions) : null);
}

export function list(items, kind = "ok") {
  return h("ul", { class: `clean ${kind}` },
    items.map((t) => h("li", {}, icon(kind === "ok" ? "check" : "alert"), h("span", {}, t))));
}

// ── Formularios ──────────────────────────────────────────────────
export function field(label, control, hint) {
  return h("label", { class: "field" }, h("span", {}, label), control, hint ? h("small", { class: "hint" }, hint) : null);
}

export function toggle(checked, onChange) {
  const input = h("input", { type: "checkbox" });
  input.checked = !!checked;
  if (onChange) input.addEventListener("change", () => onChange(input.checked));
  const el = h("label", { class: "switch" }, input, h("i"));
  el.input = input;
  return el;
}

/** Campo de etiquetas: Enter o coma añaden; Retroceso borra la última. el.value → string[] */
export function tagInput(values = [], placeholder = "Escribe y pulsa Enter") {
  let tags = [...values];
  const input = h("input", { placeholder });
  const box = h("div", { class: "tags" });
  const render = () => {
    box.replaceChildren(...tags.map((t, i) => h("span", { class: "chip accent" }, t,
      h("button", { type: "button", "aria-label": `Quitar ${t}`, onClick: () => { tags.splice(i, 1); render(); input.focus(); } }, icon("x")))), input);
  };
  const commit = () => {
    const parts = input.value.split(",").map((s) => s.trim()).filter(Boolean);
    for (const p of parts) if (!tags.includes(p)) tags.push(p);
    input.value = "";
    render();
    input.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !input.value && tags.length) { tags.pop(); render(); input.focus(); }
  });
  input.addEventListener("blur", () => input.value.trim() && commit());
  box.addEventListener("click", () => input.focus());
  render();
  Object.defineProperty(box, "value", { get: () => { if (input.value.trim()) commit(); return [...tags]; } });
  box.add = (v) => {
    if (tags.includes(v)) return false;
    tags.push(v);
    render();
    box.lastElementChild.previousElementSibling?.animate(
      [{ transform: "scale(0.6)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" });
    return true;
  };
  return box;
}

export function fmtDate(iso, withTime = false) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(+d)) return iso;
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}) });
}
