"""
assembler.py
------------
Stage 3 — Resume Assembly Logic.

Takes the scored dict from Stage 2 (and, when available, the parsed resume
from Stage 1) and applies these rules:

  1. Experience      — every job is kept, in résumé order (dropping a real job
                       would leave an unexplained gap). Within each job,
                       bullets are ordered by semantic score, best first.
  2. Bullet Cap      — the most relevant job keeps up to BULLETS_BY_RANK[0]
                       bullets, the next ones BULLETS_BY_RANK[1..], the rest
                       MIN_BULLETS_PER_JOB.
  3. Projects        — the MAX_PROJECTS most relevant, bullets best first.
  4. Skills Curation — résumé categories kept; JD-covered skills promoted to
                       the front of each category.
  5. Extra Sections  — publications, leadership, achievements, certifications
                       passed through.
  6. Gap Report      — missing + partial_match skills with actionable notes.

Public API:
    from generation.assembler import assemble_resume, inject_missing_skills
"""

from __future__ import annotations

import logging

from parsing.utils import canonical_skill

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Max bullets per job by relevance rank (index 0 = most relevant job).
BULLETS_BY_RANK: list[int] = [5, 4, 4, 4]
MIN_BULLETS_PER_JOB: int = 2
MAX_PROJECTS: int = 3


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _bullets_best_first(entry: dict) -> list[str]:
    """Bullet texts of a scored entry, highest semantic score first."""
    ranked = sorted(
        entry.get("bullets", []),
        key=lambda b: b.get("semantic_score", 0.0),
        reverse=True,
    )
    return [b["text"] for b in ranked]


def _assemble_experience(scored_experience: list[dict]) -> list[dict]:
    """Keep every job in résumé order; cap and order bullets by relevance."""
    by_relevance = sorted(
        range(len(scored_experience)),
        key=lambda i: scored_experience[i].get("avg_relevance", 0.0),
        reverse=True,
    )
    rank_of = {idx: rank for rank, idx in enumerate(by_relevance)}

    assembled: list[dict] = []
    for idx, entry in enumerate(scored_experience):
        rank = rank_of[idx]
        cap = BULLETS_BY_RANK[rank] if rank < len(BULLETS_BY_RANK) else MIN_BULLETS_PER_JOB
        bullets = _bullets_best_first(entry)[:cap]
        assembled.append(
            {
                "company": entry.get("company", ""),
                "title": entry.get("title", ""),
                "dates": entry.get("dates", ""),
                "location": entry.get("location", ""),
                "bullets": bullets,
                "avg_relevance": entry.get("avg_relevance", 0.0),
            }
        )
        log.info(
            "Experience '%s' @ '%s': rank=%d, avg=%.3f, bullets=%d",
            entry.get("title", "?"),
            entry.get("company", "?"),
            rank,
            entry.get("avg_relevance", 0.0),
            len(bullets),
        )
    return assembled


def _assemble_projects(scored_projects: list[dict]) -> list[dict]:
    """The MAX_PROJECTS most relevant projects, bullets best first."""
    ranked = sorted(
        scored_projects,
        key=lambda p: p.get("avg_relevance", 0.0),
        reverse=True,
    )
    return [
        {
            "name": proj.get("name", ""),
            "description": proj.get("description", ""),
            "technologies": proj.get("technologies", []),
            "bullets": _bullets_best_first(proj),
            "avg_relevance": proj.get("avg_relevance", 0.0),
        }
        for proj in ranked[:MAX_PROJECTS]
    ]


def _curate_skills(
    scored_skills: list[str],
    skills_categorized: list[dict],
    skills_analysis: dict,
) -> dict:
    """
    Return curated skills in two forms:
      - "flat":        plain list (JD-matched first) — for fallback
      - "categorized": list of {category, skills} with JD-matched skills
                       promoted to front of each category

    Uses the résumé's own categories when the parser found them.
    """
    covered = {canonical_skill(s).lower() for s in skills_analysis.get("covered", [])}

    def _is_covered(skill: str) -> bool:
        # "AWS (EC2, S3)" counts as AWS
        return canonical_skill(skill.split(" (")[0]).lower() in covered

    # Build flat curated list (JD-matched first)
    jd_matched = [s for s in scored_skills if _is_covered(s)]
    remaining = [s for s in scored_skills if not _is_covered(s)]
    flat = jd_matched + remaining

    # Build categorized list preserving original groups
    curated_cats: list[dict] = []
    if skills_categorized:
        for cat in skills_categorized:
            skills_in_cat = cat.get("skills", [])
            # Promote JD-covered skills to front within each category
            matched = [s for s in skills_in_cat if _is_covered(s)]
            rest = [s for s in skills_in_cat if not _is_covered(s)]
            curated_cats.append(
                {
                    "category": cat["category"],
                    "skills": matched + rest,
                }
            )
    else:
        # No categories in the résumé — wrap the flat list
        curated_cats = [{"category": "Skills", "skills": flat}]

    return {"flat": flat, "categorized": curated_cats}


