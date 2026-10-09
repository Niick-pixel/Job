// ⚙️ Ajustes: apariencia, claves API, modelo de IA, Gmail y versión.
import { api } from "../api.js";
import { bookmarkletCode, bookmarkletHref } from "../bookmarklet.js";
import { THEMES, setMotion, setTheme } from "../theme.js";
import { button, field, h, icon, pageHead, stagger, toast, toggle } from "../ui.js";

export async function render(root, ctx) {
  const [keys, ai, gmail, version, diag, spend] = await Promise.all([
    api.get("/api/settings/keys"), api.get("/api/settings/ai"), api.get("/api/settings/gmail"), api.get("/api/system/version"),
    api.get("/api/status/diagnostics").catch(() => null), api.get("/api/status/spend").catch(() => null),
  ]);
  root.replaceChildren(stagger(h("div", {},
    pageHead("Ajustes", "Todo se guarda solo en tu Mac"),
    diag ? statusSection(diag, ctx) : null,
    spend ? spendSection(spend, root, ctx) : null,
    appearance(),
    keysSection(keys, root, ctx),
    customKeys(keys, root, ctx),
    aiSection(ai),
    browserSection(),
    gmailSection(gmail, root, ctx),
    about(version, keys))));
}

const section = (title, ...children) => h("div", {}, h("h2", { class: "section-title" }, title), ...children);
const modelName = (id) => id.replace(/^claude-(\w+)-(\d+)-(\d+)$/, (_, n, a, b) => `Claude ${n[0].toUpperCase()}${n.slice(1)} ${a}.${b}`);
const usd = (n) => `${Number(n || 0).toLocaleString("es-CR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;

// ── Estado (diagnóstico) ─────────────────────────────────────────
const STATUS_ICON = { ok: ["ok", "check"], warn: ["warn", "alert"], error: ["bad", "x"], off: ["", "clock"] };

function statusSection(d, ctx) {
  const problems = d.summary.error + d.summary.warn;
  const rows = d.checks.map((c) => {
    const [kind, ico] = STATUS_ICON[c.status];
    return h("div", { class: `diag-row ${c.status}` },
      h("span", { class: `diag-ico ${kind}` }, icon(ico)),
      h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, c.label), h("p", { class: "muted small" }, c.detail)),
      c.action ? button(c.action.label, { size: "sm", onClick: () => {
        if (c.action.route === "ajustes" && c.action.anchor) document.getElementById(`sec-${c.action.anchor}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
        else ctx.go(c.action.route);
      } }) : null);
  });
  return h("div", { id: "sec-estado" }, h("h2", { class: "section-title" }, "Estado"),
    h("section", { class: "card diag" },
      h("div", { class: "row between", style: { marginBottom: "6px" } },
        h("p", { style: { fontWeight: 600 } }, problems ? `${problems} cosa${problems > 1 ? "s" : ""} por revisar` : "Todo en orden"),
        h("span", { class: "faint small" }, `Versión ${d.version}`)),
      rows));
}

