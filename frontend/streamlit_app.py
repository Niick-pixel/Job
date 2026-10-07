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

tab_cv, tab_job, tab_board, tab_mail = st.tabs(["📄 Mi CV", "🔍 Analizar oferta", "📋 Kanban", "📬 Correos"])

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
            b1, b2 = st.columns(2)
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
