"""
gap_analysis.py
---------------
Figures out which JD skills (required and preferred) the resume doesn't cover.

A skill is covered when the resume lists it — compared by canonical name, so
"React.js" covers "React" and "k8s" covers "Kubernetes". Otherwise we look for
the bullet that is semantically closest to the skill:
- Score at or above 0.6: the resume demonstrates it (covered)
- Score between 0.4 and 0.6: partial match — probably there, worded differently
- Score below 0.4: missing — the resume doesn't seem to mention this at all

Stage 3 uses the result to build the actionable gap report.
"""

from parsing.utils import canonical_skill, extract_skills

from .bullets import iter_bullets
from .embeddings import cos_sim, encode

# Similarity thresholds for classifying a JD skill against the resume.
COVERED_THRESHOLD: float = 0.6  # at or above -> the resume clearly covers it
PARTIAL_THRESHOLD: float = 0.4  # at or above -> probably there, worded differently


def _resume_skill_keys(resume: dict) -> set[str]:
    """Lowercased canonical names of every skill the resume evidences."""
    keys = set()
    for s in resume.get("all_skills_detected", []):
        keys.add(canonical_skill(s).lower())
        # Composite entries ("Linux/Unix Terminal") also cover their parts.
        keys.update(k.lower() for k in extract_skills(s))
    return keys


def analyze_skill_gaps(resume, jd):
    """
    Classify every JD skill (required + preferred) as covered, partial or missing.

    Returns a dict with:
      - covered:       skills the resume clearly addresses
      - missing:       skills not found anywhere in the resume
      - partial_match: [{jd_skill, closest_bullet, similarity, note}] for skills
                       that might be there but need better wording
    """
    requirements = jd["requirements"]
    skills = requirements.get("required_skills", []) + requirements.get("preferred_skills", [])
    if not skills:
        return {"covered": [], "missing": [], "partial_match": []}

    listed = _resume_skill_keys(resume)
    covered = [s for s in skills if canonical_skill(s).lower() in listed]
    unlisted = [s for s in skills if canonical_skill(s).lower() not in listed]

    bullet_texts = [text for _, _, _, text in iter_bullets(resume)]
    if not unlisted or not bullet_texts:
        return {"covered": covered, "missing": unlisted, "partial_match": []}

    # One batched pass instead of one forward pass per skill:
    # sims[i][j] = similarity of unlisted[i] to bullet_texts[j].
    sims = cos_sim(encode(unlisted), encode(bullet_texts))

    missing = []
    partial_match = []
    for i, skill in enumerate(unlisted):
        similarities = sims[i].tolist()
        best_score = max(similarities)

        if best_score >= COVERED_THRESHOLD:
            covered.append(skill)
        elif best_score >= PARTIAL_THRESHOLD:
            # they probably have this experience, just described it differently
            partial_match.append({
                "jd_skill": skill,
                "closest_bullet": bullet_texts[similarities.index(best_score)],
                "similarity": round(best_score, 4),
                "note": "Consider rewording your resume to match this skill more clearly",
            })
        else:
            missing.append(skill)

    return {"covered": covered, "missing": missing, "partial_match": partial_match}
