// Piezas compartidas entre vistas.
import { api } from "../api.js";
import { button, h, icon, toast } from "../ui.js";

/** Lanza el agente y espera a que termine (sondea el historial). Devuelve la ejecución. */
export async function runAgentAndWait(onProgress) {
  const before = (await api.get("/api/agent/runs", { limit: 1 }))[0]?.id ?? 0;
  await api.post("/api/agent/run");
  onProgress?.("Buscando ofertas…");
  for (let i = 0; i < 400; i++) {  // hasta ~20 min
    await new Promise((r) => setTimeout(r, 3000));
    const last = (await api.get("/api/agent/runs", { limit: 1 }))[0];
    if (last && last.id > before && last.status !== "running") return last;
    if (last && last.id > before) onProgress?.(`Analizando… ${last.stats?.descubiertas ?? ""}`);
  }
  throw new Error("El agente está tardando más de lo normal; seguirá en segundo plano");
}

export function agentButton(label = "Buscar ahora", after) {
  return button(label, {
    kind: "primary", ico: "sparkles",
    onClick: async (_, btn) => {
      const span = btn.querySelector("span");
      const run = await runAgentAndWait((msg) => { span.textContent = msg; });
      span.textContent = label;
      if (run.status === "error") toast(run.error, "error", 6000);
      else toast(`${run.stats.preparadas || 0} candidaturas nuevas · ${run.stats.descubiertas || 0} ofertas revisadas`);
      await after?.(run);
    },
  });
}

/** Aviso si falta algo imprescindible (CV o clave de Claude). */
export async function setupBanner(ctx) {
  const keys = await api.get("/api/settings/keys").catch(() => null);
  const claude = keys?.keys.find((k) => k.name === "ANTHROPIC_API_KEY");
  const steps = [];
  if (!claude?.configured) steps.push(["key", "Añade tu clave de Claude", "ajustes"]);
  if (!ctx.cv) steps.push(["upload", "Sube tu CV", "perfil"]);
  if (!steps.length) return null;
  return h("div", { class: "card sunken", style: { marginBottom: "20px" } },
    h("div", { class: "row between" },
      h("div", {}, h("h3", {}, "Para empezar"),
        h("p", { class: "muted small" }, "Con esto el agente busca y prepara candidaturas solo.")),
      h("div", { class: "row" }, steps.map(([ico, label, route]) =>
        button(label, { kind: "primary", size: "sm", ico, onClick: () => ctx.go(route) })))));
}

export const sourceLabel = (s) => ({
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", remotive: "Remotive", adzuna: "Adzuna",
  email: "Alerta por correo", manual: "Añadida por ti",
}[s] || s);

export function linkButton(label, href, ico = "external") {
  return h("a", { class: "btn sm", href, target: "_blank", rel: "noopener" }, icon(ico), h("span", {}, label));
}
