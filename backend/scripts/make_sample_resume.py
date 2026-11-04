"""
make_sample_resume.py
---------------------
Generate the synthetic sample resume the README, smoke test, and end-to-end
checks all reference. Committed output: data/sample_resumes/resume.pdf

Entirely fictional. Real resumes are personal data and stay out of git
(see .gitignore), so the repo ships this instead and works on a fresh clone.

    python scripts/make_sample_resume.py
"""

from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent.parent / "data" / "sample_resumes" / "resume.pdf"

BODY = getSampleStyleSheet()["BodyText"]
NAME = ParagraphStyle("name", parent=BODY, fontSize=18, leading=22,
                      alignment=TA_CENTER, spaceAfter=2)
CONTACT = ParagraphStyle("contact", parent=BODY, fontSize=9, alignment=TA_CENTER)
H = ParagraphStyle("h", parent=BODY, fontSize=11, leading=14, spaceBefore=10,
                   spaceAfter=2, fontName="Helvetica-Bold")
ENTRY = ParagraphStyle("entry", parent=BODY, fontSize=9.5, spaceAfter=1)
BULLET = ParagraphStyle("bullet", parent=BODY, fontSize=9, leftIndent=12,
                        bulletIndent=4, spaceAfter=1)


def _section(flow, title):
    flow.append(Paragraph(title, H))
    flow.append(HRFlowable(width="100%", thickness=0.6, spaceAfter=4))


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    f = []
    f.append(Paragraph("Alex Riveras", NAME))
    f.append(Paragraph(
        "alex.riveras@example.com | (555) 010-4477 | Boston, MA | "
        "linkedin.com/in/alexriveras | github.com/alexriveras", CONTACT))
    f.append(Spacer(1, 6))

    _section(f, "EXPERIENCE")
    f.append(Paragraph(
        "<b>Nimbus Data Systems</b> | Software Engineer | Boston, MA | Jun 2022 - Present",
        ENTRY))
    for b in [
        "Built and shipped REST APIs in Python and FastAPI serving 40M requests per day at p99 latency under 120ms.",
        "Designed a PostgreSQL schema migration strategy that cut deploy-related downtime from 25 minutes to zero.",
        "Containerized 12 legacy services with Docker and deployed them to Kubernetes, reducing provisioning from days to minutes.",
        "Instrumented distributed tracing across the request path, cutting mean incident diagnosis time by 60%.",
        "Mentored three junior engineers through code review and paired debugging sessions.",
    ]:
        f.append(Paragraph(b, BULLET, bulletText="\u2022"))

    f.append(Paragraph(
        "<b>Harborline Analytics</b> | Backend Developer | Remote | Jul 2020 - May 2022",
        ENTRY))
    for b in [
        "Developed ETL pipelines in Python and Apache Airflow processing 2TB of event data nightly.",
        "Optimized slow SQL queries with targeted indexing, reducing dashboard load times from 9s to under 1s.",
        "Added CI pipelines in GitHub Actions with automated testing, raising release confidence and cadence.",
        "Wrote integration tests that lifted backend coverage from 34% to 81%.",
    ]:
        f.append(Paragraph(b, BULLET, bulletText="\u2022"))

    _section(f, "PROJECTS")
    f.append(Paragraph("<b>StreamFold</b> | Real-time aggregation engine", ENTRY))
    for b in [
        "Implemented a streaming aggregation service in Go handling 500k events per second.",
        "Used Redis for windowed state with at-least-once delivery guarantees.",
    ]:
        f.append(Paragraph(b, BULLET, bulletText="\u2022"))

    f.append(Paragraph("<b>PaperTrail</b> | Document search over embeddings", ENTRY))
    for b in [
        "Built semantic document search using sentence-transformers and FAISS over 100k PDFs.",
        "Exposed a React front end with sub-200ms query response.",
    ]:
        f.append(Paragraph(b, BULLET, bulletText="\u2022"))

    _section(f, "EDUCATION")
    f.append(Paragraph(
        "<b>Northeastern University</b> | M.S. Computer Science | Boston, MA | 2020", ENTRY))
    f.append(Paragraph(
        "Relevant Coursework: Distributed Systems, Machine Learning, Database Design", BULLET))

    _section(f, "SKILLS")
    f.append(Paragraph(
        "<b>Languages:</b> Python, Go, SQL, TypeScript, Java", ENTRY))
    f.append(Paragraph(
        "<b>Frameworks:</b> FastAPI, Django, React, Apache Airflow", ENTRY))
    f.append(Paragraph(
        "<b>Infrastructure:</b> Docker, Kubernetes, AWS, PostgreSQL, Redis, GitHub Actions", ENTRY))

    doc.build(f)
    print(f"wrote {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
