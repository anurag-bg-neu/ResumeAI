"""
pipeline.py
-----------
The single orchestrator for the three stages. Both the CLI and the web API
call through here, so the wiring lives in exactly one place.

This is library code: it logs, it never prints, and it only touches the
filesystem when a caller explicitly asks for a PDF.

    Stage 1  parse_resume() + parse_jd()   -> raw structured dicts
    Stage 2  score_resume()                -> TF-IDF + semantic + gap analysis
    Stage 3  assemble_resume()             -> tailored resume dict
             generate_resume_pdf()         -> PDF on disk (optional)

Public API:
    from pipeline import analyze, run_pipeline
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from generation.assembler import assemble_resume, inject_missing_skills
from generation.pdf_generator import generate_resume_pdf
from parsing.jd_parser import parse_jd
from parsing.resume_parser import parse_resume
from scoring.scorer import score_resume

log = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Stages 1-2. Everything parsed and scored; nothing assembled or written."""

    resume: dict
    jd: dict
    scored: dict


@dataclass
class PipelineResult(AnalysisResult):
    """Stages 1-3. Adds the assembled resume and, when requested, the PDF path."""

    assembled: dict
    injected_skills: list[str] = field(default_factory=list)
    pdf_path: str | None = None


def analyze(
    resume_pdf: str | Path,
    jd_text: str = "",
    *,
    jd: dict | None = None,
) -> AnalysisResult:
    """
    Run Stages 1 and 2.

    Args:
        resume_pdf: Path to the resume PDF.
        jd_text:    The job description as raw text. Deliberately NOT a path —
                    the API already holds text and the CLI reads the file, so
                    keeping path handling out of here is what lets both callers
                    share this function.
        jd:         An already-parsed JD dict (from parse_jd or a saved JSON).
                    When given, jd_text is ignored and JD parsing is skipped.
    """
    log.info("Stage 1 — parsing resume: %s", resume_pdf)
    resume = parse_resume(str(resume_pdf))
    log.info(
        "Parsed %d experiences, %d projects, %d skills",
        len(resume["sections"]["experience"]),
        len(resume["sections"]["projects"]),
        len(resume["all_skills_detected"]),
    )

    if jd is None:
        log.info("Stage 1 — parsing JD (%d chars)", len(jd_text))
        jd = parse_jd(jd_text)
    log.info("JD role: %s @ %s", jd.get("title", "?"), jd.get("company", "?"))

    log.info("Stage 2 — scoring resume against JD")
    scored = score_resume(resume, jd)

    # Keep contact details with the scores so a saved scored JSON is
    # self-contained (the CLI's --scored mode has no parsed resume).
    scored["contact"] = resume.get("contact", {})

    log.info(
        "Scored: semantic=%.4f keyword=%.4f",
        scored["overall_semantic_score"],
        scored["overall_keyword_score"],
    )
    return AnalysisResult(resume=resume, jd=jd, scored=scored)


def run_pipeline(
    resume_pdf: str | Path,
    jd_text: str = "",
    *,
    jd: dict | None = None,
    output_dir: str | Path | None = None,
    filename_stem: str = "tailored_resume",
    add_missing_skills: bool = False,
) -> PipelineResult:
    """
    Run all three stages.

    Args:
        jd_text, jd:        As for analyze().
        output_dir:         Where to write the PDF. None skips PDF generation
                            entirely, which is what makes this cheap to test.
        filename_stem:      PDF filename without the extension.
        add_missing_skills: Append the JD's missing skills to the skills section
                            before rendering, for ATS keyword coverage. Off by
                            default: it lists skills the candidate may not have,
                            so callers must opt in.
    """
    analysis = analyze(resume_pdf, jd_text, jd=jd)

    log.info("Stage 3 — assembling tailored resume")
    assembled = assemble_resume(analysis.scored, analysis.jd, resume=analysis.resume)

    injected: list[str] = []
    if add_missing_skills:
        injected = inject_missing_skills(assembled, assembled["gap_report"])

    pdf_path: str | None = None
    if output_dir is not None:
        log.info("Stage 3 — generating PDF in %s", output_dir)
        pdf_path = generate_resume_pdf(
            assembled,
            output_dir=str(output_dir),
            filename_stem=filename_stem,
        )
        log.info("PDF written: %s", pdf_path)

    return PipelineResult(
        resume=analysis.resume,
        jd=analysis.jd,
        scored=analysis.scored,
        assembled=assembled,
        injected_skills=injected,
        pdf_path=pdf_path,
    )
