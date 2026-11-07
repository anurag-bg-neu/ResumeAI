"""
pdf_generator.py
------------------
Stage 3 — Resume Generation.

Primary: pdflatex + Jinja2 (Jake's Resume LaTeX template).
Fallback: reportlab (Windows / no TeX Live).

reportlab renderer matches original resume layout exactly:
  - Section headers: bold SCAPS title + full-width rule touching both margins
  - Education:  "Degree – School (GPA)   Dates"  bold, single line
                "Courses: ..."  normal weight, indented
  - Skills:     categorized, bold label + normal skills
  - Experience: company bold-left / dates right, title+location sub-line, bullets
  - Projects:   name bold | description italic | tech stack, bullets
  - Extra sections (Publications, Leadership, Achievements, Certifications):
      heading lines → bold only, normal weight for description lines
      bullet lines  → normal weight  (• marker)
      dates         → right-aligned beside heading
  - No orphan/empty bullet markers
  - Compact 9pt font targeting 2-page output

Both renderers produce the same sections. Résumé text is escaped for the
target markup (reportlab's mini-HTML, LaTeX) before it is interpolated.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as _xml

from jinja2 import BaseLoader, Environment

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# LaTeX TEMPLATE  (pdflatex path)
# ─────────────────────────────────────────────────────────────────────────────
_LATEX_TEMPLATE = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage{latexsym}\usepackage[empty]{fullpage}\usepackage{titlesec}
\usepackage{marvosym}\usepackage[usenames,dvipsnames]{color}\usepackage{verbatim}
\usepackage{enumitem}\usepackage[hidelinks]{hyperref}\usepackage{fancyhdr}
\usepackage[english]{babel}\usepackage{tabularx}\usepackage[T1]{fontenc}
\input{glyphtounicode}
\pagestyle{fancy}\fancyhf{}\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}\renewcommand{\footrulewidth}{0pt}
\addtolength{\oddsidemargin}{-0.5in}\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}\addtolength{\topmargin}{-.5in}\addtolength{\textheight}{1.0in}
\urlstyle{same}\raggedbottom\raggedright\setlength{\tabcolsep}{0in}
\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large}{}{0em}{}[\color{black}\titlerule\vspace{-5pt}]
\pdfgentounicode=1
\newcommand{\resumeItem}[1]{\item\small{#1\vspace{-2pt}}}
\newcommand{\resumeSubheading}[4]{\vspace{-2pt}\item\begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}\textbf{#1}&#2\\\textit{\small#3}&\textit{\small#4}\\\end{tabular*}\vspace{-7pt}}
\newcommand{\resumeProjectHeading}[2]{\item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}\small#1&#2\\\end{tabular*}\vspace{-7pt}}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in,label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
\begin{document}
\begin{center}
\textbf{\Huge\scshape << contact.name|default('')|le >>}\\[3pt]\small
<< contact.phone|default('')|le >>
<% if contact.phone and contact.email %> $|$ <% endif %>
\href{mailto:<< contact.email|default('')|url >>}{\underline{<< contact.email|default('')|le >>}}
<% if contact.linkedin %> $|$ \href{https://<< contact.linkedin|url >>}{\underline{<< contact.linkedin|le >>}} <% endif %>
<% if contact.location %> $|$ << contact.location|le >> <% endif %>
\end{center}
\section{Education}
\resumeSubHeadingListStart
<% for edu in education %>
\resumeSubheading{<< edu.degree|default('')|le >><% if edu.details %> (<< edu.details|join(' | ')|le >>)<% endif %>}{<< edu.dates|default('')|le >>}{<< edu.school|default('')|le >>}{}
<% if edu.courses %>\resumeItemListStart\resumeItem{\textit{Courses: << edu.courses|le >>}}\resumeItemListEnd<% endif %>
<% endfor %>
\resumeSubHeadingListEnd
\section{Skills}
\begin{itemize}[leftmargin=0.15in,label={}]\small{\item{
<% for cat in skills.categorized %>\textbf{<< cat.category|le >>}{: << cat.skills|join(', ')|le >>} \\
<% endfor %>
}}\end{itemize}
\section{Experience}
\resumeSubHeadingListStart
<% for exp in experience %>
\resumeSubheading{<< exp.company|default('')|le >>}{<< exp.dates|default('')|le >>}{<< exp.title|default('')|le >>}{<< exp.location|default('')|le >>}
\resumeItemListStart<% for b in exp.bullets %>\resumeItem{<< b|le >>}<% endfor %>\resumeItemListEnd
<% endfor %>
\resumeSubHeadingListEnd
<% if projects %>
\section{Projects}
\resumeSubHeadingListStart
<% for proj in projects %>
\resumeProjectHeading{\textbf{<< proj.name|default('')|le >>}<% if proj.description %> $|$ \emph{\small << proj.description|le >>}<% endif %><% if proj.technologies %> $|$ \small << proj.technologies|join(', ')|le >><% endif %>}{}
\resumeItemListStart<% for b in proj.bullets %>\resumeItem{<< b|le >>}<% endfor %>\resumeItemListEnd
<% endfor %>
\resumeSubHeadingListEnd
<% endif %>
<% for label, items in extras %>
\section{ <<- label|le ->> }
\resumeSubHeadingListStart
<% for item in items %><% if item.type == 'heading' %>\item\textbf{ <<- item.text|le ->> }<% if item.date %>\hfill << item.date|le >><% endif %>
<% else %>\resumeItemListStart\resumeItem{ <<- item.text|le ->> }\resumeItemListEnd
<% endif %><% endfor %>
\resumeSubHeadingListEnd
<% endfor %>
\end{document}
"""

