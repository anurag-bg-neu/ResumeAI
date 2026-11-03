"""
scorer.py
---------
Stage 2 entry point. Takes the parsed resume + JD dicts from Stage 1 and
produces the scored dict that Stage 3 consumes to assemble the final resume.

Public API:
    from scoring.scorer import score_resume
"""

import logging

from .baseline_tfidf import compute_overall_keyword_score, score_with_tfidf
from .gap_analysis import analyze_skill_gaps
from .semantic_scorer import compute_overall_semantic_score, score_with_semantic

log = logging.getLogger(__name__)


def score_resume(resume, jd):
    """
    Full scoring pipeline. Takes parsed resume + jd dicts, returns the scored
    dict matching the Stage 2 -> Stage 3 contract.
    """

    log.info("Running TF-IDF baseline scoring")
    tfidf_bullets = score_with_tfidf(resume, jd)
    overall_keyword = compute_overall_keyword_score(tfidf_bullets)

    # build a quick lookup from bullet text -> keyword score so we can attach it later
    keyword_lookup = {b["text"]: b["keyword_score"] for b in tfidf_bullets}

    log.info("Running semantic scoring")
    scored_sections = score_with_semantic(resume, jd)
    overall_semantic = compute_overall_semantic_score(scored_sections)

    # attach the keyword score to each bullet in the semantic output
    # (semantic_scorer only adds semantic_score, so we merge both here)
    for section_name in ["experience", "projects"]:
        for entry in scored_sections.get(section_name, []):
            for bullet in entry.get("bullets", []):
                bullet["keyword_score"] = keyword_lookup.get(bullet["text"], 0.0)

    log.info("Running skill gap analysis")
    skills_analysis = analyze_skill_gaps(resume, jd)

    # assemble final output matching the JSON contract
    output = {
        "scored_sections": scored_sections,
        "skills_analysis": skills_analysis,
        "overall_semantic_score": overall_semantic,
        "overall_keyword_score": overall_keyword,
    }

    return output