// ── Gasto en IA ──────────────────────────────────────────────────
function spendSection(s, root, ctx) {
  const ratio = s.budget_usd ? Math.min(1, s.month_usd / s.budget_usd) : null;
  const max = Math.max(...s.by_purpose.map((p) => p.cost_usd), 0.0001);
  const budget = h("input", { class: "input", type: "number", min: 0, max: 1000, step: 0.5, value: s.budget_usd ?? "",
    placeholder: "Sin tope", style: { maxWidth: "130px" } });
  const save = button("Guardar tope", { size: "sm", ico: "check", onClick: async () => {
    const prefs = await api.get("/api/agent/preferences");
    await api.put("/api/agent/preferences", { ...prefs, monthly_budget_usd: budget.value === "" ? null : Number(budget.value) });
    toast(budget.value === "" ? "Sin tope de gasto" : `Tope guardado: ${usd(budget.value)} al mes`);
    await render(root, ctx);
  } });
  return h("div", { id: "sec-gasto" }, h("h2", { class: "section-title" }, "Gasto en IA"),
    h("section", { class: "card stack" },
      h("div", { class: "spend-head" },
        h("div", {}, h("b", { class: "spend-total" }, usd(s.month_usd)), h("span", { class: "muted" }, " este mes"),
          h("p", { class: "faint small" }, `Previsión a fin de mes: ${usd(s.projected_usd)} · ${s.calls} llamada${s.calls === 1 ? "" : "s"} a Claude · modelo ${modelName(s.model)}`)),
        ratio !== null ? h("div", { class: "spend-meter", title: `${Math.round(ratio * 100)} % del tope` },
          h("i", { class: ratio >= 1 ? "bad" : ratio >= 0.8 ? "warn" : "", style: { "--w": `${Math.max(ratio * 100, 2)}%` } }),
          h("small", {}, `${Math.round(ratio * 100)} % de ${usd(s.budget_usd)}`)) : null),
      s.by_purpose.length ? h("div", { class: "stack", style: { gap: "8px" } }, s.by_purpose.map((p) =>
        h("div", { class: "bar-row" }, h("span", { class: "bar-label" }, p.purpose),
          h("div", { class: "bar" }, h("i", { class: "accent", style: { "--w": `${Math.max((100 * p.cost_usd) / max, 2)}%` } })),
          h("span", { class: "bar-value" }, usd(p.cost_usd), h("small", {}, ` · ${p.calls}`))))) :
        h("p", { class: "muted small" }, "Aún no hay llamadas a la IA este mes."),
      h("hr", { class: "divider", style: { margin: "4px 0" } }),
      h("div", { class: "row between" },
        h("div", { style: { flex: "1 1 260px", minWidth: 0 } }, h("p", { style: { fontWeight: 550 } }, "Tope mensual (USD)"),
          h("p", { class: "faint small" }, "Al 80 % te avisamos; al llegar, el agente se pausa hasta el mes siguiente. Lo que hagas tú a mano sigue funcionando.")),
        h("div", { class: "row", style: { flexWrap: "nowrap" } }, budget, save)),
      h("p", { class: "faint small" }, icon("alert"), " Es una estimación con los precios públicos de Claude. La factura exacta está en console.anthropic.com.")));
}

// ── Apariencia ───────────────────────────────────────────────────
function appearance() {
  const grid = h("div", { class: "themes" });
  const draw = () => {
    const current = document.documentElement.dataset.theme;
    grid.replaceChildren(...THEMES.map((t) => {
      const preview = t.bg
        ? h("div", { class: "theme-preview", style: { background: t.bg } },
          h("i", { style: { width: "55%", background: t.accent } }),
          h("i", { style: { width: "85%", background: t.surface, boxShadow: `0 0 0 1px ${t.text}14` } }),
          h("i", { style: { width: "70%", background: t.surface, boxShadow: `0 0 0 1px ${t.text}14` } }))
        : h("div", { class: "theme-preview", style: { background: "linear-gradient(135deg, #f7f7f5 50%, #151517 50%)" } },
          h("i", { style: { width: "55%", background: "#4f46e5" } }), h("i", { style: { width: "85%", background: "#ffffff" } }),
          h("i", { style: { width: "70%", background: "#1d1d20" } }));
      return h("button", { class: `theme-swatch ${t.id === current ? "active" : ""}`, type: "button", "aria-pressed": String(t.id === current),
        onClick: async () => { await setTheme(t.id); draw(); } },
        preview, h("div", { class: "theme-name" }, h("span", {}, t.name), icon("check")));
    }));
  };
  draw();
  const motion = toggle(document.documentElement.dataset.motion === "reduce", (v) => setMotion(v));
  return section("Apariencia",
    h("section", { class: "card stack" }, grid,
      h("div", { class: "row between", style: { paddingTop: "4px" } },
        h("div", {}, h("p", { style: { fontWeight: 550 } }, "Reducir animaciones"),
          h("p", { class: "faint small" }, "Quita transiciones y movimientos")), motion)));
}

// ── Claves API ───────────────────────────────────────────────────
function keysSection(data, root, ctx) {
  const groups = {};
  for (const k of data.keys) (groups[k.group] ||= []).push(k);
  return h("div", { id: "sec-claves" }, h("h2", { class: "section-title" }, "Claves API"),
    data.keychain ? h("p", { class: "faint small center", style: { marginBottom: "12px" } }, icon("shield"), " Se guardan en el Llavero de macOS, cifradas") : null,
    ...Object.entries(groups).map(([group, keys]) => h("div", { style: { marginBottom: "14px" } },
    h("p", { class: "faint small center", style: { marginBottom: "10px" } }, group),
    h("div", { class: "stack" }, keys.map((k) => keyCard(k, root, ctx))))));
}

