// Rellena un formulario de candidatura (Greenhouse, Lever, Ashby o genérico) dentro de la página.
// Se ejecuta con page.evaluate(script, profile). NUNCA envía el formulario.
// Conservador: solo campos vacíos y visibles; no toca preguntas demográficas (género, etnia, discapacidad…)
// ni casillas sí/no de permisos o visados (el sentido de la pregunta cambia de un formulario a otro).
(profile) => {
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
  const SENSITIVE = /gender|genero|sexo|race|raza|ethnic|etnia|hispanic|latino|veteran|disabilit|discapacidad|pronoun|pronombre|sexual|religion|date of birth|fecha de nacimiento|edad\b|\bage\b|social security|dni|nie|passport|pasaporte/;
  const RULES = [
    ["last_name", /last.?name|surname|family.?name|apellido/],
    ["first_name", /first.?name|given.?name|preferred.?(first.?)?name|nombre de pila/],
    ["full_name", /full.?name|nombre (y apellidos|completo)|^name\b|^nombre\b|your name|tu nombre/],
    ["email", /e-?mail|correo/],
    ["phone", /phone|telefono|movil|mobile|celular/],
    ["linkedin", /linkedin/],
    ["github", /github/],
    ["website", /website|portfolio|portafolio|web personal|personal site|blog/],
    ["location", /^location|current location|city|ciudad|ubicacion|localidad|where (are you|do you) (based|live)|donde vives|residencia/],
    ["current_company", /current (company|employer)|empresa actual|^org(anization)?\b/],
    ["cover_letter", /cover.?letter|carta de presentacion|motivation|motivacion|additional information|informacion adicional|anything else/],
    ["a:expectativa_salarial", /salar|compensation|pay expectation|remuneracion|retribucion|desired pay/],
    ["a:disponibilidad", /notice period|start date|availability|when can you start|disponibilidad|incorporarte|incorporacion|preaviso|earliest start/],
    ["a:permiso_trabajo", /authori[sz]ed|work permit|permiso de trabajo|visa|sponsorship|right to work|patrocinio/],
    ["a:reubicacion", /relocat|reubica|traslad/],
    ["a:modalidad", /remote|hibrid|hybrid|on.?site|modalidad|presencial/],
    ["a:nivel_ingles", /english|ingles/],
    ["a:por_que_empresa", /why (do you want to )?(work|join)|why (us|this company)|por que .*(empresa|nosotros|unirte|trabajar)/],
    ["a:por_que_puesto", /why .*(role|position|interested)|por que .*(puesto|rol|interesa)/],
    ["a:logro_destacado", /achievement|proud|accomplishment|logro/],
  ];

  const visible = (el) => {
    if (el.disabled || el.readOnly) return false;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };
  const text = (el) => (el ? el.innerText || el.textContent || "" : "").trim();
  const labelOf = (el) => {
    const parts = [];
    if (el.getAttribute("aria-label")) parts.push(el.getAttribute("aria-label"));
    const by = el.getAttribute("aria-labelledby");
    if (by) by.split(/\s+/).forEach((id) => parts.push(text(document.getElementById(id))));
    if (el.id) document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach((l) => parts.push(text(l)));
    const wrap = el.closest("label");
    if (wrap) parts.push(text(wrap));
    if (!parts.join("").trim()) {  // Greenhouse/Ashby: etiqueta en un contenedor cercano
      let node = el.parentElement;
      for (let i = 0; i < 4 && node && !parts.join("").trim(); i++, node = node.parentElement) {
        const l = node.querySelector("label, legend, [class*=label], [class*=question]");
        if (l && !l.contains(el)) parts.push(text(l));
      }
    }
    return parts.join(" ").replace(/\s+/g, " ").trim().slice(0, 200);
  };
  const hint = (el) => norm([el.name, el.id, el.placeholder, el.getAttribute("autocomplete")].filter(Boolean).join(" "));
  const required = (el, label) => el.required || el.getAttribute("aria-required") === "true" || /\*\s*$|\*/.test(label);

  const setValue = (el, v) => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);  // también con formularios React
    for (const ev of ["input", "change", "blur"]) el.dispatchEvent(new Event(ev, { bubbles: true }));
  };
  const mark = (el, ok) => { el.style.outline = `2px solid ${ok ? "#16a34a" : "#f59e0b"}`; el.style.outlineOffset = "2px"; };

  const tokens = (s) => new Set(norm(s).split(/[^a-z0-9]+/).filter((t) => t.length > 3));
  const similar = (a, b) => {
    const A = tokens(a), B = tokens(b);
    if (!A.size || !B.size) return 0;
    let n = 0;
    A.forEach((t) => { if (B.has(t)) n++; });
    return n / Math.min(A.size, B.size);
  };

  const fields = [...document.querySelectorAll("input, textarea, select")].filter((el) => {
    const t = (el.type || "").toLowerCase();
    return !["hidden", "submit", "button", "reset", "image", "checkbox", "radio", "password", "search"].includes(t);
  });
  const hasLast = fields.some((el) => el.type !== "file" && /last.?name|surname|apellido/.test(norm(labelOf(el)) + " " + hint(el)));

  const report = { filled: [], missing: [], skipped: [], files: [] };
  const used = new Set();
  let fileIndex = 0;

  for (const el of fields) {
    const label = labelOf(el);
    const key = norm(label);
    const all = `${key} ${hint(el)}`;
    if (el.type === "file") {
      const kind = /cover|carta|motivation/.test(all) ? "cover" : /resume|\bcv\b|curriculum|vitae/.test(all) ? "resume" : null;
      const tag = kind || (fileIndex === 0 ? "resume" : null);
      if (tag && !report.files.some((f) => f.kind === tag)) {
        el.setAttribute("data-jt-file", tag);
        report.files.push({ kind: tag, label: label || tag });
      }
      fileIndex++;
      continue;
    }
    if (!visible(el)) continue;
    if (SENSITIVE.test(all)) { report.skipped.push(label || el.name); continue; }
    if ((el.value || "").trim() && !(el instanceof HTMLSelectElement && el.selectedIndex <= 0)) continue;  // ya tiene algo

    let field = el.type === "email" ? "email" : el.type === "tel" ? "phone" : null;
    if (!field) for (const [name, re] of RULES) if (re.test(key) || (!key && re.test(hint(el)))) { field = name; break; }
    if (!field) for (const [name, re] of RULES.slice(0, 11)) if (re.test(hint(el))) { field = name; break; }
    if (field === "full_name" && hasLast) field = "first_name";

    let value = null;
    if (field?.startsWith("a:")) value = profile.answers_by_key[field.slice(2)] || null;
    else if (field) value = profile[field] || null;
    if (!value && label && (el instanceof HTMLTextAreaElement || el.type === "text" || !el.type)) {
      // Pregunta propia de la empresa: busca la más parecida en tus respuestas preparadas
      let best = null, score = 0;
      for (const a of profile.answers) {
        const s = similar(label, a.question);
        if (s > score) { score = s; best = a; }
      }
      if (best && score >= 0.6) { value = best.answer; field = `respuesta: ${best.question}`; }
    }
    if (field === "cover_letter" && !(el instanceof HTMLTextAreaElement)) value = null;
    if (field?.startsWith("a:permiso_trabajo") && !(el instanceof HTMLTextAreaElement || el.type === "text")) value = null;

    if (value && el instanceof HTMLSelectElement) {
      const want = norm(value);
      const opt = [...el.options].find((o) => o.value && (norm(o.text) === want || (norm(o.text).length > 2 && want.includes(norm(o.text)))));
      value = opt ? opt.value : null;
    }
    if (value && !used.has(el)) {
      setValue(el, value);
      used.add(el);
      mark(el, true);
      report.filled.push({ label: label || el.name || field, field });
    } else if (required(el, label)) {
      mark(el, false);
      report.missing.push(label || el.name || "(campo sin nombre)");
    }
  }

  // Preguntas sí/no y casillas obligatorias: las dejamos para ti, pero las señalamos
  const groups = new Map();
  document.querySelectorAll("input[type=radio], input[type=checkbox]").forEach((el) => {
    if (!el.required && el.getAttribute("aria-required") !== "true") return;
    const key = el.type === "radio" ? `r:${el.name}` : `c:${el.id || el.name}`;
    if (!groups.has(key)) groups.set(key, el);
  });
  groups.forEach((el) => {
    const container = el.closest("fieldset, [role=radiogroup], [class*=question], [class*=field]") || el.parentElement;
    const label = (text(container.querySelector("legend, label, [class*=label]")) || labelOf(el)).slice(0, 200);
    const checked = el.type === "radio" ? document.querySelector(`input[type=radio][name="${CSS.escape(el.name)}"]:checked`) : el.checked;
    if (!checked) { container.style.outline = "2px solid #f59e0b"; report.missing.push(label || "(casilla obligatoria)"); }
  });
  return report;
}
