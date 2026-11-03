"""
ResumeAI API
------------
Thin FastAPI wrapper around the existing 3-stage pipeline.
Zero modifications to person1_parsing, person2_scoring, or person3_generation.

Endpoints:
    POST /api/analyze      — upload resume PDF + JD text → scores + gap report JSON
    GET  /api/download/{id} — download the generated tailored resume PDF
    GET  /api/health        — health check

Run:
    cd ResumeAI
    python -m uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# ── Make the repo root importable ────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from person1_parsing.jd_parser import parse_jd  # noqa: E402
from person1_parsing.resume_parser import parse_resume  # noqa: E402
from person2_scoring.scorer import score_resume  # noqa: E402
from person3_generation.assembler import assemble_resume  # noqa: E402
from person3_generation.latex_generator import generate_resume_pdf  # noqa: E402
from generate_resume import _inject_missing_skills

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("resumeai.api")

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ResumeAI API",
    version="1.0.0",
    description="Analyze resumes against job descriptions and generate tailored PDFs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory to store generated PDFs per job
JOBS_DIR = ROOT / "_jobs"
JOBS_DIR.mkdir(exist_ok=True)


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
    # Validate file type
    if not resume.filename or not resume.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description text is required.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded PDF to job directory
    pdf_path = job_dir / "resume.pdf"
    try:
        content = await resume.read()
        pdf_path.write_bytes(content)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to read uploaded file: {exc}"
        )

    try:
        # ── Stage 1: Parse ───────────────────────────────────────────────
        log.info("[%s] Stage 1 — Parsing resume + JD", job_id)
        resume_data = parse_resume(str(pdf_path))
        jd_data = parse_jd(jd_text)

        # ── Stage 2: Score ───────────────────────────────────────────────
        log.info("[%s] Stage 2 — Scoring (TF-IDF + semantic + gap analysis)", job_id)
        scored = score_resume(resume_data, jd_data)

        # Attach contact so assembler can pass it through
        scored["contact"] = resume_data.get("contact", {})

        # ── Stage 3: Assemble + Generate PDF ─────────────────────────────
        log.info("[%s] Stage 3 — Assembling + generating PDF", job_id)
        assembled = assemble_resume(scored, jd_data, resume=resume_data)
        assembled = _inject_missing_skills(assembled, assembled["gap_report"])

        generate_resume_pdf(
            assembled,
            output_dir=str(job_dir),
            filename_stem="tailored_resume",
        )

        log.info("[%s] Pipeline complete", job_id)

        # ── Build response ───────────────────────────────────────────────
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
            "contact": resume_data.get("contact", {}),
            "jd_meta": {
                "title": jd_data.get("title", ""),
                "company": jd_data.get("company", ""),
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

    except Exception as exc:
        log.exception("[%s] Pipeline failed", job_id)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")


@app.get("/api/download/{job_id}")
async def download_pdf(job_id: str):
    """Download the generated tailored resume PDF."""
    # Sanitize job_id to prevent path traversal
    safe_id = "".join(c for c in job_id if c.isalnum())
    pdf_path = JOBS_DIR / safe_id / "tailored_resume.pdf"

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404, detail="PDF not found. Run /api/analyze first."
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="tailored_resume.pdf",
    )
