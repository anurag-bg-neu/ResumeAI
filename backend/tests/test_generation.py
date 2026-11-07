import pymupdf

from generation.assembler import assemble_resume, inject_missing_skills
from generation.pdf_generator import (
    _LATEX_TEMPLATE,
    _build_jinja_env,
    _extra_sections,
    _skill_categories,
    generate_resume_pdf,
)


def _scored(avgs):
    return {
        "scored_sections": {
            "experience": [
                {
                    "company": f"Co{i}",
                    "title": "Engineer",
                    "avg_relevance": avg,
                    "bullets": [
                        {"text": f"Co{i} bullet {j}", "semantic_score": avg + j / 100}
                        for j in range(6)
                    ],
                }
                for i, avg in enumerate(avgs)
            ],
            "projects": [],
            "education": [],
            "skills": ["React.js", "Kubernetes"],
        },
        "skills_analysis": {"covered": ["React"], "missing": ["k8s", "Go"], "partial_match": []},
        "overall_semantic_score": 0.4,
        "overall_keyword_score": 0.1,
    }


def test_every_job_is_kept_in_resume_order():
    assembled = assemble_resume(_scored([0.1, 0.5, 0.2]), {"title": "", "company": ""})
    assert [e["company"] for e in assembled["experience"]] == ["Co0", "Co1", "Co2"]
    # The most relevant job (Co1) gets the most bullets, best first.
    co1 = assembled["experience"][1]
    assert len(co1["bullets"]) == 5
    assert co1["bullets"][0] == "Co1 bullet 5"


def test_covered_skills_promoted_by_canonical_name():
    assembled = assemble_resume(_scored([0.5]), {"title": "", "company": ""})
    assert assembled["skills"]["flat"][0] == "React.js"


def test_inject_missing_skills_skips_aliases():
    assembled = assemble_resume(_scored([0.5]), {"title": "", "company": ""})
    added = inject_missing_skills(assembled, assembled["gap_report"])
    assert added == ["Go"]  # "k8s" is already there as "Kubernetes"
    assert inject_missing_skills(assembled, assembled["gap_report"]) == []


def _assembled():
    return {
        "contact": {"name": "Jordan <Lee> & Co", "email": "j@example.com"},
        "education": [{"degree": "M.S.", "school": "Lakeside", "dates": "2026", "details": []}],
        "skills": {"categorized": [{"category": "Languages", "skills": ["C++", "C#"]}]},
        "experience": [{"company": "Acme", "title": "SDE", "dates": "2024", "location": "",
                        "bullets": ["Built reusable <Button> components for 50% of pages & more"]}],
        "projects": [{"name": "Tracklet", "description": "Habits", "technologies": ["Next.js"],
                      "bullets": ["Shipped it"]}],
        "extra_sections": {"certifications": "• Cloud Practitioner (AWS)"},
    }


def test_reportlab_pdf_keeps_markup_like_text(tmp_path):
    pdf = generate_resume_pdf(_assembled(), output_dir=str(tmp_path), force_reportlab=True)
    with pymupdf.open(pdf) as doc:
        text = " ".join(page.get_text() for page in doc)
    assert "<Button>" in text
    assert "Jordan <Lee> & Co" in text
    assert "Next.js" in text
    assert "Cloud Practitioner (AWS)" in text
    assert "Semantic match" not in text  # no scoring footer on the candidate's resume


def test_latex_template_renders_and_escapes():
    data = _assembled()
    data["skills"] = {"categorized": _skill_categories(data["skills"])}
    data["extras"] = _extra_sections(data["extra_sections"])
    tex = _build_jinja_env().from_string(_LATEX_TEMPLATE).render(**data)
    assert r"\textless{}Button\textgreater{}" in tex
    assert r"50\% of pages \& more" in tex
    assert r"\section{CERTIFICATIONS}" in tex