function secretInput(placeholder) {
  const input = h("input", { class: "input mono", type: "password", placeholder, autocomplete: "off", spellcheck: "false" });
  const eye = h("button", { class: "btn ghost icon sm", type: "button", title: "Mostrar", onClick: () => {
    input.type = input.type === "password" ? "text" : "password";
  } }, icon("eye"));
  const wrap = h("div", { class: "row", style: { flexWrap: "nowrap", flex: 1, gap: "6px" } }, input, eye);
  wrap.input = input;
  return wrap;
}

function keyCard(k, root, ctx) {
  const status = h("span", { class: `chip ${k.configured ? "ok" : k.required ? "warn" : ""}` },
    h("span", { class: `dot ${k.configured ? "ok" : k.required ? "warn" : ""}` }),
    k.configured ? `Configurada · ${k.preview}` : k.required ? "Necesaria" : "Opcional");
  const result = h("p", { class: "small", hidden: true, style: { marginTop: "10px" } });
  const secret = secretInput(k.configured ? "Pega una nueva para sustituirla" : k.placeholder);

  const test = async () => {
    const r = await api.post(`/api/settings/keys/${k.name}/test`);
    result.hidden = false;
    result.style.color = r.ok ? "var(--ok)" : r.ok === false ? "var(--bad)" : "var(--text-3)";
    result.replaceChildren(icon(r.ok ? "check" : "alert"), " ", r.message);
  };
  const save = button("Guardar", { kind: "primary", ico: "check", onClick: async () => {
    if (!secret.input.value.trim()) throw new Error("Pega la clave primero");
    await api.put("/api/settings/keys", { name: k.name, value: secret.input.value });
    secret.input.value = "";
    toast(`${k.label} guardada`);
    if (k.testable) await test().catch(() => {});
    k.configured = true;
    setTimeout(() => render(root, ctx), 1400);
  } });

  return h("section", { class: "card" },
    h("div", { class: "row between", style: { alignItems: "flex-start" } },
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("h3", {}, k.label), h("p", { class: "muted small", style: { marginTop: "2px" } }, k.description)), status),
    h("div", { class: "row", style: { marginTop: "14px", flexWrap: "nowrap" } }, secret, save,
      k.testable && k.configured ? button("Probar", { onClick: test }) : null,
      k.configured ? button("", { kind: "ghost", ico: "trash", title: "Borrar", onClick: async () => {
        await api.del(`/api/settings/keys/${k.name}`);
        toast("Clave borrada");
        render(root, ctx);
      } }) : null),
    result,
    k.steps?.length ? h("details", { class: "disclosure", style: { marginTop: "14px" } },
      h("summary", {}, icon("chevron", "chev"), "Cómo conseguirla"),
      h("div", { class: "body" },
        h("ol", { style: { margin: "0 0 12px", paddingLeft: "20px", color: "var(--text-2)", display: "grid", gap: "4px" } },
          k.steps.map((s) => h("li", {}, s))),
        h("a", { class: "btn sm", href: k.url, target: "_blank", rel: "noopener" }, icon("external"), h("span", {}, "Abrir la web")))) : null);
}

