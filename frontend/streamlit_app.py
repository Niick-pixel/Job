"""JobTracker AI · interfaz Streamlit.

Arranque:  streamlit run frontend/streamlit_app.py
Requiere el backend en marcha (BACKEND_URL, por defecto http://localhost:8000).
"""
import os
from datetime import date

import httpx
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
api = httpx.Client(base_url=BACKEND, timeout=300)  # las llamadas a la IA pueden tardar

COLUMNS = {
    "por_aplicar": "📝 Por aplicar",
    "aplicado": "📤 Aplicado",
    "entrevista": "🎤 Entrevista",
    "rechazado": "❌ Rechazado",
}
URGENCY_ICON = {
    "ideal": "🟢", "buena": "🟢", "competida": "🟡", "tardía": "🟠",
    "probablemente_cerrada": "🔴", "desconocida": "⚪",
}

st.set_page_config(page_title="JobTracker AI", page_icon="💼", layout="wide")


def call(method: str, path: str, **kwargs):
    try:
        r = api.request(method, path, **kwargs)
    except httpx.HTTPError:
        st.error(f"No se puede conectar con el backend en {BACKEND}. ¿Está arrancado?")
        st.stop()
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
        st.error(f"Error {r.status_code}: {detail}")
        return None
    return r.json()


# ── Barra lateral: CV activo + alertas ──────────────────────────
with st.sidebar:
    st.title("💼 JobTracker AI")
    cvs = call("GET", "/api/cv") or []
    cv_id = None
    if cvs:
        labels = {f"{c['full_name'] or c['filename']} (#{c['id']})": c["id"] for c in cvs}
        cv_id = labels[st.selectbox("CV activo", list(labels))]
    else:
        st.info("Sube tu CV en la pestaña «Mi CV».")

    alerts = call("GET", "/api/emails/alerts") or []
    if alerts:
        st.subheader("🔔 Entrevistas detectadas")
        for a in alerts[:5]:
            when = a["analysis"].get("interview_datetime")
            st.warning(f"**{a['analysis'].get('company') or a['sender']}**\n\n{a['subject']}"
                       + (f"\n\n🗓 {when}" if when else ""))

    st.divider()
    sysinfo = call("GET", "/api/system/version") or {}
    st.caption(f"Versión {sysinfo.get('version', '?')}" + ("" if sysinfo.get("installed") else " · modo desarrollo"))
    if sysinfo.get("rolled_back_from"):
        st.caption(f"↩️ Se revirtió la {sysinfo['rolled_back_from']} por un fallo al arrancar")
    if sysinfo.get("update_available"):
        st.success(f"⬆️ Nueva versión {sysinfo['latest']} disponible")
        if sysinfo.get("notes"):
            with st.expander("Novedades"):
                st.markdown(sysinfo["notes"])
        if st.button("Actualizar ahora"):
            if call("POST", "/api/system/update") is not None:
                st.info("Actualizando… la app se reiniciará sola en ~1 minuto. Recarga la página después.")

pending = call("GET", "/api/packages") or []
tab_inbox, tab_job, tab_board, tab_mail, tab_agent, tab_cv = st.tabs([
    f"📥 Bandeja ({len(pending)})", "🔍 Analizar oferta", "📋 Kanban", "📬 Correos", "🤖 Agente", "📄 Mi CV"])

