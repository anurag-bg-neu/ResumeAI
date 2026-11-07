from conftest import SAMPLE_RESUME

from parsing.resume_parser import parse_resume


def test_skills_block_keeps_every_item_and_category(layout_resume_pdf):
    r = parse_resume(str(layout_resume_pdf))
    cats = {c["category"]: c["skills"] for c in r["sections"]["skills_categorized"]}

    assert list(cats) == ["Languages", "Concepts", "Frameworks", "Cloud", "Tools"]
    # The last item on each line used to be swallowed by the next label.
    assert cats["Languages"][-1] == "Go"
    assert cats["Concepts"][-1] == "CI/CD"
    assert cats["Frameworks"][-1] == "Vitest"
    assert cats["Tools"][-1] == "Spec-Driven Development"
    # Commas inside parentheses don't split the item.
    assert "AWS (EC2, S3, Lambda)" in cats["Cloud"]


def test_flat_skills_expand_parenthesised_lists(layout_resume_pdf):
    flat = parse_resume(str(layout_resume_pdf))["sections"]["skills"]
    assert {"AWS", "EC2", "S3", "Lambda"} <= set(flat)
    # Certifications and profiles are not skills.
    assert not any("Coursera" in s or "LeetCode" in s for s in flat)


def test_all_skills_detected_is_canonical(layout_resume_pdf):
    detected = set(parse_resume(str(layout_resume_pdf))["all_skills_detected"])
    assert {"React", "Express", "REST", "Go", "Linux", "Kubernetes", "Vitest"} <= detected
    assert "React.js" not in detected


def test_certifications_move_to_extra_sections(layout_resume_pdf):
    certs = parse_resume(str(layout_resume_pdf))["extra_sections"]["certifications"]
    assert "Cloud Practitioner (AWS)" in certs
    assert "Front-End Developer (Coursera)" in certs


def test_experience_one_field_per_line(layout_resume_pdf):
    exp = parse_resume(str(layout_resume_pdf))["sections"]["experience"]
    got = [(e["company"], e["title"], e["location"]) for e in exp]
    assert got == [
        ("Lakeside University", "Teaching Assistant", "Austin, TX, USA"),
        ("Granite Bank", "Software Development Engineer", "Pune, Maharashtra, India"),
        ("Coastal Research Lab - Applied Signals Group", "Data Analytics Intern",
         "Chennai, Tamil Nadu, India"),
    ]
    assert exp[0]["dates"] == "Jan 2025 - Apr 2025, Sep 2025 - Present"
    # "Granite Bank" must not be glued onto the previous bullet.
    assert all("Granite" not in b for b in exp[0]["bullets"])
    assert len(exp[1]["bullets"]) == 2


def test_education_school_first_layout(layout_resume_pdf):
    edu = parse_resume(str(layout_resume_pdf))["sections"]["education"]
    assert [(e["school"], e["dates"]) for e in edu] == [
        ("Lakeside University", "Sep 2024 - May 2026"),
        ("Riverbend Institute of Technology", "Jul 2016 - Jun 2020"),
    ]
    assert edu[0]["degree"] == "Master of Science (M.S.) in Computer Science"
    assert edu[0]["details"] == ["GPA: 3.80"]
    assert edu[0]["courses"].startswith("Algorithms")
    assert "courses" not in edu[1]


def test_projects_include_open_source_and_tech_stack(layout_resume_pdf):
    projects = parse_resume(str(layout_resume_pdf))["sections"]["projects"]
    by_name = {p["name"]: p for p in projects}
    assert set(by_name) == {"Tracklet", "Lanternfly (Contributor)"}
    assert by_name["Tracklet"]["technologies"] == ["Next.js", "TypeScript", "MongoDB"]
    assert by_name["Tracklet"]["description"] == "Habit tracking platform"


def test_contact(layout_resume_pdf):
    contact = parse_resume(str(layout_resume_pdf))["contact"]
    assert contact["name"] == "Jordan Avery Lee"
    assert contact["location"] == "Austin, TX"
    assert contact["email"] == "jordan.lee@example.com"


def test_sample_resume_single_line_headers():
    r = parse_resume(str(SAMPLE_RESUME))
    exp = r["sections"]["experience"]
    assert [(e["company"], e["title"]) for e in exp] == [
        ("Nimbus Data Systems", "Software Engineer"),
        ("Harborline Analytics", "Backend Developer"),
    ]
    edu = r["sections"]["education"][0]
    assert (edu["school"], edu["degree"]) == ("Northeastern University", "M.S. Computer Science")
