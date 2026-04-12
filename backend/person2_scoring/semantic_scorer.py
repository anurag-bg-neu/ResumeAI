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

import json
from sentence_transformers import SentenceTransformer, util


# load the model once at module level so we don't reload it every function call
model = SentenceTransformer("all-MiniLM-L6-v2")


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

    # encode all requirements once
    req_embeddings = model.encode(req_texts, convert_to_tensor=True)

    section_weights = get_section_weight(jd)

    # go through each section separately so we can attach section info and weights
    scored_sections = {
        "experience": [],
        "projects": [],
        "education": []
    }

    for section_name in ["experience", "projects"]:
        items = resume["sections"].get(section_name, [])
        weight = section_weights.get(section_name, 1.0)

        for item in items:
            scored_bullets = []
            for bullet_text in item.get("bullets", []):
                bullet_embedding = model.encode(bullet_text, convert_to_tensor=True)

                # cosine similarity against every requirement — gives us a score per requirement
                similarities = util.cos_sim(bullet_embedding, req_embeddings)[0]
                similarities = similarities.tolist()

                best_score = max(similarities)
                best_req_idx = similarities.index(best_score)
                best_req_text = req_texts[best_req_idx] if best_score > 0.1 else None

                scored_bullets.append({
                    "text": bullet_text,
                    "semantic_score": round(best_score, 4),
                    "best_match_requirement": best_req_text
                })

            # average relevance for this job/project entry (used by Person 3 to decide what to include)
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


if __name__ == "__main__":
    with open("../data/mock_data/sample_resume.json") as f:
        resume = json.load(f)
    with open("../data/mock_data/sample_jd.json") as f:
        jd = json.load(f)

    print("Encoding and scoring... (this takes a few seconds the first time)")
    scored = score_with_semantic(resume, jd)
    overall = compute_overall_semantic_score(scored)

    print(f"\nOverall semantic score: {overall}")
    print("\nTop bullets by semantic score (experience section):")
    for entry in scored["experience"]:
        print(f"\n  {entry['company']} — {entry['title']}")
        top_bullets = sorted(entry["bullets"], key=lambda x: x["semantic_score"], reverse=True)[:3]
        for b in top_bullets:
            print(f"    [{b['semantic_score']:.2f}] {b['text'][:70]}")
