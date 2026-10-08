// Temas: lista, cambio con transición suave y persistencia en el backend.
import { api } from "./api.js";
import { softly, toast } from "./ui.js";

export const THEMES = [
  { id: "auto", name: "Automático", note: "Sigue a macOS" },
  { id: "porcelana", name: "Porcelana", bg: "#f7f7f5", surface: "#ffffff", accent: "#4f46e5", text: "#1c1c1e" },
  { id: "grafito", name: "Grafito", bg: "#151517", surface: "#1d1d20", accent: "#8ab4ff", text: "#ececef" },
  { id: "oceano", name: "Océano", bg: "#f2f7fa", surface: "#ffffff", accent: "#0e7490", text: "#0f2533" },
  { id: "bosque", name: "Bosque", bg: "#111a16", surface: "#16231d", accent: "#5fd39a", text: "#e3efe8" },
  { id: "atardecer", name: "Atardecer", bg: "#fbf6f1", surface: "#fffdfa", accent: "#c4512e", text: "#2b1d14" },
  { id: "lavanda", name: "Lavanda", bg: "#f6f4fb", surface: "#ffffff", accent: "#7c3aed", text: "#1f1933" },
  { id: "medianoche", name: "Medianoche", bg: "#0d1220", surface: "#131a2c", accent: "#f5b544", text: "#e6eaf5" },
  { id: "arena", name: "Arena", bg: "#f5f1e8", surface: "#fbf9f4", accent: "#5f7a1f", text: "#2a261d" },
];

export async function setTheme(theme) {
  const root = document.documentElement;
  if (root.dataset.theme === theme) return;
  await softly(() => { root.dataset.theme = theme; });
  document.dispatchEvent(new CustomEvent("themechange", { detail: theme }));
  api.put("/api/settings/ui", { theme, reduce_motion: root.dataset.motion === "reduce" })
    .catch((e) => toast(e.message, "error"));
}

export function setMotion(reduce) {
  document.documentElement.dataset.motion = reduce ? "reduce" : "full";
  api.put("/api/settings/ui", { theme: document.documentElement.dataset.theme, reduce_motion: reduce })
    .catch((e) => toast(e.message, "error"));
}

