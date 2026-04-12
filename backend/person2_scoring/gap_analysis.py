"""
gap_analysis.py
---------------
Figures out which skills the JD requires that the resume doesn't cover well.

We check each required skill against every bullet in the resume semantically.
- Score above 0.6: the resume covers this skill (covered)
- Score between 0.4 and 0.6: partial match — the person probably has it but worded it differently
- Score below 0.4: missing — the resume doesn't seem to mention this at all

These thresholds come from the project plan. Person 3 uses the gap report to
generate the actionable feedback section of the output.
"""

import json
from sentence_transformers import SentenceTransformer, util


model = SentenceTransformer("all-MiniLM-L6-v2")


def get_all_bullet_texts(resume):
    """Flatten every bullet from experience and projects into one list."""
    all_bullets = []

    for exp in resume["sections"].get("experience", []):
        all_bullets.extend(exp.get("bullets", []))

    for proj in resume["sections"].get("projects", []):
        all_bullets.extend(proj.get("bullets", []))

    return all_bullets


def analyze_skill_gaps(resume, jd):
    """
    For each required skill in the JD, find the best-matching bullet in the resume.
    Classify as covered, partial, or missing based on the similarity score.

    Returns a dict with:
      - covered: skills the resume clearly addresses
      - missing: skills not found anywhere in the resume
      - partial_match: skills that might be there but need better wording
    """

    required_skills = jd["requirements"].get("required_skills", [])
    preferred_skills = jd["requirements"].get("preferred_skills", [])

    all_bullet_texts = get_all_bullet_texts(resume)
    resume_skills = resume.get("all_skills_detected", [])

    if not all_bullet_texts:
        return {"covered": [], "missing": required_skills, "partial_match": []}

    # encode all bullets once
    bullet_embeddings = model.encode(all_bullet_texts, convert_to_tensor=True)

    covered = []
    missing = []
    partial_match = []

    # check required skills first (these are the ones that matter most)
    for skill in required_skills + preferred_skills:
        skill_embedding = model.encode(skill, convert_to_tensor=True)

        # compare this skill against every bullet
        similarities = util.cos_sim(skill_embedding, bullet_embeddings)[0].tolist()

        best_score = max(similarities)
        best_bullet_idx = similarities.index(best_score)
        best_bullet = all_bullet_texts[best_bullet_idx]

        # Alias-aware coverage check:
        # "Apache Kafka" is covered if "Kafka" is in resume skills (and vice versa).
        # Any shared token between the JD skill and a resume skill counts as a match.
        skill_tokens = set(skill.lower().split())
        in_skills_section = any(
            skill.lower() in s.lower()                      # "Kafka" in "Apache Kafka"
            or s.lower() in skill.lower()                   # "Apache Kafka" contains "Kafka"
            or bool(skill_tokens & set(s.lower().split()))  # shared token: "kafka" in both
            for s in resume_skills
        )

        if best_score >= 0.6 or in_skills_section:
            covered.append(skill)
        elif best_score >= 0.4:
            # they probably have this experience, just described it differently
            partial_match.append({
                "jd_skill": skill,
                "closest_bullet": best_bullet,
                "similarity": round(best_score, 4),
                "note": "Consider rewording your resume to match this skill more clearly"
            })
        else:
            missing.append(skill)

    return {
        "covered": covered,
        "missing": missing,
        "partial_match": partial_match
    }


if __name__ == "__main__":
    with open("../data/mock_data/sample_resume.json") as f:
        resume = json.load(f)
    with open("../data/mock_data/sample_jd.json") as f:
        jd = json.load(f)

    print("Running gap analysis...")
    gaps = analyze_skill_gaps(resume, jd)

    print(f"\nCovered skills: {gaps['covered']}")
    print(f"Missing skills: {gaps['missing']}")
    print(f"\nPartial matches (consider rewording):")
    for p in gaps["partial_match"]:
        print(f"  JD wants: '{p['jd_skill']}' (score: {p['similarity']})")
        print(f"  Closest bullet: '{p['closest_bullet'][:80]}'")