# ── Bandeja de aprobación ───────────────────────────────────────
with tab_inbox:
    if not pending:
        st.info("No hay candidaturas pendientes. El agente las prepara solo; también puedes pulsar "
                "«Buscar ahora» en la pestaña 🤖 Agente o «Preparar candidatura» en 🔍 Analizar oferta.")
    for pkg in pending:
        job, match = pkg["job"], pkg["match"] or {}
        urg = job.get("urgency") or {}
        with st.container(border=True):
            h1, h2 = st.columns([4, 1])
            h1.markdown(f"### {job['title']}\n**{job['company'] or '¿?'}** · {job['location'] or ''} · _{job['source']}_")
            if match:
                h2.metric("Encaje", f"{match['score']:.0f}%")
            st.caption(f"{URGENCY_ICON.get(urg.get('level'), '⚪')} {urg.get('message', '')}")
            if match.get("summary"):
                st.write(match["summary"])
            c1, c2 = st.columns(2)
            if match.get("strengths"):
                c1.markdown("**✅ Puntos fuertes**\n" + "\n".join(f"- {x}" for x in match["strengths"][:4]))
            if match.get("gaps"):
                c2.markdown("**⚠️ Brechas**\n" + "\n".join(f"- {x}" for x in match["gaps"][:4]))

            st.markdown(f"**Titular adaptado:** {pkg['headline']}")
            with st.expander(f"✍️ Viñetas mejoradas ({len(pkg['bullets'])})"):
                for b in pkg["bullets"]:
                    st.markdown(f"~~{b['original']}~~\n\n➡️ **{b['improved']}**")
            letter = st.text_area("Carta de presentación", pkg["cover_letter"], height=220, key=f"letter_{pkg['id']}")
            answered = [a for a in pkg["answers"] if a.get("answer")]
            if answered:
                with st.expander(f"💬 Respuestas adaptadas ({len(answered)})"):
                    for a in answered:
                        st.markdown(f"**{a['question']}**\n\n{a['answer']}")
            if pkg["pending_answers"]:
                st.caption("Sin respuesta base (complétalas en 📄 Mi CV): " + "; ".join(pkg["pending_answers"][:5]))
            if pkg["honesty_warnings"]:
                st.warning("No añadido por falta de evidencia en tu CV: " + ", ".join(pkg["honesty_warnings"]))

            pdf = api.get(f"/api/packages/{pkg['id']}/cv.pdf")
            a1, a2, a3, a4 = st.columns(4)
            if pdf.status_code == 200:
                a1.download_button("📄 CV adaptado (PDF)", pdf.content, file_name=f"CV_{job['company'] or 'oferta'}.pdf",
                                   mime="application/pdf", key=f"pdf_{pkg['id']}")
            if job.get("apply_url"):
                a2.link_button("🔗 Abrir oferta", job["apply_url"])
            if a3.button("✅ Aprobar", key=f"ok_{pkg['id']}", type="primary"):
                call("POST", f"/api/packages/{pkg['id']}/decision", json={"decision": "aprobada", "cover_letter": letter})
                st.rerun()
            if a4.button("📤 Ya la envié", key=f"sent_{pkg['id']}"):
                call("POST", f"/api/packages/{pkg['id']}/decision", json={"decision": "enviada", "cover_letter": letter})
                st.rerun()
            r1, r2 = st.columns([3, 1])
            reason = r1.text_input("Motivo si la descartas (el agente aprende de esto)", key=f"why_{pkg['id']}",
                                   placeholder="p. ej. no quiero consultoras, sueldo bajo, demasiado junior…")
            if r2.button("🗑️ Descartar", key=f"no_{pkg['id']}"):
                call("POST", f"/api/packages/{pkg['id']}/decision", json={"decision": "descartada", "reason": reason or None})
                st.rerun()

    approved = call("GET", "/api/packages", params={"status": "aprobada"}) or []
    if approved:
        st.divider()
        st.subheader(f"✅ Aprobadas, pendientes de enviar ({len(approved)})")
        for pkg in approved:
            j = pkg["job"]
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.markdown(f"**{j['title']}** — {j['company'] or ''}")
            if j.get("apply_url"):
                c2.link_button("🔗 Aplicar", j["apply_url"])
            if c3.button("📤 Enviada", key=f"sent2_{pkg['id']}"):
                call("POST", f"/api/packages/{pkg['id']}/decision", json={"decision": "enviada"})
                st.rerun()

# ── CV ──────────────────────────────────────────────────────────
with tab_cv:
    up = st.file_uploader("Sube tu CV (PDF, TXT o MD)", type=["pdf", "txt", "md"])
    if up and st.button("Analizar CV con IA", type="primary"):
        with st.spinner("Extrayendo habilidades y experiencia…"):
            res = call("POST", "/api/cv", files={"file": (up.name, up.getvalue(), up.type or "application/octet-stream")})
        if res:
            st.success(f"CV analizado: {res['full_name'] or res['filename']}")
            st.rerun()

    if cv_id:
        cv = call("GET", f"/api/cv/{cv_id}")
        p = cv["profile"]
        st.header(p.get("full_name") or cv["filename"])
        st.caption(f"{p.get('headline') or ''} · {p.get('seniority')} · {p.get('years_experience') or '?'} años")
        st.write(p.get("summary"))
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Hard skills**\n\n" + ", ".join(p.get("hard_skills", [])))
        c2.markdown("**Tecnologías**\n\n" + ", ".join(p.get("technologies", [])))
        c3.markdown("**Idiomas**\n\n" + ", ".join(p.get("languages", [])))
        with st.expander("Experiencia"):
            for e in p.get("experience", []):
                st.markdown(f"**{e['role']}** — {e['company']} ({e.get('start') or '?'} – {e.get('end') or '?'})")
                for h in e.get("highlights", []):
                    st.markdown(f"- {h}")

    st.divider()
    st.subheader("💬 Banco de respuestas")
    st.caption("Respóndelas una vez: la IA las adapta a cada oferta, pero nunca inventa las que dejes vacías.")
    answers = call("GET", "/api/answers") or []
    with st.form("answers"):
        edited = {a["key"]: st.text_area(a["question"], a["answer"], key=f"ans_{a['key']}", height=80)
                  for a in answers}
        if st.form_submit_button("Guardar respuestas", type="primary"):
            for a in answers:
                if edited[a["key"]] != a["answer"]:
                    call("PUT", "/api/answers", json={"key": a["key"], "question": a["question"],
                                                       "answer": edited[a["key"]]})
            st.success("Guardadas")