# ─────────────────────────────────────────────────────────────────────────────
# LaTeX ESCAPE
# ─────────────────────────────────────────────────────────────────────────────
_LS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\^{}",
    "\\": r"\textbackslash{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}
_LRE = re.compile(
    "(" + "|".join(re.escape(k) for k in sorted(_LS, key=len, reverse=True)) + ")"
)


def _le(t):
    return _LRE.sub(lambda m: _LS[m.group(0)], str(t)) if t else ""


def _url(t):
    """Keep only characters that are safe inside a LaTeX \\href URL."""
    return re.sub(r"[^\w.@/:+\-]", "", str(t)) if t else ""


def _build_jinja_env():
    env = Environment(
        loader=BaseLoader(),
        # LaTeX is full of { } and %, so Jinja uses delimiters LaTeX never does.
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="##(",
        comment_end_string=")##",
        autoescape=False,
    )
    env.filters["le"] = _le
    env.filters["url"] = _url
    return env


# ─────────────────────────────────────────────────────────────────────────────
# EXTRA SECTION PARSER
# ─────────────────────────────────────────────────────────────────────────────
_BULLET_RE = re.compile(r"^[•\-–—*·]\s*")

# Date suffix pattern: "  Sep 2024 – Present" at end of a line
_DATE_TRAIL = re.compile(
    r"^(.*?)\s+"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Spring|Fall|Summer|Winter|\d{4})"
    r"[^\n]*?(?:Present|Current|Now|\d{4}))\s*$",
    re.IGNORECASE,
)


