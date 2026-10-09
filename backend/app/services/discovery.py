"""Descubrir en qué plataforma de empleo publica cada empresa y con qué identificador.

Por nombre se prueban Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Breezy y Workable. Workday
(muy usado por multinacionales en Costa Rica) no se puede adivinar: se detecta pegando la URL de la web
de empleo (empresa.wd1.myworkdayjobs.com/Sitio).

El usuario escribe nombres («Glovo, La Fourche») o pega la URL de su página de empleo. Para cada
nombre se prueban unas pocas variantes de identificador contra las APIs públicas, en paralelo.
Los resultados se muestran con nº de ofertas y títulos de ejemplo para que el usuario confirme:
un identificador como «nova» podría pertenecer a otra empresa.
"""
from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import httpx

from .sources import USER_AGENT

MAX_COMPANIES = 15
_LEGAL = re.compile(r"\b(inc|llc|ltd|gmbh|s\.?l\.?u?|s\.?a\.?|corp|corporation|co|group|holding|technologies)\b\.?")

URL_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
    ("breezy", re.compile(r"([\w-]+)\.breezy\.hr", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
]
WORKDAY = re.compile(r"(https?://[\w-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[\w-]+)", re.I)

CAREERS_URL = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{slug}",
    "recruitee": "https://{slug}.recruitee.com",
    "breezy": "https://{slug}.breezy.hr",
    "workable": "https://apply.workable.com/{slug}",
    "workday": "{slug}",
}
BY_NAME = ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "breezy", "workable")


@dataclass
class Board:
    query: str
    provider: str
    slug: str
    jobs: int
    sample: list[str] = field(default_factory=list)
    url: str = ""


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    s = _LEGAL.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug_variants(name: str) -> list[str]:
    words = _norm(name).split()
    if not words:
        return []
    joined, hyphen = "".join(words), "-".join(words)
    candidates = [joined, hyphen, f"{joined}app", f"{joined}hq", f"{joined}inc"]
    if len(words) > 1:
        candidates.append(words[0])
    seen, out = set(), []
    for c in candidates:
        if len(c) >= 2 and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:6]


def parse_url(text: str) -> tuple[str, str] | None:
    if m := WORKDAY.search(text):
        return "workday", m.group(1)
    for provider, pattern in URL_PATTERNS:
        m = pattern.search(text)
        if m:
            slug = m.group(1).lower()
            if provider in ("recruitee", "breezy") and slug in ("www", "app", "api", "careers", "jobs"):
                continue
            return provider, slug
    return None


def _get(client: httpx.Client, url: str, **params):
    try:
        r = client.get(url, params=params or None, headers={"User-Agent": USER_AGENT}, timeout=8)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def probe(client: httpx.Client, provider: str, slug: str) -> tuple[int, list[str]] | None:
    """Devuelve (nº de ofertas, títulos de ejemplo) si existe el tablero, o None."""
    if provider == "greenhouse":
        data = _get(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if not isinstance(data, dict) or "jobs" not in data:
            return None
        jobs = data["jobs"]
        return len(jobs), [j.get("title", "") for j in jobs[:3]]
    if provider == "lever":
        data = _get(client, f"https://api.lever.co/v0/postings/{slug}", mode="json")
        if not isinstance(data, list):
            return None
        return len(data), [j.get("text", "") for j in data[:3]]
    if provider == "smartrecruiters":
        data = _get(client, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", limit=3)
        jobs = data.get("content") if isinstance(data, dict) else None
        if not jobs:  # responde 200 vacío para cualquier nombre: solo cuenta si hay ofertas
            return None
        return data.get("totalFound", len(jobs)), [j.get("name", "") for j in jobs[:3]]
    if provider == "recruitee":
        data = _get(client, f"https://{slug}.recruitee.com/api/offers/")
        if not isinstance(data, dict) or "offers" not in data:
            return None
        return len(data["offers"]), [o.get("title", "") for o in data["offers"][:3]]
    if provider == "breezy":
        data = _get(client, f"https://{slug}.breezy.hr/json")
        if not isinstance(data, list):
            return None
        return len(data), [p.get("name", "") for p in data[:3]]
    if provider == "workable":
        data = _get(client, f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
        if not isinstance(data, dict) or "jobs" not in data:
            return None
        return len(data["jobs"]), [j.get("title", "") for j in data["jobs"][:3]]
    if provider == "workday":
        from .sources_latam import parse_workday

        parsed = parse_workday(slug)
        if not parsed:
            return None
        tenant, wd, site = parsed
        try:
            r = client.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                            json={"appliedFacets": {}, "limit": 3, "offset": 0, "searchText": ""},
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=10)
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            data = None
        if not isinstance(data, dict) or "jobPostings" not in data:
            return None
        return data.get("total", 0), [j.get("title", "") for j in data["jobPostings"][:3]]
    if provider == "ashby":
        data = _get(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        # Ashby podría responder 200 con lista vacía para cualquier nombre: solo cuenta si hay ofertas
        if not jobs:
            return None
        return len(jobs), [j.get("title", "") for j in jobs[:3]]
    return None


def discover(client: httpx.Client, queries: list[str]) -> list[dict]:
    """Prueba todas las combinaciones en paralelo. Devuelve tableros encontrados (más ofertas primero)."""
    tasks: list[tuple[str, str, str]] = []
    for q in [q.strip() for q in queries if q.strip()][:MAX_COMPANIES]:
        direct = parse_url(q)
        if direct:
            tasks.append((q, *direct))
            continue
        for i, slug in enumerate(slug_variants(q)):
            # Las plataformas nuevas solo con las variantes más probables (menos peticiones)
            for provider in (BY_NAME if i < 2 else BY_NAME[:3]):
                tasks.append((q, provider, slug))

    def run(task):
        query, provider, slug = task
        found = probe(client, provider, slug)
        if found is None:
            return None
        n, sample = found
        return Board(query, provider, slug, n, [s for s in sample if s], CAREERS_URL[provider].format(slug=slug))

    with ThreadPoolExecutor(max_workers=8) as pool:
        boards = [b for b in pool.map(run, tasks) if b]

    # Una misma empresa puede aparecer con varias variantes del mismo tablero: quedarse con la mejor
    best: dict[tuple[str, str, str], Board] = {}
    for b in boards:
        key = (b.query, b.provider, b.slug)
        best.setdefault(key, b)
    ordered = sorted(best.values(), key=lambda b: (b.query.lower(), -b.jobs))
    return [asdict(b) for b in ordered]
