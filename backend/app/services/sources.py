"""Fuentes de ofertas: APIs públicas de ATS y portales, y alertas de empleo por correo.

Cada fuente devuelve `RawJob` normalizados. Los fallos de una fuente nunca paran a las
demás: se registran en las estadísticas de la ejecución del agente.

Notas por fuente:
- Greenhouse, Lever y Ashby publican las ofertas de cada empresa en JSON público y sin
  autenticación. Necesitas el identificador de la empresa (aparece en la URL de su portal).
- Remotive pide atribución y un uso moderado (pocas consultas al día): el agente consulta
  como mucho una vez por ejecución.
- Adzuna requiere app_id/app_key gratuitos (developer.adzuna.com).
- LinkedIn/InfoJobs/Indeed no se rascan: se leen las alertas que ya te envían por correo.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from ..schemas import AlertExtraction, EmailIn, SourcesConfig
from .llm import LLMClient

USER_AGENT = "JobTrackerAI/0.3 (+https://github.com/Niick-pixel/Job)"


@dataclass
class RawJob:
    source: str
    external_id: str
    title: str
    company: str | None
    location: str | None
    url: str | None
    description: str
    apply_url: str | None = None
    posted_date: date | None = None
    remote: bool | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Texto completo para la IA."""
        head = [self.title, self.company or "", self.location or ""]
        if self.salary_text:
            head.append(f"Salario: {self.salary_text}")
        return "\n".join(h for h in head if h) + "\n\n" + self.description


class SourceError(RuntimeError):
    pass


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    # Solo los elementos de bloque cortan línea; los inline (<strong>, <a>…) quedan en la frase
    for block in soup.find_all(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"]):
        block.append("\n")
    text = soup.get_text("")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):  # epoch en ms (Lever)
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
        return dateparser.parse(str(value)).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _is_remote(*texts: str | None) -> bool | None:
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    return bool(re.search(r"\bremot[eo]\b|\bteletrabajo\b|anywhere|work from home", blob)) or None


def _get_json(client: httpx.Client, url: str, **params):
    try:
        r = client.get(url, params=params or None, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SourceError(f"{url}: {e}") from e


# ── ATS ─────────────────────────────────────────────────────────


def fetch_greenhouse(client: httpx.Client, board: str) -> list[RawJob]:
    data = _get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", content="true")
    jobs = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name")
        jobs.append(RawJob(
            source="greenhouse",
            external_id=f"greenhouse:{board}:{j['id']}",
            title=j.get("title", "").strip(),
            company=j.get("company_name") or board,
            location=location,
            url=j.get("absolute_url"),
            apply_url=j.get("absolute_url"),
            description=html_to_text(j.get("content")),
            # first_published no siempre viene; updated_at es la mejor aproximación
            posted_date=_date(j.get("first_published") or j.get("updated_at")),
            remote=_is_remote(location, j.get("title")),
        ))
    return jobs


def fetch_lever(client: httpx.Client, company: str) -> list[RawJob]:
    data = _get_json(client, f"https://api.lever.co/v0/postings/{company}", mode="json")
    jobs = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or "")
        salary = j.get("salaryRange") or {}
        workplace = j.get("workplaceType")
        jobs.append(RawJob(
            source="lever",
            external_id=f"lever:{company}:{j['id']}",
            title=(j.get("text") or "").strip(),
            company=company,
            location=cats.get("location"),
            url=j.get("hostedUrl"),
            apply_url=j.get("applyUrl") or j.get("hostedUrl"),
            description="\n\n".join(p for p in parts if p).strip(),
            posted_date=_date(j.get("createdAt")),
            remote=True if workplace == "remote" else (False if workplace in ("on-site", "hybrid") else
                                                         _is_remote(cats.get("location"))),
            salary_text=j.get("salaryDescriptionPlain") or (
                f"{salary.get('min')}-{salary.get('max')} {salary.get('currency', '')} {salary.get('interval', '')}".strip()
                if salary else None),
            salary_min=_annual(salary.get("min"), salary.get("interval")),
            salary_max=_annual(salary.get("max"), salary.get("interval")),
            extra={"commitment": cats.get("commitment"), "team": cats.get("team"), "workplace": workplace},
        ))
    return jobs