# ── Oferta + matching + optimización ────────────────────────────
with tab_job:
    mode = st.radio("Origen de la oferta", ["Pegar texto", "Enlace"], horizontal=True)
    text = st.text_area("Texto de la oferta", height=220) if mode == "Pegar texto" else None
    url = st.text_input("URL de la oferta") if mode == "Enlace" else None
    c1, c2 = st.columns(2)
    known_date = c1.date_input("Fecha de publicación (opcional)", value=None, max_value=date.today())
    applicants = c2.number_input("Nº de candidatos (opcional)", min_value=0, value=None, step=1)

    if st.button("Analizar oferta", type="primary", disabled=not (text or url)):
        payload = {"text": text, "url": url,
                   "posted_date": known_date.isoformat() if known_date else None,
                   "applicants_count": applicants}
        with st.spinner("Analizando la oferta…"):
            job = call("POST", "/api/jobs", json=payload)
        if job:
            st.session_state["job_id"] = job["id"]

    jobs = call("GET", "/api/jobs") or []
    if jobs:
        st.divider()
        ids = [j["id"] for j in jobs]
        default = ids.index(st.session_state["job_id"]) if st.session_state.get("job_id") in ids else 0
        job = st.selectbox("Oferta", jobs, index=default,
                           format_func=lambda j: f"#{j['id']} · {j['title']} — {j['company'] or '¿?'}")
        u = job["urgency"]
        st.subheader(f"{URGENCY_ICON.get(u['level'], '⚪')} Urgencia: {u['level']} ({u['score']}/100)")
        st.write(u["message"])

        if not cv_id:
            st.info("Sube un CV para calcular la compatibilidad.")
        else:
            b1, b2, b3 = st.columns(3)
            if b3.button("📦 Preparar candidatura"):
                with st.spinner("Generando CV en PDF, carta y respuestas…"):
                    if call("POST", f"/api/jobs/{job['id']}/prepare", params={"cv_id": cv_id}):
                        st.success("Lista en 📥 Bandeja")
            if b1.button("🎯 Calcular compatibilidad"):
                with st.spinner("Comparando CV y oferta…"):
                    st.session_state[f"match_{job['id']}"] = call(
                        "POST", f"/api/jobs/{job['id']}/match", params={"cv_id": cv_id})
            if b2.button("✍️ Optimizar CV + carta"):
                with st.spinner("Generando sugerencias…"):
                    st.session_state[f"opt_{job['id']}"] = call(
                        "POST", f"/api/jobs/{job['id']}/optimize", params={"cv_id": cv_id})

            m = st.session_state.get(f"match_{job['id']}")
            if m:
                a = m["analysis"]
                k1, k2, k3 = st.columns(3)
                k1.metric("Compatibilidad", f"{m['score']:.0f}%")
                k2.metric("Juicio IA", f"{m['llm_score']}%")
                k3.metric("Cobertura de requisitos", f"{m['skills_coverage'] * 100:.0f}%")
                st.progress(min(int(m["score"]), 100))
                st.write(a["summary"])
                c1, c2 = st.columns(2)
                c1.markdown("**✅ Puntos fuertes**\n" + "\n".join(f"- {s}" for s in a["strengths"]))
                c2.markdown("**⚠️ Áreas de mejora**\n" + "\n".join(f"- {s}" for s in a["gaps"]))
                st.markdown("**Cómo cerrar la brecha**\n" + "\n".join(f"- {s}" for s in a["improvement_tips"]))
                st.caption("Keywords que faltan: " + ", ".join(a["missing_keywords"]))

            o = st.session_state.get(f"opt_{job['id']}")
            if o:
                st.subheader("Viñetas sugeridas")
                st.info(f"Titular sugerido: **{o['suggested_headline']}**")
                for b in o["bullet_suggestions"]:
                    st.markdown(f"~~{b['original']}~~\n\n➡️ **{b['improved']}**")
                    st.caption(f"+ {', '.join(b['keywords_added'])} · {b['reason']}")
                if o["honesty_warnings"]:
                    st.warning("No añadas sin evidencia: " + ", ".join(o["honesty_warnings"]))
                st.subheader("Carta de presentación")
                st.text_area("Carta", o["cover_letter"], height=320, label_visibility="collapsed")

