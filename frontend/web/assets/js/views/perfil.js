// 👤 Perfil: tu CV y el banco de respuestas.
import { api } from "../api.js";
import { h, icon, pageHead, stagger, toast } from "../ui.js";

export async function render(root, ctx) {
  const cv = ctx.cv ? await api.get(`/api/cv/${ctx.cv.id}`) : null;
  const answers = await api.get("/api/answers");
  root.replaceChildren(stagger(h("div", {},
    pageHead("Perfil", cv ? "Lo que la IA sabe de ti" : "Sube tu CV para empezar"),
    dropzone(root, ctx, !!cv),
    cv ? profileCard(cv.profile) : null,
    answersSection(answers))));
}

function dropzone(root, ctx, hasCv) {
  const input = h("input", { type: "file", accept: ".pdf,.txt,.md", hidden: true });
  const label = h("p", {}, hasCv ? "Arrastra un CV nuevo para sustituirlo" : "Arrastra tu CV aquí o haz clic para elegirlo");
  const zone = h("div", { class: "dropzone", role: "button", tabindex: "0" }, icon("upload"), label,
    h("p", { class: "faint small" }, "PDF, TXT o MD · se procesa con IA y se guarda solo en tu Mac"), input);
  const upload = async (file) => {
    if (!file) return;
    label.textContent = `Analizando ${file.name}…`;
    zone.classList.add("pulse");
    try {
      await api.upload("/api/cv", file);
      await ctx.refreshCv();
      toast("CV analizado · el agente empieza a buscar");
      await render(root, ctx);
    } catch (e) {
      toast(e.message, "error", 6000);
      label.textContent = "Arrastra tu CV aquí o haz clic para elegirlo";
    } finally { zone.classList.remove("pulse"); }
  };
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => upload(input.files[0]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); upload(e.dataTransfer.files[0]); });
  return zone;
}

function chips(items, kind = "") {
  return h("div", { class: "row", style: { gap: "6px" } }, (items || []).map((s) => h("span", { class: `chip ${kind}` }, s)));
}

function profileCard(p) {
  return h("section", { class: "card", style: { marginTop: "18px" } },
    h("div", { class: "center" },
      h("h2", { style: { fontSize: "22px" } }, p.full_name || "Tu perfil"),
      h("p", { class: "card-sub" }, [p.headline, p.location].filter(Boolean).join(" · ")),
      h("div", { class: "row", style: { justifyContent: "center", marginTop: "10px", gap: "6px" } },
        p.seniority && p.seniority !== "unknown" ? h("span", { class: "chip accent" }, p.seniority) : null,
        p.years_experience ? h("span", { class: "chip" }, `${p.years_experience} años de experiencia`) : null)),
    p.summary ? h("p", { class: "muted center", style: { margin: "16px auto 0", maxWidth: "600px" } }, p.summary) : null,
    h("hr", { class: "divider" }),
    h("div", { class: "stack" },
      h("div", {}, h("p", { class: "faint small", style: { marginBottom: "6px" } }, "Habilidades"), chips(p.hard_skills, "accent")),
      h("div", {}, h("p", { class: "faint small", style: { marginBottom: "6px" } }, "Tecnologías"), chips(p.technologies)),
      h("div", { class: "grid-2" },
        h("div", {}, h("p", { class: "faint small", style: { marginBottom: "6px" } }, "Idiomas"), chips(p.languages)),
        h("div", {}, h("p", { class: "faint small", style: { marginBottom: "6px" } }, "Formación"), chips(p.education)))),
    p.experience?.length ? h("details", { class: "disclosure", style: { marginTop: "16px" } },
      h("summary", {}, icon("chevron", "chev"), `Experiencia (${p.experience.length})`),
      h("div", { class: "body stack" }, p.experience.map((e) => h("div", {},
        h("p", {}, h("b", {}, e.role), h("span", { class: "muted" }, ` · ${e.company}`),
          h("span", { class: "faint small" }, `  ${[e.start, e.end].filter(Boolean).join(" – ")}`)),
        h("ul", { style: { margin: "6px 0 0", paddingLeft: "18px", color: "var(--text-2)" } }, e.highlights.map((x) => h("li", {}, x))))))) : null);
}

function answersSection(answers) {
  const filled = answers.filter((a) => a.answer.trim()).length;
  return h("div", {},
    h("h2", { class: "section-title" }, `Banco de respuestas · ${filled}/${answers.length}`),
    h("p", { class: "center muted small", style: { marginTop: "-4px", marginBottom: "14px" } },
      "Respóndelas una vez: la IA las adapta a cada oferta y nunca inventa las que dejes vacías. Se guardan solas."),
    h("section", { class: "card stack" }, answers.map((a) => answerField(a))));
}

function answerField(a) {
  const state = h("span", { class: "faint small", style: { transition: "opacity 300ms", opacity: 0 } }, "Guardado");
  const ta = h("textarea", { class: "input", rows: 2, placeholder: "Tu respuesta…" }, a.answer);
  let saved = a.answer;
  ta.addEventListener("blur", async () => {
    if (ta.value === saved) return;
    try {
      await api.put("/api/answers", { key: a.key, question: a.question, answer: ta.value });
      saved = ta.value;
      state.style.opacity = 1;
      setTimeout(() => { state.style.opacity = 0; }, 1600);
    } catch (e) { toast(e.message, "error"); }
  });
  return h("label", { class: "field" }, h("span", { class: "row between" }, a.question, state), ta);
}