function customKeys(data, root, ctx) {
  const name = h("input", { class: "input mono", placeholder: "NOMBRE_DE_LA_CLAVE", autocomplete: "off", spellcheck: "false",
    style: { flex: "1 1 0", minWidth: 0 } });
  name.addEventListener("input", () => { name.value = name.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"); });
  const secret = secretInput("valor");
  secret.style.flex = "1.3 1 0";
  secret.style.minWidth = "0";
  const rows = data.custom.map((c) => h("div", { class: "row between", style: { padding: "10px 0", borderBottom: "1px solid var(--border)" } },
    h("div", {}, h("code", { style: { fontFamily: "var(--mono)", fontWeight: 600 } }, c.name), h("span", { class: "faint small" }, `  ${c.preview || ""}`)),
    button("", { kind: "ghost", size: "sm", ico: "trash", title: "Borrar", onClick: async () => {
      await api.del(`/api/settings/keys/${c.name}`);
      toast("Clave borrada");
      render(root, ctx);
    } })));
  return section("Otras claves",
    h("section", { class: "card stack" },
      h("p", { class: "muted small" }, "Añade cualquier otra clave o variable para futuras integraciones. Se guarda en ",
        h("code", { style: { fontFamily: "var(--mono)" } }, ".env"), " con permisos privados y nunca se muestra completa."),
      rows.length ? h("div", {}, rows) : null,
      h("div", { class: "row", style: { flexWrap: "nowrap" } }, name, secret,
        button("Añadir", { kind: "primary", ico: "plus", onClick: async () => {
          await api.put("/api/settings/keys", { name: name.value, value: secret.input.value });
          toast(`${name.value} guardada`);
          render(root, ctx);
        } }))));
}

// ── Modelo de IA ─────────────────────────────────────────────────
function aiSection(ai) {
  const select = (value, options) => h("select", { class: "input" },
    options.map((o) => h("option", { value: o.id ?? o, selected: (o.id ?? o) === value }, o.label ? `${o.label} — ${o.note}` : o)));
  const model = select(ai.model, ai.models);
  const fast = select(ai.fast_model, ai.models);
  const effortLabels = { low: "Bajo · más rápido y barato", medium: "Medio", high: "Alto", xhigh: "Muy alto", max: "Máximo · más lento y caro" };
  const effort = select(ai.effort, ai.efforts.map((e) => ({ id: e, label: effortLabels[e]?.split(" · ")[0] || e, note: effortLabels[e]?.split(" · ")[1] || "" })));

  const cards = h("div", { class: "presets" });
  const drawPresets = (active) => cards.replaceChildren(...ai.presets.map((p) => h("button", {
    type: "button", class: `preset ${p.id === active ? "active" : ""}`, "aria-pressed": String(p.id === active),
    onClick: async () => {
      const r = await api.put("/api/settings/ai", { model: p.model, fast_model: p.fast_model, effort: p.effort });
      model.value = r.model; fast.value = r.fast_model; effort.value = r.effort;
      drawPresets(r.profile);
      toast(`Perfil «${p.label}» activado`);
    },
  }, h("span", { class: "row between" }, h("b", {}, p.label), icon("check")),
    h("span", { class: "preset-price" }, p.estimate),
    h("span", { class: "faint small" }, p.note))));
  drawPresets(ai.profile);

  return section("Inteligencia artificial",
    h("section", { class: "card stack" },
      h("p", { class: "muted small center" }, "Elige cuánto quieres gastar en la API de Claude. Estimación con ~100 ofertas cribadas y ~2 candidaturas al día."),
      cards,
      h("details", { class: "disclosure" },
        h("summary", {}, icon("chevron", "chev"), "Personalizar modelos"),
        h("div", { class: "body stack" },
          h("div", { class: "grid-2" },
            field("Modelo principal", model, "Análisis completo, CV adaptado y cartas"),
            field("Modelo rápido", fast, "Criba masiva de ofertas")),
          field("Nivel de razonamiento", effort, "Más razonamiento = mejores resultados, más tiempo y coste"),
          h("div", { class: "row", style: { justifyContent: "flex-end" } },
            button("Guardar", { kind: "primary", ico: "check", onClick: async () => {
              const r = await api.put("/api/settings/ai", { model: model.value, fast_model: fast.value, effort: effort.value });
              drawPresets(r.profile);
              toast(r.profile === "personalizado" ? "Configuración personalizada guardada" : "Modelo actualizado");
            } }))))));
}

// ── Guardar desde el navegador ───────────────────────────────────
function browserSection() {
  const drag = h("a", { class: "btn", href: bookmarkletHref(location.origin), title: "Arrástrame a la barra de favoritos del navegador",
    onClick: (e) => { e.preventDefault(); toast("Arrástralo a la barra de favoritos del navegador"); } },
    icon("plus"), h("span", {}, "Guardar en JobTracker"));
  return section("Navegador",
    h("section", { class: "card stack" },
      h("div", {}, h("h3", {}, "Guardar ofertas desde el navegador"),
        h("p", { class: "muted small", style: { marginTop: "2px" } },
          "Un botón en la barra de favoritos de Safari o Chrome envía a JobTracker la oferta que estés viendo: LinkedIn, InfoJobs, Indeed o la web de cualquier empresa.")),
      h("div", { class: "row" },
        h("a", { class: "btn primary", href: "/capture", target: "_blank", rel: "noopener" }, icon("external"), h("span", {}, "Instalar en mi navegador")),
        drag,
        button("Copiar código", { kind: "ghost", ico: "file", onClick: async () => {
          await navigator.clipboard.writeText(bookmarkletCode(location.origin)); toast("Código copiado");
        } })),
      h("p", { class: "faint small" }, "«Instalar en mi navegador» abre una guía en tu navegador desde la que arrastras el botón a la barra de favoritos.")));
}

// ── Gmail ────────────────────────────────────────────────────────
function gmailSection(g, root, ctx) {
  const input = h("input", { type: "file", accept: ".json,application/json", hidden: true });
  input.addEventListener("change", async () => {
    try {
      await api.upload("/api/settings/gmail/credentials", input.files[0]);
      toast("Credenciales guardadas · pulsa «Sincronizar» en Correos para autorizar");
      render(root, ctx);
    } catch (e) { toast(e.message, "error", 6000); }
  });
  const state = g.connected ? ["ok", "Conectado"] : g.credentials ? ["warn", "Falta autorizar"] : ["", "Modo de prueba"];
  return h("div", { id: "sec-gmail" }, h("h2", { class: "section-title" }, "Correo"),
    h("section", { class: "card" },
      h("div", { class: "row between", style: { alignItems: "flex-start" } },
        h("div", { style: { flex: 1 } }, h("h3", {}, "Gmail"),
          h("p", { class: "muted small", style: { marginTop: "2px" } }, "Lee (solo lectura) las respuestas de empresas y tus alertas de empleo de LinkedIn, InfoJobs o Indeed.")),
        h("span", { class: `chip ${state[0]}` }, h("span", { class: `dot ${state[0]}` }), state[1])),
      h("div", { class: "row", style: { marginTop: "14px" } },
        button(g.credentials ? "Sustituir credenciales" : "Subir credenciales (JSON)", { kind: g.credentials ? "" : "primary", ico: "upload", onClick: () => input.click() }),
        g.credentials ? button("Autorizar / sincronizar", { ico: "refresh", onClick: () => ctx.go("correos") }) : null,
        g.mode === "gmail" ? button("Desconectar", { kind: "ghost", onClick: async () => { await api.del("/api/settings/gmail"); toast("Gmail desconectado"); render(root, ctx); } }) : null,
        input),
      h("details", { class: "disclosure", style: { marginTop: "14px" } },
        h("summary", {}, icon("chevron", "chev"), "Cómo conseguir las credenciales"),
        h("div", { class: "body" },
          h("ol", { style: { margin: "0 0 12px", paddingLeft: "20px", color: "var(--text-2)", display: "grid", gap: "4px" } },
            ["En Google Cloud Console crea un proyecto (gratis)",
              "APIs y servicios → Biblioteca → activa «Gmail API»",
              "Pantalla de consentimiento OAuth → tipo «Externo» → añade tu correo como usuario de prueba",
              "Credenciales → Crear credenciales → ID de cliente OAuth → «Aplicación de escritorio»",
              "Descarga el JSON y súbelo aquí. Al sincronizar se abrirá el navegador para autorizar el acceso de solo lectura"]
              .map((s) => h("li", {}, s))),
          h("a", { class: "btn sm", href: "https://console.cloud.google.com/apis/credentials", target: "_blank", rel: "noopener" },
            icon("external"), h("span", {}, "Abrir Google Cloud Console"))))));
}

// ── Acerca de ────────────────────────────────────────────────────
function about(v, keys) {
  return section("Acerca de",
    h("section", { class: "card center" },
      h("p", { style: { fontWeight: 600 } }, `JobTracker AI ${v.version}`),
      h("p", { class: "faint small", style: { marginTop: "4px" } },
        v.installed ? (v.auto_update ? "Se actualiza sola cada 6 horas · actualizaciones firmadas" : "Actualizaciones automáticas desactivadas") : "Modo desarrollo"),
      v.update_available ? h("div", { style: { marginTop: "12px" } }, button(`Actualizar a ${v.latest}`, { kind: "primary", ico: "arrowUp", onClick: async () => {
        await api.post("/api/system/update");
        toast("Actualizando… la app se reiniciará sola");
      } })) : null,
      h("p", { class: "faint small", style: { marginTop: "10px" } }, "Claves en ", h("code", { style: { fontFamily: "var(--mono)" } }, keys.path))));
}