# ── Kanban ──────────────────────────────────────────────────────
with tab_board:
    board = call("GET", "/api/applications/board") or {}
    cols = st.columns(len(COLUMNS))
    for col, (status, title) in zip(cols, COLUMNS.items()):
        cards = board.get(status, [])
        col.markdown(f"#### {title} ({len(cards)})")
        for card in cards:
            with col.container(border=True):
                st.markdown(f"**{card['job_title']}**\n\n{card['company'] or ''}")
                badges = []
                if card["match_score"] is not None:
                    badges.append(f"🎯 {card['match_score']:.0f}%")
                if card["urgency_level"]:
                    badges.append(f"{URGENCY_ICON.get(card['urgency_level'], '')} {card['urgency_level']}")
                if card["interview_at"]:
                    badges.append(f"🗓 {card['interview_at'][:16].replace('T', ' ')}")
                st.caption(" · ".join(badges))
                new = st.selectbox("Mover a", list(COLUMNS), index=list(COLUMNS).index(status),
                                   format_func=COLUMNS.get, key=f"mv_{card['id']}", label_visibility="collapsed")
                if new != status:
                    call("PATCH", f"/api/applications/{card['id']}", json={"status": new})
                    st.rerun()

# ── Correos ─────────────────────────────────────────────────────
with tab_mail:
    st.caption("Modo de correo configurado en EMAIL_MODE (simulated | gmail).")
    if st.button("🔄 Sincronizar bandeja"):
        with st.spinner("Leyendo y clasificando correos…"):
            res = call("POST", "/api/emails/sync")
        if res is not None:
            st.success(f"{len(res)} correos procesados")
    icon = {"entrevista": "🎤", "rechazo": "❌", "oferta": "🎉", "confirmacion_recepcion": "📨",
            "solicitud_info": "📎", "otro": "📭"}
    for ev in call("GET", "/api/emails") or []:
        with st.container(border=True):
            st.markdown(f"{icon.get(ev['category'], '📭')} **{ev['subject']}** — {ev['sender']}")
            st.caption(f"{ev['category']} · confianza {ev['confidence']:.0%}"
                       + (" · vinculado al Kanban" if ev["application_id"] else " · sin candidatura asociada"))
            st.write(ev["analysis"].get("summary", ""))
            if ev["analysis"].get("action_required"):
                st.info(ev["analysis"]["action_required"])

# ── Agente ──────────────────────────────────────────────────────


def _list(text: str) -> list[str]:
    return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]