def _build_gap_report(skills_analysis: dict, jd: dict) -> dict:
    """Produce the actionable gap report."""
    missing = skills_analysis.get("missing", [])
    partial = skills_analysis.get("partial_match", [])

    lines: list[str] = []
    if missing:
        lines.append(
            f"Missing skills ({len(missing)}): add these to your resume if you have them: "
            + ", ".join(missing)
            + "."
        )
    if partial:
        lines.append(
            f"Partial matches ({len(partial)}): consider clearer wording for — "
            + "; ".join(f'"{p["jd_skill"]}"' for p in partial)
            + "."
        )
    if not missing and not partial:
        lines.append(
            "Your resume covers all detected required and preferred skills for this role."
        )

    return {
        "missing_skills": missing,
        "partial_matches": partial,
        "jd_title": jd.get("title", ""),
        "jd_company": jd.get("company", ""),
        "recommendation": " ".join(lines),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def assemble_resume(
    scored_output: dict,
    jd: dict,
    resume: dict | None = None,
) -> dict:
    """
    Convert Stage 2's scored dict into an assembled resume dict for PDF generation.

    Args:
        scored_output: Output of scoring.scorer.score_resume().
        jd:            Parsed JD dict from parsing.jd_parser.parse_jd().
        resume:        Full resume dict from parsing.resume_parser.parse_resume().
                       Supplies skill categories, extra sections and the full
                       contact block; without it those fall back to what the
                       scored dict carries.

    Returns dict with keys:
        contact, experience, projects, education, skills, extra_sections,
        gap_report, overall_scores, jd_meta
    """
    scored_sections = scored_output.get("scored_sections", {})
    skills_analysis = scored_output.get(
        "skills_analysis", {"covered": [], "missing": [], "partial_match": []}
    )

    experience = _assemble_experience(scored_sections.get("experience", []))
    projects = _assemble_projects(scored_sections.get("projects", []))
    education = scored_sections.get("education", [])

    # Skills: prefer categorized from full resume
    scored_skills = scored_sections.get("skills", [])
    skills_categorized = []
    if resume:
        skills_categorized = resume.get("sections", {}).get("skills_categorized", [])

    skills_result = _curate_skills(scored_skills, skills_categorized, skills_analysis)

    # Extra sections from full resume
    extra_sections: dict = {}
    if resume:
        extra_sections = resume.get("extra_sections", {})

    # Contact: prefer full resume contact (has linkedin/location)
    contact = scored_output.get("contact", {})
    if resume and resume.get("contact"):
        contact = resume["contact"]

    gap_report = _build_gap_report(skills_analysis, jd)

    assembled = {
        "contact": contact,
        "experience": experience,
        "projects": projects,
        "education": education,
        "skills": skills_result,
        "extra_sections": extra_sections,
        "gap_report": gap_report,
        "overall_scores": {
            "semantic": scored_output.get("overall_semantic_score", 0.0),
            "keyword": scored_output.get("overall_keyword_score", 0.0),
        },
        "jd_meta": {
            "title": jd.get("title", ""),
            "company": jd.get("company", ""),
        },
    }

    log.info(
        "Assembly complete: %d experiences, %d projects, %d skill categories; "
        "extra_sections=%s, missing=%d, partial=%d",
        len(experience),
        len(projects),
        len(skills_result["categorized"]),
        list(extra_sections.keys()),
        len(gap_report["missing_skills"]),
        len(gap_report["partial_matches"]),
    )

    return assembled


def inject_missing_skills(assembled: dict, gap_report: dict) -> list[str]:
    """
    Append the JD's missing skills to the assembled resume's skills section so
    they appear on the generated PDF, improving ATS keyword coverage.

    Mutates `assembled` in place. Skills already present are skipped
    (compared by canonical name, so "k8s" is not added next to "Kubernetes"),
    which also makes this idempotent.

    Returns the list of skills actually added, so callers can report it.
    """
    missing = gap_report.get("missing_skills", [])
    if not missing:
        return []

    # skills is normally {"flat": [...], "categorized": [...]}, but tolerate a
    # bare list from older callers.
    skills_data = assembled.get("skills", {})
    if isinstance(skills_data, dict):
        flat = skills_data.get("flat", [])
        cats = skills_data.get("categorized", [])
    else:
        flat = skills_data
        cats = [{"category": "Skills", "skills": list(skills_data)}]

    existing = {canonical_skill(s).lower() for s in flat}
    newly_added = [s for s in missing if canonical_skill(s).lower() not in existing]

    if not newly_added:
        log.info("No new skills to inject — all missing skills already present")
        return []

    # Append to the last category too, so they show up in the categorized layout
    # the PDF renders, not just the flat list.
    if cats:
        cats[-1]["skills"] = cats[-1]["skills"] + newly_added
    else:
        cats = [{"category": "Skills", "skills": list(newly_added)}]

    assembled["skills"] = {"flat": flat + newly_added, "categorized": cats}
    log.info("Injected %d missing skill(s): %s", len(newly_added), ", ".join(newly_added))
    return newly_added