def fetch_ashby(client: httpx.Client, org: str) -> list[RawJob]:
    data = _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{org}", includeCompensation="true")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        location = j.get("location") if isinstance(j.get("location"), str) else (j.get("location") or {}).get("name")
        workplace = (j.get("workplaceType") or "").lower()
        jobs.append(RawJob(
            source="ashby",
            external_id=f"ashby:{org}:{j.get('id') or j.get('jobUrl')}",
            title=(j.get("title") or "").strip(),
            company=org,
            location=location,
            url=j.get("jobUrl"),
            apply_url=j.get("applyUrl") or j.get("jobUrl"),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_date=_date(j.get("publishedAt") or j.get("publishedDate")),
            remote=True if (j.get("isRemote") or workplace == "remote") else _is_remote(location),
            salary_text=comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary"),
        ))
    return jobs


# ── Portales ────────────────────────────────────────────────────


def fetch_remotive(client: httpx.Client, query: str) -> list[RawJob]:
    data = _get_json(client, "https://remotive.com/api/remote-jobs", search=query, limit=50)
    return [
        RawJob(
            source="remotive",
            external_id=f"remotive:{j['id']}",
            title=(j.get("title") or "").strip(),
            company=j.get("company_name"),
            location=j.get("candidate_required_location") or "Remoto",
            url=j.get("url"),
            apply_url=j.get("url"),
            description=html_to_text(j.get("description")),
            posted_date=_date(j.get("publication_date")),
            remote=True,
            salary_text=j.get("salary") or None,
            extra={"job_type": j.get("job_type"), "attribution": "Remotive"},
        )
        for j in data.get("jobs", [])
    ]


def fetch_adzuna(client: httpx.Client, query: str, country: str, app_id: str, app_key: str) -> list[RawJob]:
    data = _get_json(
        client, f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
        app_id=app_id, app_key=app_key, what=query, results_per_page=50, max_days_old=30,
    )
    jobs = []
    for j in data.get("results", []):
        smin, smax = j.get("salary_min"), j.get("salary_max")
        jobs.append(RawJob(
            source="adzuna",
            external_id=f"adzuna:{j['id']}",
            title=html_to_text(j.get("title")),
            company=(j.get("company") or {}).get("display_name"),
            location=(j.get("location") or {}).get("display_name"),
            url=j.get("redirect_url"),
            apply_url=j.get("redirect_url"),
            description=html_to_text(j.get("description")),
            posted_date=_date(j.get("created")),
            remote=_is_remote(j.get("title"), j.get("description")),
            salary_text=f"{smin:.0f}-{smax:.0f}" if smin and smax else None,
            salary_min=smin, salary_max=smax,
        ))
    return jobs


def _annual(amount, interval: str | None) -> float | None:
    if amount in (None, ""):
        return None
    factor = {"per-hour-wage": 1800, "per-month-salary": 12, "per-year-salary": 1}.get(interval or "", 1)
    return float(amount) * factor


# ── Alertas de empleo por correo ────────────────────────────────

ALERT_SENDERS = re.compile(
    r"jobalerts?-noreply@linkedin|jobs-noreply@linkedin|@infojobs\.net|alert@indeed|@indeed\.com"
    r"|@glassdoor|@tecnoempleo|@welcometothejungle|@getmanfred|noreply@jobs"
    # Latinoamérica: Computrabajo, elempleo, Empleos.net (CR), Bumeran/ZonaJobs, OCC, Get on Board, Torre…
    r"|@computrabajo|@elempleo|@empleos\.net|@bumeran|@zonajobs|@occ\.com\.mx|@occmundial|@getonbrd|@torre\.(?:co|ai)"
    r"|@tecoloco|@buscojobs|@laborum|@trabajando\.com|@multitrabajos|@konzerta",
    re.I,
)

ALERT_SYSTEM = """Extraes ofertas de empleo de correos de alertas (LinkedIn, Computrabajo, InfoJobs, Indeed, elempleo…).
Devuelve cada oferta que aparezca, sin inventar datos: si falta la empresa o la ubicación, null.
Copia la URL de cada oferta tal cual aparece en el correo."""