def _parse_extra_lines(raw: str) -> list[dict]:
    """
    Convert raw extra-section text into structured line dicts, handling both
    PyMuPDF inline format ("• text") and split format ("•\ntext on next line").

    Returns list of:
      {"type": "heading", "text": str, "date": str}
      {"type": "bullet",  "text": str}
    """
    # ── Step 1: merge orphan bullet markers with the following text ───────────
    # PyMuPDF emits "•\n" as a lone line; merge it with the next non-empty line.
    raw_lines = raw.split("\n")
    merged: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        lone_bullet = (
            _BULLET_RE.match(line.strip())
            and not _BULLET_RE.sub("", line.strip()).strip()
        )
        if lone_bullet:
            j = i + 1
            while j < len(raw_lines) and not raw_lines[j].strip():
                j += 1
            if j < len(raw_lines):
                merged.append("\u2022 " + raw_lines[j].strip())
                i = j + 1
                continue
        merged.append(line)
        i += 1

    # ── Step 2: classify lines ────────────────────────────────────────────────
    result: list[dict] = []
    pending: str = ""
    pending_type: str = ""
    pending_date: str = ""

    def _flush():
        nonlocal pending, pending_type, pending_date
        t = pending.strip()
        if not t:
            pending = pending_type = pending_date = ""
            return
        if pending_type == "bullet":
            result.append({"type": "bullet", "text": t})
        elif pending_type == "heading":
            result.append({"type": "heading", "text": t, "date": pending_date})
        pending = pending_type = pending_date = ""

    def _is_continuation(clean: str) -> bool:
        """
        A line is a continuation (wraps from the previous line) if:
        - starts lowercase
        - starts with a common joining word
        - starts with a parenthetical
        - is a short fragment (<=60 chars) with no date and no em-dash
          (em-dash signals a new heading like "Role – Company")
        """
        if not clean:
            return False
        if clean[0].islower():
            return True
        if re.match(r"^(and|or|with|using|for|that|which|the|a |an |\()", clean, re.I):
            return True
        if re.match(r"^\d+", clean):  # "400CC...", "88% accuracy..." etc.
            return True
        # Short fragment without em-dash/en-dash → continuation of previous line
        has_dash = bool(re.search(r"[\u2013\u2014\u2012–—]", clean))
        if len(clean) <= 60 and not has_dash and not _DATE_TRAIL.match(clean):
            return True
        return False

    for line in merged:
        stripped = line.strip()
        if not stripped:
            continue

        is_bullet = bool(_BULLET_RE.match(stripped))
        clean = _BULLET_RE.sub("", stripped).strip()

        # Empty bullet marker → skip
        if is_bullet and not clean:
            continue

        if is_bullet:
            _flush()
            pending = clean
            pending_type = "bullet"
        else:
            # Continuation of current pending item?
            if pending_type in ("bullet", "heading") and _is_continuation(clean):
                pending = pending + " " + clean
                continue

            # New heading
            _flush()
            m = _DATE_TRAIL.match(stripped)
            if m:
                pending = m.group(1).strip()
                pending_date = m.group(2).strip()
            else:
                pending = stripped
                pending_date = ""
            pending_type = "heading"

    _flush()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SHARED SECTION DATA  (both renderers read these, so they stay in sync)
# ─────────────────────────────────────────────────────────────────────────────

EXTRA_ORDER: list[tuple[str, str]] = [
    ("publications", "RESEARCH & PUBLICATIONS"),
    ("leadership", "LEADERSHIP AND TEACHING EXPERIENCE"),
    ("achievements", "ACHIEVEMENTS & EXTRACURRICULAR ACTIVITIES"),
    ("certifications", "CERTIFICATIONS"),
]


def _skill_categories(skills) -> list[dict]:
    """skills is {"flat", "categorized"} from the assembler, or a bare list."""
    if isinstance(skills, dict):
        return skills.get("categorized", [])
    return [{"category": "Skills", "skills": list(skills)}] if skills else []


def _extra_sections(extra: dict) -> list[tuple[str, list[dict]]]:
    """[(heading, parsed lines)] for each non-empty extra section, in EXTRA_ORDER."""
    return [
        (label, _parse_extra_lines(extra[key].strip()))
        for key, label in EXTRA_ORDER
        if extra.get(key, "").strip()
    ]


