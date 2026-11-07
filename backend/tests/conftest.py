"""
Shared fixtures. Every test runs offline: nothing here loads the
sentence-transformer model, so the suite is fast and needs no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

BACKEND = Path(__file__).resolve().parent.parent
SAMPLE_RESUME = BACKEND / "data" / "sample_resumes" / "resume.pdf"
SAMPLE_JDS = BACKEND / "data" / "sample_jds"

# A fictional résumé in the layout that used to break the parser: skill
# labels on their own line, "City, State, Country" location lines, a company
# line right after a bullet, a two-range date line, an OPEN SOURCE section and
# inline Certifications/Profiles lines inside the skills block.
ONE_LINE_PER_FIELD_RESUME = """\
Jordan Avery Lee
Austin, TX | +1 512-555-0142 | jordan.lee@example.com | linkedin.com/in/jordan-lee
EDUCATION
Lakeside University
Sep 2024 - May 2026 (Expected)
Master of Science (M.S.) in Computer Science, GPA: 3.80/4.0
Austin, TX, USA
Coursework: Algorithms, Distributed Systems, Machine Learning
Riverbend Institute of Technology
Jul 2016 - Jun 2020
Bachelor of Technology (B.Tech) in Computer Engineering, GPA: 3.60/4.0
Pune, Maharashtra, India
TECHNICAL SKILLS
Languages:
C++, Python, Java, TypeScript, SQL, Go
Concepts:
Data Structures and Algorithms, REST APIs, CI/CD
Frameworks:
React.js, Node.js, Express.js, FastAPI, Vitest
Cloud:
AWS (EC2, S3, Lambda), Docker, Kubernetes, Render
Tools:
Git, Linux/Unix Terminal, Jira, Spec-Driven Development
Certifications: Cloud Practitioner (AWS), Front-End Developer (Coursera)
Profiles:
LeetCode (300+ problems solved)
OPEN SOURCE
Lanternfly (Contributor) | Open-source note-taking app | TypeScript, Node.js, Vitest
• Fixed credential masking across 3 CLI flows with 4 merged pull requests.
PROJECTS
Tracklet | Habit tracking platform | Next.js, TypeScript, MongoDB (Demo | Code)
• Built a full-stack habit tracker with 20 REST endpoints deployed on Vercel.
EXPERIENCE
Lakeside University
Jan 2025 - Apr 2025, Sep 2025 - Present
Teaching Assistant
Austin, TX, USA
• Mentored 80+ students through weekly code reviews on React and Node.js.
Granite Bank
Jul 2020 - Aug 2024
Software Development Engineer
Pune, Maharashtra, India
• Cut manual reporting time by 40% by building an automated SQL alerting pipeline.
• Integrated RESTful backend APIs via asynchronous JavaScript for 3,000+ users.
Coastal Research Lab - Applied Signals Group
May 2019 - Jun 2019
Data Analytics Intern
Chennai, Tamil Nadu, India
• Cleaned ECG recordings with Python (pandas, NumPy) for a 6-person research team.
"""


def write_text_pdf(text: str, path: Path) -> Path:
    """Render text one line per row on letter pages — enough for PyMuPDF."""
    c = canvas.Canvas(str(path), pagesize=letter)
    y = letter[1] - 40
    for line in text.splitlines():
        if y < 40:
            c.showPage()
            y = letter[1] - 40
        c.setFont("Helvetica", 9)
        c.drawString(40, y, line)
        y -= 12
    c.save()
    return path


@pytest.fixture
def layout_resume_pdf(tmp_path: Path) -> Path:
    return write_text_pdf(ONE_LINE_PER_FIELD_RESUME, tmp_path / "layout_resume.pdf")
