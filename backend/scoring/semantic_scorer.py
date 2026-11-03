"""
semantic_scorer.py
------------------
This is the "smart" model. Instead of matching words, it converts every bullet and
requirement into a 384-dimensional embedding vector that captures *meaning*.

So "built REST APIs" and "developed backend services" will score high similarity even
though they don't share many words — the embeddings know they mean similar things.

We use the all-MiniLM-L6-v2 model from sentence-transformers. It's small and fast,
which matters when we're scoring 40+ bullets against 8+ requirements.

We also do section weighting: experience bullets count more than education bullets
because the JD is for a software engineering role (not a research or academic position).
"""

from .embeddings import cos_sim, encode

# Below this similarity, a "best match" is noise rather than a real match, so we
# report no matching requirement at all.
MATCH_FLOOR: float = 0.1


def get_section_weight(jd):
    """
    Decide how much each resume section should count for this specific JD.

    The logic: look at whether the JD seems more experience-focused or research/project-focused.
    If it mentions years of experience heavily, weight experience higher.
    If it seems more academic or project-driven, weight projects higher.

    For most software engineering JDs, experience is the most important section.
    """
    req_text = " ".join([r["text"] for r in jd["requirements"]["requirement_sentences"]]).lower()

    weights = {
        "experience": 1.5,  # default: experience matters most for eng roles
        "projects": 1.0,
        "education": 0.5,   # education bullets are usually not very relevant
    }

    # if the JD specifically calls out research, publications, or academic projects, boost projects
    if any(word in req_text for word in ["research", "publication", "academic", "thesis"]):
        weights["projects"] = 1.5
        weights["experience"] = 1.0

    return weights


def score_with_semantic(resume, jd):
    """
    Score every bullet semantically against the JD requirements.

    Steps:
    1. Collect all bullets (with section labels)
    2. Collect all JD requirement sentences
    3. Encode everything into vectors
    4. For each bullet, find which requirement it matches best and what the score is
    5. Apply section weight to get a final weighted score
    """

    requirements = jd["requirements"]["requirement_sentences"]
    req_texts = [r["text"] for r in requirements]
    section_weights = get_section_weight(jd)

    scored_sections = {
        "experience": [],
        "projects": [],
        "education": []
    }

    # ── Flatten ──────────────────────────────────────────────────────────────
    # Collect every bullet into one list, remembering where each came from, so
    # the whole resume can be encoded in a single batched forward pass instead
    # of one pass per bullet.
    flat_bullets: list[str] = []
    origins: list[tuple[str, int, int]] = []  # (section_name, entry_idx, bullet_idx)

    for section_name in ("experience", "projects"):
        for entry_idx, item in enumerate(resume["sections"].get(section_name, [])):
            for bullet_idx, bullet_text in enumerate(item.get("bullets", [])):
                flat_bullets.append(bullet_text)
                origins.append((section_name, entry_idx, bullet_idx))

    # ── Encode ───────────────────────────────────────────────────────────────
    # sims[i][j] = similarity of flat_bullets[i] to req_texts[j].
    # Stays None when either side is empty — a JD with no parsed requirement
    # sentences used to crash here on max() of an empty sequence.
    sims = None
    if flat_bullets and req_texts:
        sims = cos_sim(encode(flat_bullets), encode(req_texts))

    # ── Scatter ──────────────────────────────────────────────────────────────
    # Turn the similarity matrix back into one scored-bullet dict per origin.
    bullet_results: dict[tuple[str, int, int], dict] = {}
    for i, origin in enumerate(origins):
        if sims is None:
            # No requirement sentences to match against: score everything 0.0
            # rather than dropping the bullet, so the rebuild step below still
            # finds an entry for every bullet that exists.
            best_score, best_req_text = 0.0, None
        else:
            similarities = sims[i].tolist()
            best_score = max(similarities)
            # max() + .index() resolves ties to the first requirement, matching
            # the pre-batching behaviour so scores don't shift.
            best_req_text = (
                req_texts[similarities.index(best_score)]
                if best_score > MATCH_FLOOR
                else None
            )

        bullet_results[origin] = {
            "text": flat_bullets[i],
            "semantic_score": round(best_score, 4),
            "best_match_requirement": best_req_text,
        }

    # ── Rebuild ──────────────────────────────────────────────────────────────
    for section_name in ("experience", "projects"):
        weight = section_weights.get(section_name, 1.0)

        for entry_idx, item in enumerate(resume["sections"].get(section_name, [])):
            scored_bullets = [
                bullet_results[(section_name, entry_idx, bullet_idx)]
                for bullet_idx in range(len(item.get("bullets", [])))
            ]

            # average relevance for this job/project entry (used by the assembler to decide what to include)
            if scored_bullets:
                avg = sum(b["semantic_score"] for b in scored_bullets) / len(scored_bullets)
            else:
                avg = 0.0

            entry = dict(item)  # copy the original metadata (company, title, dates, etc.)
            entry["section_weight"] = weight
            entry["avg_relevance"] = round(avg, 4)
            entry["bullets"] = scored_bullets

            scored_sections[section_name].append(entry)

    # education doesn't have bullets in our format, just pass it through
    scored_sections["education"] = resume["sections"].get("education", [])
    scored_sections["skills"] = resume["sections"].get("skills", [])

    return scored_sections


def compute_overall_semantic_score(scored_sections):
    """
    Average of all bullet semantic scores, weighted by section weight.
    This is the single number that represents how well this resume matches this JD.
    """
    total_score = 0.0
    total_bullets = 0

    for section_name in ["experience", "projects"]:
        for entry in scored_sections.get(section_name, []):
            weight = entry.get("section_weight", 1.0)
            for bullet in entry.get("bullets", []):
                total_score += bullet["semantic_score"] * weight
                total_bullets += 1

    if total_bullets == 0:
        return 0.0
    return round(total_score / total_bullets, 4)