with tab_agent:
    runs = call("GET", "/api/agent/runs", params={"limit": 5}) or []
    c1, c2 = st.columns([1, 3])
    if c1.button("🔎 Buscar ahora", type="primary"):
        if call("POST", "/api/agent/run") is not None:
            st.info("Buscando… tarda unos minutos. Las candidaturas aparecerán en 📥 Bandeja.")
    if runs:
        last = runs[0]
        icon = {"ok": "✅", "error": "❌", "running": "⏳"}.get(last["status"], "•")
        s_ = last["stats"] or {}
        c2.markdown(f"{icon} Última ejecución ({last['trigger']}) {last['started_at'][:16].replace('T', ' ')}: "
                    f"**{s_.get('descubiertas', 0)}** descubiertas · {s_.get('duplicadas', 0)} duplicadas · "
                    f"{s_.get('filtradas', 0)} filtradas · {s_.get('criba_baja', 0)} descartadas por IA · "
                    f"**{s_.get('preparadas', 0)}** preparadas")
        if last.get("error"):
            c2.error(last["error"])
        with st.expander("Detalle por fuente"):
            st.json(s_.get("fuentes", {}))

    prefs = call("GET", "/api/agent/preferences") or {}
    src = prefs.get("sources", {})
    with st.form("prefs"):
        st.subheader("🎯 Qué buscas")
        enabled = st.toggle("Agente activado (se ejecuta solo cada 3 h en la app instalada)", prefs.get("enabled", True))
        f1, f2 = st.columns(2)
        titles = f1.text_area("Puestos objetivo (separados por comas; vacío = todos)", ", ".join(prefs.get("target_titles", [])))
        exclude = f2.text_area("Excluir si contiene", ", ".join(prefs.get("exclude_keywords", [])),
                               placeholder="consultora, guardias, prácticas…")
        locations = f1.text_input("Ubicaciones aceptadas", ", ".join(prefs.get("locations", [])), placeholder="Madrid, España")
        blacklist = f2.text_input("Empresas a evitar", ", ".join(prefs.get("blacklist_companies", [])))
        g1, g2, g3, g4 = st.columns(4)
        remote_ok = g1.checkbox("Acepto remoto", prefs.get("remote_ok", True))
        remote_only = g2.checkbox("Solo remoto", prefs.get("remote_only", False))
        min_salary = g3.number_input("Salario mínimo anual", min_value=0, value=prefs.get("min_salary") or 0, step=1000)
        max_age = g4.number_input("Antigüedad máx. (días)", min_value=1, value=prefs.get("max_age_days", 30))
        k1, k2, k3 = st.columns(3)
        triage_t = k1.slider("Umbral de criba rápida", 0, 100, prefs.get("triage_threshold", 65))
        prepare_t = k2.slider("Umbral para preparar candidatura", 0, 100, prefs.get("prepare_threshold", 75))
        top_n = k3.number_input("Análisis completos por ejecución", 1, 50, prefs.get("deep_match_top_n", 10))

        st.subheader("📡 Fuentes")
        st.caption("Greenhouse/Lever/Ashby: el identificador está en la URL de la página de empleo de la empresa, "
                   "p. ej. boards.greenhouse.io/**acme**, jobs.lever.co/**acme**, jobs.ashbyhq.com/**acme**.")
        s1, s2, s3 = st.columns(3)
        gh = s1.text_area("Greenhouse", ", ".join(src.get("greenhouse", [])))
        lv = s2.text_area("Lever", ", ".join(src.get("lever", [])))
        ab = s3.text_area("Ashby", ", ".join(src.get("ashby", [])))
        t1, t2, t3 = st.columns(3)
        remotive = t1.text_input("Búsquedas en Remotive (remoto)", ", ".join(src.get("remotive_queries", [])))
        adzuna = t2.text_input("Búsquedas en Adzuna (requiere API key)", ", ".join(src.get("adzuna_queries", [])))
        country = t3.text_input("País Adzuna", src.get("adzuna_country", "es"))
        alerts = st.checkbox("Leer alertas de empleo de mi correo (LinkedIn, InfoJobs, Indeed…)", src.get("email_alerts", True))

        if st.form_submit_button("Guardar", type="primary"):
            body = {
                **prefs, "enabled": enabled, "target_titles": _list(titles), "exclude_keywords": _list(exclude),
                "locations": _list(locations), "blacklist_companies": _list(blacklist), "remote_ok": remote_ok,
                "remote_only": remote_only, "min_salary": int(min_salary) or None, "max_age_days": int(max_age),
                "triage_threshold": triage_t, "prepare_threshold": prepare_t, "deep_match_top_n": int(top_n),
                "sources": {**src, "greenhouse": _list(gh), "lever": _list(lv), "ashby": _list(ab),
                            "remotive_queries": _list(remotive), "adzuna_queries": _list(adzuna),
                            "adzuna_country": country.strip() or "es", "email_alerts": alerts},
            }
            if call("PUT", "/api/agent/preferences", json=body):
                st.success("Preferencias guardadas")

    st.subheader("🧭 Embudo de ofertas descubiertas")
    labels = {"": "Todas", "candidata": "Candidatas", "en_bandeja": "En bandeja", "criba_baja": "Descartadas por IA",
              "filtrada": "Filtradas", "aprobada": "Aprobadas", "descartada": "Descartadas por ti"}
    status = st.selectbox("Estado", list(labels), format_func=labels.get)
    found = call("GET", "/api/agent/jobs", params={"status": status} if status else None) or []
    if found:
        st.dataframe(
            [{"Puesto": j["title"], "Empresa": j["company"], "Ubicación": j["location"], "Fuente": j["source"],
              "Estado": j["status"], "Score": j["score"], "Motivo": j["reason"], "Enlace": j["url"]} for j in found],
            column_config={"Enlace": st.column_config.LinkColumn("Enlace", display_text="abrir")},
            hide_index=True,
        )
    else:
        st.caption("Todavía no hay ofertas descubiertas.")
