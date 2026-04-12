"""
assembler.py
------------
Stage 3 — Resume Assembly Logic.

Takes the scored JSON from Person 2 and the full resume dict from Person 1,
then applies structural decision rules:

  1. Experience Selection  — cut entries with avg_relevance < EXPERIENCE_CUT_THRESHOLD
  2. Bullet Ordering       — sort bullets by semantic_score descending; keep ALL from
                             original resume (scoring used for ORDER, not hard filtering)
  3. Bullet Cap            — top entry gets up to 4 bullets, 2nd up to 3, 3rd up to 2, rest 1
  4. Section Ordering      — driven by section_weight
  5. Skills Curation       — use categorized skills from person1 if available;
                             JD-matched skills promoted to front of each category
  6. Extra Sections        — pass through publications, leadership, achievements
  7. Gap Report            — missing + partial_match skills with actionable notes

Public API:
    from person3_generation.assembler import assemble_resume
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

EXPERIENCE_CUT_THRESHOLD: float = 0.25  # avg_relevance below this → cut entry
BULLET_SCORE_THRESHOLD: float = 0.30  # used for ordering hint only; not hard filter

# Max bullets per experience rank (index 0 = most relevant entry)
BULLETS_BY_RANK: list[int] = [5, 4, 4, 4]  # keep all significant bullets per entry


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _build_bullet_score_lookup(scored_sections: dict) -> dict[str, float]:
    """Build a text → semantic_score lookup from all scored bullets."""
    lookup: dict[str, float] = {}
    for section in ["experience", "projects"]:
        for entry in scored_sections.get(section, []):
            for b in entry.get("bullets", []):
                if b.get("text"):
                    lookup[b["text"]] = b.get("semantic_score", 0.0)
    return lookup


def _get_original_bullets(
    entry_key: tuple[str, str],
    resume: dict | None,
    section: str,
) -> list[str] | None:
    """
    Look up the original (unfiltered) bullets from the full resume dict.
    Returns None if resume is not provided or entry not found.
    entry_key = (company, title) or (name,) for projects.
    """
    if not resume:
        return None
    orig_entries = resume.get("sections", {}).get(section, [])
    for e in orig_entries:
        if section == "experience":
            if (
                e.get("company", "").strip() == entry_key[0].strip()
                and e.get("title", "").strip() == entry_key[1].strip()
            ):
                return e.get("bullets", [])
        else:  # projects
            if e.get("name", "").strip() == entry_key[0].strip():
                return e.get("bullets", [])
    return None


def _select_and_trim_experiences(
    scored_experience: list[dict],
    resume: dict | None,
    bullet_lookup: dict[str, float],
) -> list[dict]:
    """
    1. Filter entries below EXPERIENCE_CUT_THRESHOLD (keep at least top-2 fallback).
    2. Sort survivors by avg_relevance descending.
    3. For each entry, use ALL original bullets ordered by semantic score.
       Apply a bullet cap by rank (4/3/2/1) — no hard score filter.
    """
    eligible = [
        e
        for e in scored_experience
        if e.get("avg_relevance", 0.0) >= EXPERIENCE_CUT_THRESHOLD
    ]

    if not eligible:
        eligible = sorted(
            scored_experience, key=lambda e: e.get("avg_relevance", 0.0), reverse=True
        )[:2]
        log.warning(
            "No experience entries passed threshold %.2f — using top-2 fallback",
            EXPERIENCE_CUT_THRESHOLD,
        )

    eligible.sort(key=lambda e: e.get("avg_relevance", 0.0), reverse=True)

    assembled: list[dict] = []
    for rank, entry in enumerate(eligible):
        max_bullets = BULLETS_BY_RANK[rank] if rank < len(BULLETS_BY_RANK) else 1

        # Prefer original (unfiltered) bullets from full resume
        orig_bullets = _get_original_bullets(
            (entry.get("company", ""), entry.get("title", "")),
            resume,
            "experience",
        )
        if orig_bullets:
            # Order by semantic score (best first), keep up to max_bullets
            ordered = sorted(
                orig_bullets,
                key=lambda b: bullet_lookup.get(b, 0.0),
                reverse=True,
            )
        else:
            # Fall back to scored bullets text
            sorted_scored = sorted(
                entry.get("bullets", []),
                key=lambda b: b.get("semantic_score", 0.0),
                reverse=True,
            )
            ordered = [b["text"] for b in sorted_scored]

        selected = ordered[:max_bullets] if ordered else []

        assembled_entry = {
            "company": entry.get("company", ""),
            "title": entry.get("title", ""),
            "dates": entry.get("dates", ""),
            "location": entry.get("location", ""),
            "bullets": selected,
            "avg_relevance": entry.get("avg_relevance", 0.0),
            "section_weight": entry.get("section_weight", 1.0),
        }
        assembled.append(assembled_entry)
        log.info(
            "Experience '%s' @ '%s': rank=%d, avg=%.3f, bullets=%d",
            entry.get("title", "?"),
            entry.get("company", "?"),
            rank,
            entry.get("avg_relevance", 0.0),
            len(selected),
        )

    return assembled


def _select_and_trim_projects(
    scored_projects: list[dict],
    resume: dict | None,
    bullet_lookup: dict[str, float],
    max_projects: int = 3,
) -> list[dict]:
    """Sort projects by avg_relevance, keep top max_projects with ALL original bullets."""
    sorted_projects = sorted(
        scored_projects,
        key=lambda p: p.get("avg_relevance", 0.0),
        reverse=True,
    )

    assembled: list[dict] = []
    for proj in sorted_projects[:max_projects]:
        orig_bullets = _get_original_bullets(
            (proj.get("name", ""),), resume, "projects"
        )
        if orig_bullets:
            ordered = sorted(
                orig_bullets,
                key=lambda b: bullet_lookup.get(b, 0.0),
                reverse=True,
            )
        else:
            sorted_scored = sorted(
                proj.get("bullets", []),
                key=lambda b: b.get("semantic_score", 0.0),
                reverse=True,
            )
            ordered = [b["text"] for b in sorted_scored]

        # Get original description from resume if available
        orig_desc = proj.get("description", "")
        if resume:
            for p in resume.get("sections", {}).get("projects", []):
                if p.get("name", "").strip() == proj.get("name", "").strip():
                    orig_desc = p.get("description", "") or orig_desc
                    break

        assembled.append(
            {
                "name": proj.get("name", ""),
                "description": orig_desc,
                "bullets": ordered,
                "avg_relevance": proj.get("avg_relevance", 0.0),
            }
        )

    return assembled


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

    Uses categorized structure from person1 if available.
    """
    covered_lower = {s.lower() for s in skills_analysis.get("covered", [])}
    missing_lower = {s.lower() for s in skills_analysis.get("missing", [])}

    # Build flat curated list (JD-matched first)
    jd_matched = [s for s in scored_skills if s.lower() in covered_lower]
    remaining = [s for s in scored_skills if s.lower() not in covered_lower]
    flat = jd_matched + remaining

    # Build categorized list preserving original groups
    curated_cats: list[dict] = []
    if skills_categorized:
        for cat in skills_categorized:
            skills_in_cat = cat.get("skills", [])
            # Promote JD-covered skills to front within each category
            matched = [s for s in skills_in_cat if s.lower() in covered_lower]
            rest = [s for s in skills_in_cat if s.lower() not in covered_lower]
            curated_cats.append(
                {
                    "category": cat["category"],
                    "skills": matched + rest,
                }
            )
    else:
        # No categories from person1 — wrap flat list
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
    Convert Person 2's scored JSON into an assembled resume dict for PDF generation.

    Args:
        scored_output: Output of person2_scoring.scorer.score_resume().
        jd:            Parsed JD dict from person1_parsing.jd_parser.parse_jd().
        resume:        Full resume dict from person1_parsing.resume_parser.parse_resume().
                       When provided, original bullets and extra sections are preserved.

    Returns dict with keys:
        contact, experience, projects, education, skills, extra_sections,
        gap_report, overall_scores, jd_meta
    """
    scored_sections = scored_output.get("scored_sections", {})
    skills_analysis = scored_output.get(
        "skills_analysis", {"covered": [], "missing": [], "partial_match": []}
    )

    bullet_lookup = _build_bullet_score_lookup(scored_sections)

    experience = _select_and_trim_experiences(
        scored_sections.get("experience", []), resume, bullet_lookup
    )
    projects = _select_and_trim_projects(
        scored_sections.get("projects", []), resume, bullet_lookup
    )
    education = scored_sections.get("education", [])

    # Enrich education with courses if available from full resume
    if resume:
        for edu_entry in education:
            for orig_edu in resume.get("sections", {}).get("education", []):
                if orig_edu.get("school", "")[:30] in edu_entry.get(
                    "school", ""
                ) or edu_entry.get("school", "")[:30] in orig_edu.get("school", ""):
                    if orig_edu.get("courses") and not edu_entry.get("courses"):
                        edu_entry["courses"] = orig_edu["courses"]
                    break

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
