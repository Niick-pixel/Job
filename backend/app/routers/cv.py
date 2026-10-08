from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from ..config import JOBTRACKER_HOME, get_settings
from ..database import get_session
from ..models import CVProfile
from ..services.cv_parser import CVParseError, analyze_cv, extract_text
from ..services.llm import LLMClient, LLMError, get_llm

router = APIRouter(prefix="/api/cv", tags=["CV"])
MAX_CV_BYTES = 10 * 1024 * 1024


@router.post("", response_model=CVProfile)
async def upload_cv(
    background: BackgroundTasks,
    file: UploadFile = File(...), db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm),
):
    content = await file.read()
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(413, "El CV supera 10 MB")
    try:
        text = extract_text(file.filename or "cv", content)
    except CVParseError as e:
        raise HTTPException(422, str(e)) from e
    try:
        extraction = analyze_cv(llm, text)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e

    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    cv = CVProfile(
        filename=file.filename or "cv",
        raw_text=text,
        full_name=extraction.full_name,
        headline=extraction.headline,
        years_experience=extraction.years_experience,
        profile=extraction.model_dump(mode="json"),
    )
    db.add(cv)
    db.commit()
    db.refresh(cv)
    (settings.upload_dir / f"cv_{cv.id}_{cv.filename}").write_bytes(content)
    if JOBTRACKER_HOME:  # app instalada: primera búsqueda en cuanto hay CV, sin esperar a las 3 h
        from .agent import _run_in_background

        background.add_task(_run_in_background, llm)
    return cv


@router.get("", response_model=list[CVProfile])
def list_cvs(db: Session = Depends(get_session)):
    return db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).all()


@router.get("/{cv_id}", response_model=CVProfile)
def get_cv(cv_id: int, db: Session = Depends(get_session)):
    cv = db.get(CVProfile, cv_id)
    if not cv:
        raise HTTPException(404, "CV no encontrado")
    return cv