# ─────────────────────────────────────────────────────────────────────────────
# REPORTLAB — STYLES
# ─────────────────────────────────────────────────────────────────────────────
def _styles():
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    S = getSampleStyleSheet()
    BASE = 9.0  # compact base size → 2-page target

    return {
        "name": ParagraphStyle(
            "RN",
            parent=S["Title"],
            fontSize=15,
            spaceBefore=0,
            spaceAfter=1,
            alignment=TA_CENTER,
        ),
        "contact": ParagraphStyle(
            "RC",
            parent=S["Normal"],
            fontSize=8.5,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=2,
        ),
        # Section heading: UPPERCASE bold, no extra spacing
        "sec_title": ParagraphStyle(
            "RS",
            parent=S["Normal"],
            fontSize=10.5,
            fontName="Helvetica-Bold",
            spaceBefore=5,
            spaceAfter=0,
        ),
        # One-line education entry (bold)
        "edu": ParagraphStyle(
            "RE",
            parent=S["Normal"],
            fontSize=BASE,
            fontName="Helvetica-Bold",
            spaceBefore=2,
            spaceAfter=0,
        ),
        "edu_right": ParagraphStyle(
            "RER",
            parent=S["Normal"],
            fontSize=BASE,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
            spaceBefore=2,
            spaceAfter=0,
        ),
        "courses": ParagraphStyle(
            "RCou",
            parent=S["Normal"],
            fontSize=BASE - 0.5,
            leftIndent=6,
            spaceAfter=2,
            leading=12,
        ),
        # Experience
        "exp_co": ParagraphStyle(
            "REC",
            parent=S["Normal"],
            fontSize=BASE,
            fontName="Helvetica-Bold",
            spaceAfter=0,
            spaceBefore=3,
        ),
        "exp_co_r": ParagraphStyle(
            "RER2",
            parent=S["Normal"],
            fontSize=BASE,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
            spaceAfter=0,
            spaceBefore=3,
        ),
        "exp_sub": ParagraphStyle(
            "RES", parent=S["Normal"], fontSize=BASE - 0.5, spaceAfter=0, leading=11
        ),
        # Bullets
        "bullet": ParagraphStyle(
            "RB",
            parent=S["Normal"],
            fontSize=BASE,
            leftIndent=10,
            firstLineIndent=0,
            spaceAfter=0,
            leading=12,
        ),
        # Skills
        "skill": ParagraphStyle(
            "RSk",
            parent=S["Normal"],
            fontSize=BASE,
            leftIndent=4,
            spaceAfter=0,
            leading=12,
        ),
        # Extra section headings (bold) + normal date
        "ex_head": ParagraphStyle(
            "REH",
            parent=S["Normal"],
            fontSize=BASE,
            fontName="Helvetica-Bold",
            spaceBefore=2,
            spaceAfter=0,
        ),
        "ex_head_r": ParagraphStyle(
            "REHR",
            parent=S["Normal"],
            fontSize=BASE,
            alignment=TA_RIGHT,
            spaceBefore=2,
            spaceAfter=0,
        ),
        # Extra section plain description (non-bold, e.g. project description line)
        "ex_plain": ParagraphStyle(
            "REP",
            parent=S["Normal"],
            fontSize=BASE,
            spaceBefore=0,
            spaceAfter=0,
            leading=12,
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# REPORTLAB — HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _full_hr(avail_w, colors):
    """HRFlowable that spans the exact available width with no padding."""
    from reportlab.platypus import HRFlowable

    return HRFlowable(
        width=avail_w,
        thickness=0.5,
        color=colors.black,
        spaceAfter=2,
        spaceBefore=0,
        hAlign="LEFT",
        vAlign="BOTTOM",
    )


def _two_col(left_para, right_para, avail_w, date_w):
    """Table: left content, right content right-aligned."""
    from reportlab.platypus import Table, TableStyle

    tbl = Table([[left_para, right_para]], colWidths=[avail_w - date_w, date_w])
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tbl


# ─────────────────────────────────────────────────────────────────────────────
# REPORTLAB — MAIN GENERATOR
# ─────────────────────────────────────────────────────────────────────────────


def _generate_with_reportlab(data: dict, output_pdf: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
    )

    contact = data.get("contact", {})
    experience = data.get("experience", [])
    projects = data.get("projects", [])
    education = data.get("education", [])
    skills_d = data.get("skills", {})
    extra = data.get("extra_sections", {})
    skills_cats = _skill_categories(skills_d)

    LM = RM = 0.45 * inch  # 0.45" margins — matches original tight layout
    TM = 0.38 * inch
    BM = 0.45 * inch
    avail_w = letter[0] - LM - RM  # exact usable width in points
    # Right-hand date column: wide enough for the longest date on the page
    # ("Jan 2026 - Apr 2026, Sep 2026 - Present"), but never under 1.45".
    longest_date = max(
        (
            stringWidth(e.get("dates", ""), "Helvetica-Bold", 9.0)
            for e in [*experience, *education]
        ),
        default=0.0,
    )
    DATE_W = min(max(1.45 * inch, longest_date + 6), avail_w / 2)

    # Use BaseDocTemplate + explicit Frame with zero padding so that
    # HRFlowable(width=avail_w) and Paragraph text both use the exact
    # same drawable width — no internal frame padding misalignment.
    doc = BaseDocTemplate(
        str(output_pdf),
        pagesize=letter,
        leftMargin=LM,
        rightMargin=RM,
        topMargin=TM,
        bottomMargin=BM,
    )
    frame = Frame(
        LM,
        BM,  # x, y of bottom-left corner
        avail_w,
        letter[1] - TM - BM,  # width, height
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])
    S = _styles()
    story = []

    # ── helpers ───────────────────────────────────────────────────────────────
    def gap(pts=2):
        story.append(Spacer(1, pts))

    def section(title: str):
        story.append(Paragraph(title, S["sec_title"]))
        story.append(_full_hr(avail_w, colors))

    def bul(text: str):
        """Render a bullet. If text matches 'Bold Label: rest', bold the label."""
        if not text.strip():
            return
        # Pattern: short bold label before first colon (≤45 chars, no period inside)
        m = re.match(r"^([^:.]{1,45}):\s(.+)$", text, re.DOTALL)
        if m:
            label = _xml(m.group(1).strip())
            rest = _xml(m.group(2).strip())
            rendered = f"\u2022\u00a0<b>{label}:</b> {rest}"
        else:
            rendered = f"\u2022\u00a0{_xml(text)}"
        story.append(Paragraph(rendered, S["bullet"]))

    def two_col(left_p, right_p):
        story.append(_two_col(left_p, right_p, avail_w, DATE_W))

    # ── HEADER ────────────────────────────────────────────────────────────────
    story.append(Paragraph(_xml(contact.get("name", "")), S["name"]))
    parts = [
        p
        for p in [
            contact.get("phone", ""),
            contact.get("email", ""),
            contact.get("linkedin", ""),
            contact.get("location", ""),
        ]
        if p
    ]
    if parts:
        story.append(Paragraph(_xml(" | ".join(parts)), S["contact"]))
    story.append(_full_hr(avail_w, colors))

    # ── EDUCATION ─────────────────────────────────────────────────────────────
    section("EDUCATION")
    for edu in education:
        details = " | ".join(edu.get("details", []))
        heading = " \u2013 ".join(p for p in (edu.get("degree", ""), edu.get("school", "")) if p)
        if details:
            heading += f" ({details})"
        # Single bold line: "Degree - School (GPA)"  |  dates right
        two_col(
            Paragraph(f"<b>{_xml(heading)}</b>", S["edu"]),
            Paragraph(_xml(edu.get("dates", "")), S["edu_right"]),
        )
        if edu.get("courses"):
            story.append(Paragraph(_xml(f"Courses: {edu['courses']}"), S["courses"]))
    gap(3)

    # ── SKILLS ────────────────────────────────────────────────────────────────
    section("SKILLS")
    for cat in skills_cats:
        story.append(
            Paragraph(
                f"<b>{_xml(cat['category'])}</b>: {_xml(', '.join(cat.get('skills', [])))}",
                S["skill"],
            )
        )
    gap(3)

    # ── EXPERIENCE ────────────────────────────────────────────────────────────
    section("EXPERIENCE")
    for exp in experience:
        two_col(
            Paragraph(f"<b>{_xml(exp.get('company', ''))}</b>", S["exp_co"]),
            Paragraph(_xml(exp.get("dates", "")), S["exp_co_r"]),
        )
        title_loc = " \u2013 ".join(p for p in (exp.get("title", ""), exp.get("location", "")) if p)
        story.append(Paragraph(_xml(title_loc), S["exp_sub"]))
        for b in exp.get("bullets", []):
            bul(b)
        gap(2)

    # ── PROJECTS ──────────────────────────────────────────────────────────────
    if projects:
        section("PROJECTS")
        for proj in projects:
            head = f"<b>{_xml(proj.get('name', ''))}</b>"
            if proj.get("description"):
                head += f" | <i>{_xml(proj['description'])}</i>"
            if proj.get("technologies"):
                head += f" | {_xml(', '.join(proj['technologies']))}"
            story.append(Paragraph(head, S["exp_co"]))
            for b in proj.get("bullets", []):
                bul(b)
            gap(2)

    # ── EXTRA SECTIONS ────────────────────────────────────────────────────────
    for label, items in _extra_sections(extra):
        section(label)
        for item in items:
            if item["type"] == "heading":
                if item.get("date"):
                    two_col(
                        Paragraph(_xml(item["text"]), S["ex_head"]),
                        Paragraph(_xml(item["date"]), S["ex_head_r"]),
                    )
                else:
                    # Long paper titles etc — bold, full width
                    story.append(Paragraph(_xml(item["text"]), S["ex_head"]))
            else:  # bullet — normal weight
                bul(item["text"])
        gap(2)

    doc.build(story)
    log.info("reportlab PDF → %s", output_pdf)


# ─────────────────────────────────────────────────────────────────────────────
# PDFLATEX GENERATOR
# ─────────────────────────────────────────────────────────────────────────────


def _generate_with_pdflatex(data: dict, output_pdf: Path) -> None:
    tmpl = _build_jinja_env().from_string(_LATEX_TEMPLATE)
    ld = dict(data)
    ld["skills"] = {"categorized": _skill_categories(data.get("skills", {}))}
    ld["extras"] = _extra_sections(data.get("extra_sections", {}))
    src = tmpl.render(**ld)
    with tempfile.TemporaryDirectory() as td:
        tex = Path(td) / "r.tex"
        tex.write_text(src, encoding="utf-8")
        res = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                td,
                str(tex),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        pdf = Path(td) / "r.pdf"
        if res.returncode != 0 or not pdf.exists():
            # pdflatex reports errors on stdout; keep the tail for the log.
            raise RuntimeError(f"pdflatex exit {res.returncode}: {res.stdout[-800:]}")
        shutil.copy2(str(pdf), str(output_pdf))
    log.info("pdflatex → %s", output_pdf)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def generate_resume_pdf(
    assembled_data: dict,
    output_dir: str = "results",
    filename_stem: str = "tailored_resume",
    force_reportlab: bool = False,
) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"{filename_stem}.pdf"

    if not force_reportlab and shutil.which("pdflatex"):
        try:
            _generate_with_pdflatex(assembled_data, pdf)
            log.info("PDF via pdflatex: %s", pdf)
            return str(pdf.resolve())
        except Exception as e:
            log.warning("pdflatex failed (%s) — falling back to reportlab", e)
    try:
        _generate_with_reportlab(assembled_data, pdf)
        log.info("PDF via reportlab: %s", pdf)
        return str(pdf.resolve())
    except Exception as e:
        raise RuntimeError(f"Both generators failed: {e}") from e
