"""
ResumeAI API
------------
Thin FastAPI wrapper around the shared pipeline. All stage wiring lives in
pipeline.py; this module only handles HTTP concerns — upload validation,
concurrency, serialization, and error mapping.

Endpoints:
    POST /api/analyze       — upload resume PDF + JD text → scores + gap report JSON
    GET  /api/download/{id} — download the generated tailored resume PDF
    GET  /api/health        — health check

Run:
    cd backend
    python -m uvicorn api_app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("resumeai.api")

# ── Configuration ────────────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = int(os.getenv("RESUMEAI_MAX_UPLOAD_MB", "10")) * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
PDF_MAGIC = b"%PDF-"

# Generated PDFs live outside the source tree by default so the OS reaps them.
JOBS_DIR = Path(
    os.getenv("RESUMEAI_JOBS_DIR", Path(tempfile.gettempdir()) / "resumeai_jobs")
)
JOB_TTL_SECONDS = int(os.getenv("RESUMEAI_JOB_TTL_SECONDS", str(6 * 3600)))

# job_id is uuid4().hex[:12]; validate that shape rather than stripping characters.
_JOB_ID_RE = re.compile(r"\A[0-9a-f]{12}\Z")

# The pipeline is CPU-bound ML work. Starlette's threadpool defaults to 40
# threads; letting 40 torch inferences run at once would thrash the CPU until
# everything times out. Bound it so the rest queue cleanly.
_MAX_CONCURRENT = int(os.getenv("RESUMEAI_MAX_CONCURRENT", "2"))
_analysis_slots = asyncio.Semaphore(_MAX_CONCURRENT)

CORS_ORIGINS = os.getenv(
    "RESUMEAI_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ResumeAI API",
    version="1.0.0",
    description="Analyze resumes against job descriptions and generate tailored PDFs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _purge_stale_jobs() -> None:
    """Drop job directories older than the TTL. Best-effort, never fatal."""
    if not JOBS_DIR.exists():
        return
    cutoff = time.time() - JOB_TTL_SECONDS
    for entry in JOBS_DIR.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            log.debug("Could not purge %s", entry, exc_info=True)


@app.on_event("startup")
async def _on_startup() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _purge_stale_jobs()
    log.info("Jobs directory: %s (TTL %ds)", JOBS_DIR, JOB_TTL_SECONDS)


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    """
    Stream the upload to disk, enforcing the size cap as we go.

    Reading the whole body into memory first would let a large POST OOM the
    process before any limit could be applied, so the cap is checked per chunk.
    """
    total = 0
    header = b""
    with dest.open("wb") as fh:
        while chunk := await upload.read(_CHUNK_BYTES):
            if not header:
                header = chunk[: len(PDF_MAGIC)]
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Resume exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                )
            fh.write(chunk)

    if not header.startswith(PDF_MAGIC):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze(
    resume: UploadFile = File(..., description="Resume PDF file"),
    jd_text: str = Form(..., description="Raw job description text"),
):
    """
    Full pipeline: PDF + JD text → scored JSON + tailored PDF.

    Returns scores, skill gap analysis, and a job_id for PDF download.
    """
    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description text is required.")

    _purge_stale_jobs()

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "resume.pdf"

    try:
        await _save_upload(resume, pdf_path)

        # The pipeline is synchronous and CPU-bound for 10-30s. Running it
        # directly in this coroutine would pin the event loop, so /api/health
        # could not answer while any analysis was in flight.
        async with _analysis_slots:
            result = await run_in_threadpool(
                run_pipeline,
                pdf_path,
                jd_text,
                output_dir=job_dir,
                filename_stem="tailored_resume",
            )
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        # Log the real cause; return something that leaks neither stack nor paths.
        log.exception("[%s] Pipeline failed", job_id)
        raise HTTPException(
            status_code=500,
            detail="Analysis failed. Please try again or use a different PDF.",
        )

    scored = result.scored
    assembled = result.assembled

    log.info("[%s] Pipeline complete", job_id)

    return {
        "job_id": job_id,
        "scores": {
            "semantic": round(scored["overall_semantic_score"], 4),
            "keyword": round(scored["overall_keyword_score"], 4),
        },
        "skills_analysis": {
            "covered": scored["skills_analysis"].get("covered", []),
            "missing": scored["skills_analysis"].get("missing", []),
            "partial_match": scored["skills_analysis"].get("partial_match", []),
        },
        "gap_report": assembled.get("gap_report", {}),
        "contact": result.resume.get("contact", {}),
        "jd_meta": {
            "title": result.jd.get("title", ""),
            "company": result.jd.get("company", ""),
        },
        "experience_count": len(assembled.get("experience", [])),
        "project_count": len(assembled.get("projects", [])),
        "experience": [
            {
                "company": e.get("company", ""),
                "title": e.get("title", ""),
                "avg_relevance": round(e.get("avg_relevance", 0), 4),
                "bullet_count": len(e.get("bullets", [])),
            }
            for e in assembled.get("experience", [])
        ],
        "projects": [
            {
                "name": p.get("name", ""),
                "avg_relevance": round(p.get("avg_relevance", 0), 4),
            }
            for p in assembled.get("projects", [])
        ],
    }


@app.get("/api/download/{job_id}")
async def download_pdf(job_id: str):
    """Download the generated tailored resume PDF."""
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="PDF not found.")

    pdf_path = JOBS_DIR / job_id / "tailored_resume.pdf"
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404, detail="PDF not found. Run /api/analyze first."
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="tailored_resume.pdf",
    )
