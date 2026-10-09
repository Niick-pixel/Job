"""Fuentes pensadas para Costa Rica y Latinoamérica.

- Workday: el portal de empleo de muchas multinacionales con sede en Costa Rica (Intel, P&G, Boston
  Scientific…). Se usa el JSON público que carga la propia web de empleo de cada empresa
  (empresa.wd1.myworkdayjobs.com/Sitio). Hay que pegar la URL de su página de empleo.
- SmartRecruiters: API pública de ofertas por empresa, con filtro por país.
- Get on Board: el portal tecnológico de referencia en Latinoamérica (API pública).
- Himalayas: ofertas remotas; solo se quedan las abiertas a tu país o a Latinoamérica.
- Amazon: su buscador de empleo filtrado por país (Amazon tiene una gran sede en Costa Rica).
- Recruitee, Breezy y Workable: ATS de muchas startups latinoamericanas (JSON público por empresa).

Todas son consultas de lectura a datos públicos, como hace un navegador; con pausas y pocas peticiones.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import httpx

from .region import country_info, mentions_country
from .sources import USER_AGENT, RawJob, SourceError, _date, _get_json, _is_remote, html_to_text

MAX_DETAILS = 25  # descripciones completas por empresa y pasada (cada una es una petición)


def _post_json(client: httpx.Client, url: str, body: dict):
    try:
        r = client.post(url, json=body, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SourceError(f"{url}: {e}") from e


def _epoch_date(value) -> date | None:
    """Fechas en segundos desde 1970 (Get on Board, Himalayas); si es en ms, también."""
    if not isinstance(value, (int, float)):
        return _date(value)
    seconds = value / 1000 if value > 10_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


def _wanted(location: str | None, remote: bool | None, country: str | None) -> bool:
    """Para fuentes globales: ¿la oferta es en tu país o remota abierta a ti?"""
    if not country:
        return True
    return mentions_country(location, country) or bool(remote)


# ── Workday ─────────────────────────────────────────────────────

WORKDAY_URL = re.compile(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)


def parse_workday(url: str) -> tuple[str, str, str] | None:
    m = WORKDAY_URL.search(url or "")
    return (m.group(1).lower(), m.group(2).lower(), m.group(3)) if m else None


def _workday_posted(text: str | None, today: date) -> date | None:
    t = (text or "").lower()
    if "today" in t or "hoy" in t:
        return today
    if "yesterday" in t or "ayer" in t:
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(?:days?|días?)", t)
    return today - timedelta(days=int(m.group(1))) if m else None


def fetch_workday(client: httpx.Client, url: str, country: str | None = None, today: date | None = None) -> list[RawJob]:
    parsed = parse_workday(url)
    if not parsed:
        raise SourceError(f"{url}: no parece una web de empleo de Workday (empresa.wd1.myworkdayjobs.com/Sitio)")
    tenant, wd, site = parsed
    host = f"{tenant}.{wd}.myworkdayjobs.com"
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    today = today or date.today()
    search = (country_info(country) or {}).get("name", "") if country else ""
    postings = []
    for offset in (0, 20, 40):  # Workday devuelve 20 por página
        data = _post_json(client, f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search})
        page = data.get("jobPostings") or []
        postings += page
        if len(page) < 20 or len(postings) >= (data.get("total") or 0):
            break
    jobs = []
    for p in postings:
        path = p.get("externalPath") or ""
        loc = p.get("locationsText") or ""
        remote = _is_remote(loc, p.get("remoteType"))
        if not path or (country and not _wanted(loc, remote, country) and "locations" not in loc.lower()):
            continue
        desc, company, posted = "", tenant.capitalize(), _workday_posted(p.get("postedOn"), today)
        if len(jobs) < MAX_DETAILS:
            try:
                info = (_get_json(client, f"{api}{path}") or {}).get("jobPostingInfo") or {}
                desc = html_to_text(info.get("jobDescription"))
                loc = info.get("location") or loc
                posted = _date(info.get("startDate")) or posted
                company = ((info.get("hiringOrganization") or {}).get("name")) or company
            except SourceError:
                pass
        jobs.append(RawJob(
            source="workday", external_id=f"workday:{tenant}:{(p.get('bulletFields') or [path])[0]}",
            title=(p.get("title") or "").strip(), company=company, location=loc,
            url=f"https://{host}/en-US/{site}{path}", apply_url=f"https://{host}/en-US/{site}{path}/apply",
            description=desc or f"{p.get('title', '')} · {loc}", posted_date=posted, remote=remote,
            extra={"partial": not desc},
        ))
    return jobs


# ── SmartRecruiters ─────────────────────────────────────────────


def fetch_smartrecruiters(client: httpx.Client, company: str, country: str | None = None) -> list[RawJob]:
    base = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    params = {"limit": 100}
    if country:
        params["country"] = country.lower()
    data = _get_json(client, base, **params)
    jobs = []
    for p in data.get("content") or []:
        loc_d = p.get("location") or {}
        loc = loc_d.get("fullLocation") or ", ".join(x for x in (loc_d.get("city"), (loc_d.get("country") or "").upper()) if x)
        desc = ""
        if len(jobs) < MAX_DETAILS:
            try:
                ad = ((_get_json(client, f"{base}/{p['id']}") or {}).get("jobAd") or {}).get("sections") or {}
                desc = "\n\n".join(html_to_text((ad.get(k) or {}).get("text"))
                                   for k in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))
            except SourceError:
                pass
        ident = (p.get("company") or {}).get("identifier") or company
        url = f"https://jobs.smartrecruiters.com/{ident}/{p['id']}"
        jobs.append(RawJob(
            source="smartrecruiters", external_id=f"smartrecruiters:{company}:{p['id']}",
            title=(p.get("name") or "").strip(), company=(p.get("company") or {}).get("name") or company,
            location=loc, url=url, apply_url=url, description=desc.strip() or p.get("name", ""),
            posted_date=_date(p.get("releasedDate")), remote=True if loc_d.get("remote") else _is_remote(loc),
            extra={"partial": not desc.strip()},
        ))
    return jobs


# ── Get on Board ────────────────────────────────────────────────


def fetch_getonbrd(client: httpx.Client, query: str, country: str | None = None) -> list[RawJob]:
    data = _get_json(client, "https://www.getonbrd.com/api/v0/search/jobs", query=query, per_page=50,
                     expand='["company"]')
    jobs = []
    for item in data.get("data") or []:
        a = item.get("attributes") or {}
        countries = a.get("countries") or []
        if isinstance(countries, str):
            countries = [countries]
        modality = a.get("remote_modality") or ""
        remote = bool(a.get("remote")) or modality in ("fully_remote", "remote_local")
        loc = ", ".join(countries) or ("Remoto" if remote else None)
        if remote and modality == "remote_local" and country and countries and not mentions_country(loc, country):
            continue  # remoto pero solo para residentes de otro país
        if not remote and country and not mentions_country(loc, country):
            continue
        company = (((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name")
        smin, smax = a.get("min_salary"), a.get("max_salary")
        url = (item.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{item.get('id')}"
        parts = [a.get("description"), a.get("projects"), a.get("functions"), a.get("benefits"), a.get("requirements")]
        jobs.append(RawJob(
            source="getonbrd", external_id=f"getonbrd:{item.get('id')}", title=(a.get("title") or "").strip(),
            company=company, location=loc, url=url, apply_url=url,
            description="\n\n".join(html_to_text(p) for p in parts if p).strip(),
            posted_date=_epoch_date(a.get("published_at")), remote=remote,
            salary_text=f"{smin}-{smax} USD/mes" if smin and smax else None,
            salary_min=smin * 12 if smin else None, salary_max=smax * 12 if smax else None,
        ))
    return jobs


# ── Himalayas (remoto) ──────────────────────────────────────────


def fetch_himalayas(client: httpx.Client, country: str | None = None) -> list[RawJob]:
    data = _get_json(client, "https://himalayas.app/jobs/api", limit=100)
    name = (country_info(country) or {}).get("name")
    jobs = []
    for j in data.get("jobs") or []:
        restrictions = j.get("locationRestrictions") or []
        loc = ", ".join(restrictions) if restrictions else "Remoto (cualquier país)"
        open_to_me = mentions_country(loc, country) or re.search(r"latin|latam|americas", loc, re.I)
        if restrictions and country and not open_to_me:
            continue  # remoto, pero solo para otros países
        smin, smax = j.get("minSalary"), j.get("maxSalary")
        jobs.append(RawJob(
            source="himalayas", external_id=f"himalayas:{j.get('guid') or j.get('applicationLink')}",
            title=(j.get("title") or "").strip(), company=j.get("companyName"), location=loc,
            url=j.get("applicationLink") or j.get("guid"), apply_url=j.get("applicationLink"),
            description=html_to_text(j.get("description")) or j.get("excerpt") or "",
            posted_date=_epoch_date(j.get("pubDate")), remote=True,
            salary_text=f"{smin}-{smax} {j.get('currency') or 'USD'}" if smin and smax else None,
            extra={"open_to": name or "global"},
        ))
    return jobs


# ── Amazon ──────────────────────────────────────────────────────


def fetch_amazon(client: httpx.Client, country: str | None, query: str = "") -> list[RawJob]:
    info = country_info(country)
    if not info:
        raise SourceError("Amazon: indica tu país en Agente para buscar allí")
    data = _get_json(client, "https://www.amazon.jobs/en/search.json", country=info["iso3"], result_limit=100,
                     sort="recent", base_query=query)
    jobs = []
    for j in data.get("jobs") or []:
        parts = [j.get("description"), "Requisitos básicos:\n" + (j.get("basic_qualifications") or ""),
                 "Valorable:\n" + (j.get("preferred_qualifications") or "")]
        url = f"https://www.amazon.jobs{j.get('job_path')}" if j.get("job_path") else None
        jobs.append(RawJob(
            source="amazon", external_id=f"amazon:{j.get('id_icims') or j.get('id')}", title=(j.get("title") or "").strip(),
            company=j.get("company_name") or "Amazon", location=j.get("normalized_location") or j.get("location"),
            url=url, apply_url=url, description="\n\n".join(html_to_text(p) for p in parts if p).strip(),
            posted_date=_date(j.get("posted_date")), remote=_is_remote(j.get("location")),
        ))
    return jobs


# ── Recruitee, Breezy, Workable ────────────────────────────────


def fetch_recruitee(client: httpx.Client, company: str, country: str | None = None) -> list[RawJob]:
    data = _get_json(client, f"https://{company}.recruitee.com/api/offers/")
    jobs = []
    for o in data.get("offers") or []:
        loc = o.get("location") or ", ".join(x for x in (o.get("city"), o.get("country")) if x)
        remote = bool(o.get("remote")) or _is_remote(loc)
        if not _wanted(loc, remote, country):
            continue
        jobs.append(RawJob(
            source="recruitee", external_id=f"recruitee:{company}:{o.get('id')}", title=(o.get("title") or "").strip(),
            company=o.get("company_name") or company, location=loc, url=o.get("careers_url"),
            apply_url=o.get("careers_apply_url") or o.get("careers_url"),
            description=(html_to_text(o.get("description")) + "\n\n" + html_to_text(o.get("requirements"))).strip(),
            posted_date=_date(o.get("published_at") or o.get("created_at")), remote=remote,
        ))
    return jobs


def fetch_breezy(client: httpx.Client, company: str, country: str | None = None) -> list[RawJob]:
    data = _get_json(client, f"https://{company}.breezy.hr/json")
    jobs = []
    for p in data if isinstance(data, list) else []:
        loc_d = p.get("location") or {}
        loc = loc_d.get("name") or ", ".join(x for x in (loc_d.get("city"), (loc_d.get("country") or {}).get("name")) if x)
        remote = bool(loc_d.get("is_remote")) or _is_remote(loc)
        if not _wanted(loc, remote, country):
            continue
        extra = [p.get("department"), (p.get("type") or {}).get("name"), p.get("salary")]
        jobs.append(RawJob(
            source="breezy", external_id=f"breezy:{company}:{p.get('id')}", title=(p.get("name") or "").strip(),
            company=(p.get("company") or {}).get("name") or company, location=loc, url=p.get("url"), apply_url=p.get("url"),
            description=" · ".join(x for x in extra if x) or (p.get("name") or ""),
            posted_date=_date(p.get("published_date")), remote=remote, salary_text=p.get("salary") or None,
            extra={"partial": True},  # Breezy no publica la descripción en su JSON: se completa al analizar
        ))
    return jobs


def fetch_workable(client: httpx.Client, account: str, country: str | None = None) -> list[RawJob]:
    data = _get_json(client, f"https://apply.workable.com/api/v1/widget/accounts/{account}", details="true")
    jobs = []
    for j in data.get("jobs") or []:
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        remote = bool(j.get("telecommuting")) or _is_remote(loc)
        if not _wanted(loc, remote, country):
            continue
        jobs.append(RawJob(
            source="workable", external_id=f"workable:{account}:{j.get('shortcode')}", title=(j.get("title") or "").strip(),
            company=data.get("name") or account, location=loc, url=j.get("url") or j.get("shortlink"),
            apply_url=j.get("application_url") or j.get("url"), description=html_to_text(j.get("description")),
            posted_date=_date(j.get("published_on") or j.get("created_at")), remote=remote,
        ))
    return jobs