def is_job_alert(email: EmailIn) -> bool:
    return bool(ALERT_SENDERS.search(email.sender)) or bool(
        re.search(r"alerta de empleo|job alert|nuevas ofertas|new jobs? for you|empleos? que coinciden|ofertas? de empleo para ti"
                  r"|vacantes? (nuevas?|para ti|que te pueden)", email.subject, re.I)
    )


def extract_alert_jobs(llm: LLMClient, email: EmailIn, fast_model: str) -> list[RawJob]:
    result = llm.structured(
        system=ALERT_SYSTEM,
        prompt=f"De: {email.sender}\nAsunto: {email.subject}\n\n<correo>\n{email.body[:30_000]}\n</correo>",
        schema=AlertExtraction, model=fast_model, effort="low", max_tokens=8000,
    )
    received = email.received_at.date() if email.received_at else None
    jobs = []
    for i, j in enumerate(result.jobs):
        if not j.title:
            continue
        jobs.append(RawJob(
            source="email",
            external_id=f"email:{email.message_id}:{i}",
            title=j.title.strip(), company=j.company, location=j.location,
            url=j.url, apply_url=j.url,
            description=j.snippet or "(Descripción no incluida en la alerta)",
            posted_date=received, remote=_is_remote(j.location, j.title),
            extra={"partial": True},
        ))
    return jobs


# ── Orquestación ────────────────────────────────────────────────


def collect(client: httpx.Client, cfg: SourcesConfig, adzuna_creds: tuple[str, str] | None,
            country: str | None = None) -> tuple[list[RawJob], dict]:
    """Ejecuta todas las fuentes HTTP configuradas. Devuelve (ofertas, informe por fuente)."""
    from . import sources_latam as lt

    tasks = (
        [(f"greenhouse:{b}", fetch_greenhouse, (b,)) for b in cfg.greenhouse]
        + [(f"lever:{c}", fetch_lever, (c,)) for c in cfg.lever]
        + [(f"ashby:{o}", fetch_ashby, (o,)) for o in cfg.ashby]
        + [(f"remotive:{q}", fetch_remotive, (q,)) for q in cfg.remotive_queries]
        + [(f"workday:{(lt.parse_workday(u) or (u,))[0]}", lt.fetch_workday, (u, country)) for u in cfg.workday]
        + [(f"smartrecruiters:{c}", lt.fetch_smartrecruiters, (c, country)) for c in cfg.smartrecruiters]
        + [(f"recruitee:{c}", lt.fetch_recruitee, (c, country)) for c in cfg.recruitee]
        + [(f"breezy:{c}", lt.fetch_breezy, (c, country)) for c in cfg.breezy]
        + [(f"workable:{c}", lt.fetch_workable, (c, country)) for c in cfg.workable]
        + [(f"getonbrd:{q}", lt.fetch_getonbrd, (q, country)) for q in cfg.getonbrd_queries]
        + ([("himalayas", lt.fetch_himalayas, (country,))] if cfg.himalayas else [])
        + ([("amazon", lt.fetch_amazon, (country,))] if cfg.amazon else [])
    )
    if cfg.adzuna_queries and adzuna_creds:
        tasks += [(f"adzuna:{q}", fetch_adzuna, (q, cfg.adzuna_country, *adzuna_creds)) for q in cfg.adzuna_queries]

    jobs: list[RawJob] = []
    report: dict[str, str | int] = {}
    if cfg.adzuna_queries and not adzuna_creds:
        report["adzuna"] = "sin credenciales (ADZUNA_APP_ID / ADZUNA_APP_KEY)"
    for name, fn, args in tasks:
        try:
            found = fn(client, *args)
            jobs.extend(found)
            report[name] = len(found)
        except SourceError as e:
            report[name] = f"error: {e}"
    return jobs, report


def page_text(client: httpx.Client, url: str, limit: int = 15_000) -> str:
    """Texto de la página pública de una oferta (para fuentes que no publican la descripción)."""
    try:
        r = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
    except httpx.HTTPError:
        return ""
    if "html" not in r.headers.get("content-type", "html"):
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return html_to_text(str(main))[:limit]
