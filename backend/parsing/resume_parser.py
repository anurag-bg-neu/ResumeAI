"""
resume_parser.py — Structured résumé parser for the ResumeAI pipeline.

Public API:
    parse_resume(file_path: str) -> dict

The returned dict strictly matches the Stage 1 → Stage 2 JSON contract:

    {
      "contact": {"name": str, "email": str, "phone": str},
      "sections": {
        "experience": [{"company", "title", "dates", "location", "bullets"}],
        "education":  [{"school", "degree", "dates", "details"}],
        "skills":     [str, ...],
        "projects":   [{"name", "description", "bullets"}]
      },
      "all_skills_detected": [str, ...]
    }

Architecture:
    PDF → raw text  (utils.extract_text_from_pdf)
         → sections (classify_sections)
         → per-section parsers
         → JSON assembly
"""

from __future__ import annotations

import logging
import re

from .utils import (
    BULLET_INLINE_RE,
    COMPANY_HINTS_RE,
    DATE_RANGE,
    ROLE_SEP_RE,
    ROLE_WORD_RE,
    STOP_SECTIONS_RE,
    canonical_skill,
    extract_bullets,
    extract_date_range,
    extract_date_ranges,
    extract_location,
    extract_skills,
    extract_text_from_pdf,
    is_location_line,
    merge_continuation_lines,
    normalize_bullet_lines,
    remove_date_range,
    split_outside_parens,
    split_role_and_company,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

# A header is the whole line (optionally with a trailing colon), so prose or
# inline labels like "Profiles: LeetCode, ..." never open a new section.
_SECTION_HEADERS: list[tuple[str, str]] = [
    (
        "summary",
        r"(?:professional\s+|career\s+)?(?:summary|objective|profile)|about(?:\s+me)?",
    ),
    (
        "experience",
        r"(?:work\s+|professional\s+|relevant\s+)?experience"
        r"|employment(?:\s+history)?|work\s+history",
    ),
    (
        "education",
        r"education(?:al\s+background)?|academic\s+background|academics|qualifications",
    ),
    (
        "skills",
        r"(?:technical\s+|core\s+|key\s+)?skills(?:\s+(?:summary|overview))?"
        r"(?:\s*(?:&|and)\s*\w+(?:\s+\w+)?)?"
        r"|(?:core\s+)?competencies|technologies|technical\s+toolkit"
        r"|tech(?:nical)?\s+stack|proficiencies|areas\s+of\s+expertise",
    ),
    (
        "projects",
        r"(?:academic\s+|personal\s+|key\s+|selected\s+|technical\s+)?projects?"
        r"|project\s+work|portfolio",
    ),
    (
        "open_source",
        r"open[\s-]source(?:\s+(?:contributions?|projects?|work))?",
    ),
    # ── Extra sections: kept as raw text, rendered as-is by the generator ──
    (
        "publications",
        r"(?:research\s*(?:&|and)\s*)?publications?|research",
    ),
    (
        "leadership",
        r"leadership(?:\s*(?:&|and)\s*teaching)?|teaching\s+experience",
    ),
    (
        "achievements",
        r"achievements?|extracurricular(?:\s+activities)?|honou?rs?(?:\s*(?:&|and)\s*awards?)?"
        r"|awards?(?:\s*(?:&|and)\s*honou?rs?)?",
    ),
    (
        "certifications",
        r"(?:licenses?\s*(?:&|and)\s*)?certifications?(?:\s*(?:&|and)\s*licenses?)?"
        r"|licenses?|credentials|awards?\s*(?:&|and)\s*certifications?",
    ),
]

EXTRA_SECTIONS: tuple[str, ...] = ("publications", "leadership", "achievements", "certifications")

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(rf"(?:{body})\s*:?", re.IGNORECASE))
    for name, body in _SECTION_HEADERS
]


def _find_section_headers(
    lines: list[str], patterns: list[tuple[str, re.Pattern[str]]]
) -> list[tuple[int, str]]:
    """Return (line_index, section_name) for the first header of each section."""
    boundaries: list[tuple[int, str]] = []
    seen: set[str] = set()
    for line_num, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        for section_name, pattern in patterns:
            if section_name not in seen and pattern.fullmatch(stripped):
                boundaries.append((line_num, section_name))
                seen.add(section_name)
                break
    return boundaries


def _slice_sections(
    lines: list[str], boundaries: list[tuple[int, str]]
) -> dict[str, str]:
    """Body text between each header and the next one."""
    sections: dict[str, str] = {}
    for i, (line_num, section_name) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(lines)
        body = "\n".join(lines[line_num + 1 : end]).strip()
        if body:
            sections[section_name] = body
    return sections


def classify_sections(text: str) -> dict[str, str]:
    """
    Split résumé text into labeled sections.

    Returns a dict mapping section name → section text.
    Always includes "full_text" and "contact" keys.
    """
    lines = text.split("\n")
    sections: dict[str, str] = {"full_text": text}

    # The first few non-empty lines are the contact block.
    contact_lines = [ln.strip() for ln in lines[:12] if ln.strip()]
    sections["contact"] = "\n".join(contact_lines[:5])

    sections.update(_slice_sections(lines, _find_section_headers(lines, _SECTION_PATTERNS)))

    log.info("Sections classified: %s", list(sections.keys()))
    return sections


# ─────────────────────────────────────────────────────────────────────────────
# CONTACT EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────


def extract_contact_info(text: str) -> dict[str, str]:
    """
    Extract contact details from the top of the résumé text.

    Returns {"name", "email", "phone", "linkedin", "location"} (all str).
    """
    contact: dict[str, str] = {
        "name": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "location": "",
    }

    email_m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    if email_m:
        contact["email"] = email_m.group()

    phone_m = re.search(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
    if phone_m:
        contact["phone"] = phone_m.group()

    # LinkedIn URL extraction
    linkedin_m = re.search(
        r"(?:linkedin\.com/in/|linkedin\.com/pub/)([\w\-]+)", text, re.IGNORECASE
    )
    if linkedin_m:
        contact["linkedin"] = "www.linkedin.com/in/" + linkedin_m.group(1)

    # City/State location from contact block (first 5 lines); [ ] not \s so
    # the match can't run back across a line break into the name.
    loc_m = re.search(r"\b([A-Z][a-zA-Z ]+,\s*[A-Z]{2})\b|\b(Remote)\b", text)
    if loc_m:
        contact["location"] = (loc_m.group(1) or loc_m.group(2)).strip()

    # Name heuristic: first short, mostly-alphabetic, non-header line(s)
    _skip = re.compile(
        r"@|linkedin|github|http|\.com|\.edu|\.org"
        r"|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}"
        r"|^(work\s+)?experience|^education|^(technical\s+)?skills|^projects?"
        r"|^summary|^objective|^profile|^certifications?"
        r"|^(software|senior|junior|lead|staff|principal|full\s*stack"
        r"|front\s*end|back\s*end)\s*(engineer|developer|architect"
        r"|manager|intern|analyst|scientist|designer)",
        re.IGNORECASE,
    )
    name_parts: list[str] = []
    for ln in [l.strip() for l in text.split("\n")[:12] if l.strip()]:
        if len(ln) > 40 or _skip.search(ln):
            continue
        alpha_ratio = sum(c.isalpha() or c.isspace() for c in ln) / max(len(ln), 1)
        if alpha_ratio > 0.8 and sum(c.isalpha() for c in ln) >= 2:
            if not name_parts:
                name_parts.append(ln)
                if len(ln.split()) >= 2:
                    break
            elif len(name_parts) == 1 and len(name_parts[0].split()) == 1:
                name_parts.append(ln)
                break
            else:
                break
        elif name_parts:
            break

    contact["name"] = " ".join(name_parts)
    return contact


# ─────────────────────────────────────────────────────────────────────────────
# EXPERIENCE PARSER
# ─────────────────────────────────────────────────────────────────────────────

# Common SWE job title patterns
_TITLE_RE = re.compile(
    r"^(?:(?:senior|junior|lead|staff|principal|associate)?\s*"
    r"(?:software|backend|frontend|full\s*stack|data|ml|cloud|devops|platform|"
    r"mobile|web|qa|sre|systems?|application|infrastructure|site\s+reliability|"
    r"software\s+development|teaching|research)?\s*"
    r"(?:engineer(?:ing)?|developer|scientist|architect|analyst|intern|manager|"
    r"programmer|consultant|specialist|designer|administrator|"
    r"associate|technologist|researcher|assistant|fellow))"
    r"|^(?:computer\s+scientist|technology\s+associate)"
    r"|^(?:SDE|SWE|MTS|IC)\b",
    re.IGNORECASE,
)

# Lines that are just a comma-separated tech list (not an achievement)
_TECH_STACK_BULLET_RE = re.compile(
    r"^[•●○▪▸\-–—\*]\s*(?:[A-Za-z0-9#+/.]+(?:\s+[A-Za-z0-9#+/.]+)?,\s*){3,}"
)


def _looks_like_title(text: str) -> bool:
    return (
        len(text) <= 60
        and len(text.split()) <= 7
        and bool(ROLE_WORD_RE.search(text) or _TITLE_RE.match(text))
        and not COMPANY_HINTS_RE.search(text)
    )


def _resolve_entry_header(header_lines: list[str]) -> tuple[str, str, str]:
    """
    Work out (company, title, location) from an entry's header lines.

    Handles every common layout: one line per field in any order
    ("Granite Bank" / dates / "Software Engineer" / "Boston, MA, USA"),
    or a combined "Title | Company" / "Company - Title" line.
    """
    company = title = location = ""
    for line in header_lines:
        text = remove_date_range(line)
        if not text:
            continue
        if is_location_line(text):
            location = location or text
            continue

        parts = ROLE_SEP_RE.split(text, maxsplit=1)
        if len(parts) == 2 and not (title and company) and (
            _looks_like_title(parts[0]) or _looks_like_title(parts[1])
        ):
            t, c = split_role_and_company(text)
            if _looks_like_title(c) and not _looks_like_title(t):
                t, c = c, t
            title, company = title or t, company or c
        elif _looks_like_title(text) and not title:
            title = text
        elif not company:
            company = text
        elif not title:
            title = text

    if not location:
        company, loc1 = extract_location(company)
        title, loc2 = extract_location(title)
        location = loc1 or loc2
    return company, title, location


def parse_experience(section_text: str) -> list[dict]:
    """
    Parse the experience section into structured entries.

    Returns a list of dicts matching:
        {"company": str, "title": str, "dates": str, "location": str, "bullets": [str]}
    """
    if not section_text or not section_text.strip():
        return []

    raw_lines = [ln.strip() for ln in section_text.split("\n") if ln.strip()]
    lines = normalize_bullet_lines(raw_lines)
    lines = merge_continuation_lines(lines)

    # ── Step 1: locate entry boundaries via date lines ──────────────────────
    entry_starts: list[int] = []
    for i, ln in enumerate(lines):
        if DATE_RANGE.search(ln) and not BULLET_INLINE_RE.match(ln):
            start = i
            for lookback in range(1, 4):
                j = i - lookback
                if j < 0:
                    break
                prev = lines[j]
                if BULLET_INLINE_RE.match(prev) or DATE_RANGE.search(prev):
                    break
                if prev.rstrip().endswith((".", "%", ")")):
                    break
                if entry_starts and j <= entry_starts[-1]:
                    break
                start = j
            if not entry_starts or start > entry_starts[-1]:
                entry_starts.append(start)

    if not entry_starts:
        entry_starts = [0]

    # ── Step 2: slice into per-entry blocks ──────────────────────────────────
    blocks: list[list[str]] = []
    for idx, start in enumerate(entry_starts):
        end = entry_starts[idx + 1] if idx + 1 < len(entry_starts) else len(lines)
        blocks.append(lines[start:end])

    # ── Step 3: parse each block ─────────────────────────────────────────────
    parsed: list[dict] = []
    for block in blocks:
        header_lines: list[str] = []
        bullet_lines: list[str] = []
        in_bullets = False

        for ln in block:
            if BULLET_INLINE_RE.match(ln):
                if _TECH_STACK_BULLET_RE.match(ln):
                    continue  # skip pure tech-stack lists
                in_bullets = True
                bullet_lines.append(ln)
            elif in_bullets:
                bullet_lines.append(ln)
            else:
                header_lines.append(ln)

        # Implicit bullet detection for no-bullet résumés
        if not bullet_lines and len(header_lines) > 4:
            real_headers: list[str] = []
            for ln in header_lines:
                has_date = any(DATE_RANGE.search(h) for h in real_headers)
                is_sentence = len(ln) > 40 or ln.rstrip().endswith((".", "%", ")"))
                if is_sentence and has_date:
                    bullet_lines.append(ln)
                else:
                    real_headers.append(ln)
            header_lines = real_headers

        company, title, location = _resolve_entry_header(header_lines)
        bullets = extract_bullets(bullet_lines)

        if company or title or bullets:
            parsed.append(
                {
                    "company": company,
                    "title": title,
                    "dates": extract_date_ranges(" | ".join(header_lines)),
                    "location": location,
                    "bullets": bullets,
                }
            )

    log.info("Parsed %d experience entries", len(parsed))
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# EDUCATION PARSER
# ─────────────────────────────────────────────────────────────────────────────

_DEGREE_KEYWORDS = [
    "Bachelor",
    "Master",
    "B.S.",
    "M.S.",
    "B.A.",
    "M.A.",
    "Ph.D.",
    "PhD",
    "B.Tech",
    "M.Tech",
    "B.E.",
    "M.E.",
    "MBA",
    "Associate",
    "Diploma",
    "BS ",
    "MS ",
    "BA ",
    "MA ",
    "MASTER OF",
    "BACHELOR OF",
    "B.E ",
]

_SCHOOL_HINTS_RE = re.compile(
    r"university|college|institute|school|academy|technology|polytechnic|\bMIT\b|\bIIT\b",
    re.IGNORECASE,
)

_GPA_RE = re.compile(r"C?GPA[:\s]*(\d+\.?\d*)\s*(?:/\s*\d+\.?\d*)?", re.IGNORECASE)

_GRAD_YEAR_RE = re.compile(
    r"(?:Expected|Exp\.?|Graduating|Grad)?\s*:?\s*"
    r"(?:Dec(?:ember)?|May|Jan(?:uary)?|Jun(?:e)?|Sep(?:tember)?|Spring|Fall|Summer|Winter)?\s*"
    r"(\d{4})",
    re.IGNORECASE,
)


_COURSES_RE = re.compile(r"^\s*(?:Relevant\s+)?Course(?:s|work)\s*:\s*(.+)$", re.IGNORECASE)
_GPA_SUFFIX_RE = re.compile(r",?\s*\(?\s*C?GPA\b[^)]*\)?\s*$", re.IGNORECASE)


def _has_degree(line: str) -> bool:
    low = line.lower()
    return any(kw.lower() in low for kw in _DEGREE_KEYWORDS)


def _clean_school(line: str) -> str:
    text = DATE_RANGE.sub("", line)
    return _GPA_SUFFIX_RE.sub("", text).strip(" ,|–—-")


def parse_education(section_text: str) -> list[dict]:
    """
    Parse the education section into structured entries.

    Returns a list of dicts matching:
        {"school": str, "degree": str, "dates": str, "details": [str],
         "courses": str}   # "courses" only when the résumé lists them

    Works whether the school or the degree comes first in each entry. A new
    entry starts when a school or degree line arrives and the current entry
    already has one.
    """
    if not section_text or not section_text.strip():
        return []

    raw_lines = [ln.strip() for ln in section_text.split("\n") if ln.strip()]
    lines = merge_continuation_lines(normalize_bullet_lines(raw_lines))

    entries: list[dict] = []
    current: dict = {}

    def _start_new() -> None:
        nonlocal current
        if current.get("school") or current.get("degree"):
            entries.append(current)
        current = {}

    for ln in lines:
        courses_m = _COURSES_RE.match(ln)
        if courses_m:
            current["courses"] = courses_m.group(1).strip()
            continue
        if BULLET_INLINE_RE.match(ln) or is_location_line(ln):
            continue

        gpa_m = _GPA_RE.search(ln)
        dates = extract_date_range(ln)
        year_m = _GRAD_YEAR_RE.search(ln)

        # Parenthetical metadata line "(Grad: Dec 2027 | GPA: 3.83)"
        if ln.startswith("(") and not _has_degree(ln):
            pass
        elif _has_degree(ln):
            if current.get("degree"):
                _start_new()
            # "School | Degree | City, ST | 2020" in any order: classify each part.
            parts = [s.strip() for s in ROLE_SEP_RE.split(ln) if s.strip()]
            degree = next((s for s in parts if _has_degree(s)), ln)
            others = [
                s for s in parts
                if s != degree and not is_location_line(s) and not _GRAD_YEAR_RE.fullmatch(s)
                and not DATE_RANGE.fullmatch(s)
            ]
            school = next((s for s in others if _SCHOOL_HINTS_RE.search(s)), others[0] if others else "")
            current["degree"] = _GPA_SUFFIX_RE.sub("", DATE_RANGE.sub("", degree)).strip(" ,|–—-")
            if school and not current.get("school"):
                current["school"] = _clean_school(school)
        elif _SCHOOL_HINTS_RE.search(ln) or (
            not current.get("school") and not (dates or gpa_m or year_m)
        ):
            if current.get("school"):
                _start_new()
            school = _clean_school(ln)
            if school:
                current["school"] = school

        if gpa_m and not current.get("gpa"):
            current["gpa"] = gpa_m.group(1)
        if not current.get("dates"):
            if dates:
                current["dates"] = dates
            elif year_m and (ln.startswith("(") or _has_degree(ln)):
                current["dates"] = year_m.group(0).strip()

    _start_new()

    result: list[dict] = []
    for e in entries:
        entry = {
            "school": e.get("school", ""),
            "degree": e.get("degree", ""),
            "dates": e.get("dates", ""),
            "details": [f"GPA: {e['gpa']}"] if e.get("gpa") else [],
        }
        if e.get("courses"):
            entry["courses"] = e["courses"]
        result.append(entry)

    log.info("Parsed %d education entries", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PROJECTS PARSER
# ─────────────────────────────────────────────────────────────────────────────

_TECH_STACK_HEADER_RE = re.compile(r"^Tech\s+Stack\s*:", re.IGNORECASE)
_INLINE_PROJECT_RE = re.compile(r"^[•●○▪▸\-–—\*]\s+(.+?)\s*(?:\(\d{4}\))?\s*:\s+(.+)$")


# Link labels that trail a project name: "(GitHub)", "(Demo | Frontend | Backend)"
_LINK_PAREN_RE = re.compile(
    r"\s*\((?:[^)]*\b(?:github|link|demo|live|code|repo|website|frontend|backend)\b[^)]*)\)",
    re.IGNORECASE,
)


def _split_project_header(header: str) -> tuple[str, str, list[str]]:
    """
    "ResumeAI | AI Resume Platform | Python, FastAPI (GitHub)"
        → ("ResumeAI", "AI Resume Platform", ["Python", "FastAPI"])

    The last part counts as a tech stack only when it is a comma list.
    """
    header = _LINK_PAREN_RE.sub("", header)
    parts = split_outside_parens(re.sub(r"\s+[–—]\s+", "|", header), separators="|")
    if not parts:
        return "", "", []
    name, rest = parts[0], parts[1:]
    technologies: list[str] = []
    if rest and "," in rest[-1]:
        technologies = split_outside_parens(rest.pop(), separators=",")
    return name, " | ".join(rest), technologies


def parse_projects(section_text: str) -> list[dict]:
    """
    Parse the projects section into structured entries.

    Returns a list of dicts matching:
        {"name": str, "description": str, "technologies": [str], "bullets": [str]}
    """
    if not section_text or not section_text.strip():
        return []

    raw_lines = [ln.strip() for ln in section_text.split("\n") if ln.strip()]
    lines = normalize_bullet_lines(raw_lines)
    lines = merge_continuation_lines(lines)

    # Remove stop-section headers and tech-stack labels
    clean: list[str] = []
    for ln in lines:
        if STOP_SECTIONS_RE.match(ln):
            break
        if _TECH_STACK_HEADER_RE.match(ln):
            continue
        clean.append(ln)
    lines = clean

    # ── Entry boundary detection ─────────────────────────────────────────────
    entry_starts: list[int] = []

    # Primary: lines with date ranges
    for i, ln in enumerate(lines):
        if DATE_RANGE.search(ln) and not BULLET_INLINE_RE.match(ln):
            start = i
            for lookback in range(1, 3):
                j = i - lookback
                if j < 0:
                    break
                prev = lines[j]
                if BULLET_INLINE_RE.match(prev) or DATE_RANGE.search(prev):
                    break
                if prev.rstrip().endswith((".", "%", ")")):
                    break
                if entry_starts and j <= entry_starts[-1]:
                    break
                start = j
            if not entry_starts or start > entry_starts[-1]:
                entry_starts.append(start)

    # Fallback: separator-based header (e.g. "Role | Company | Dates")
    if not entry_starts:
        _sep = re.compile(r"\s+[|–—]\s+")
        for i, ln in enumerate(lines):
            if not BULLET_INLINE_RE.match(ln) and _sep.search(ln):
                entry_starts.append(i)

    # Fallback: inline bullet format "• Name (2023): description"
    if not entry_starts:
        inline: list[dict] = []
        for ln in lines:
            m = _INLINE_PROJECT_RE.match(ln)
            if m:
                proj_name = m.group(1).strip()
                proj_desc = m.group(2).strip()
                inline.append(
                    {
                        "name": proj_name,
                        "description": "",
                        "technologies": [],
                        "bullets": [proj_desc] if len(proj_desc) > 15 else [],
                    }
                )
        if inline:
            log.info("Parsed %d inline project entries", len(inline))
            return inline
        entry_starts = [0]

    # ── Slice and parse each block ───────────────────────────────────────────
    blocks: list[list[str]] = []
    for idx, start in enumerate(entry_starts):
        end = entry_starts[idx + 1] if idx + 1 < len(entry_starts) else len(lines)
        blocks.append(lines[start:end])

    parsed: list[dict] = []
    for block in blocks:
        header_lines: list[str] = []
        description_lines: list[str] = []
        bullet_lines: list[str] = []
        in_bullets = False

        for ln in block:
            if BULLET_INLINE_RE.match(ln):
                in_bullets = True
                bullet_lines.append(ln)
            elif in_bullets:
                bullet_lines.append(ln)
            elif not header_lines or DATE_RANGE.search(ln):
                header_lines.append(ln)
            else:
                description_lines.append(ln)

        header_text = " ".join(header_lines)
        header_clean = DATE_RANGE.sub("", header_text).strip().rstrip("–—- ").strip()
        name, subtitle, technologies = _split_project_header(header_clean)

        description = " ".join(description_lines).strip() or subtitle
        bullets = extract_bullets(bullet_lines)

        # No-bullet projects: long description lines become bullets
        if not bullets and description_lines:
            implicit: list[str] = []
            for dl in description_lines:
                if dl.rstrip().endswith((".", "%", ")")) and len(dl) > 40:
                    implicit.append(dl)
            if implicit:
                bullets = implicit
                description = subtitle

        if name and (bullets or description):
            parsed.append(
                {
                    "name": name,
                    "description": description,
                    "technologies": technologies,
                    "bullets": bullets,
                }
            )

    log.info("Parsed %d project entries", len(parsed))
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# SKILLS SECTION PARSER
# ─────────────────────────────────────────────────────────────────────────────

# "Languages: Python, Go" or a label alone on its line ("Languages:") with the
# items on the next line. Matched per line so a label never swallows the last
# item of the line above it.
_SKILL_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 &/+.\-]{0,40}?)\s*:\s*(.*)$")

# Labels inside a skills block that hold something other than skills.
_NON_SKILL_LABEL_RE = re.compile(
    r"^(?:certifications?|certificates?|licenses?|profiles?|links?|interests?"
    r"|hobbies|awards?|achievements?|honou?rs?|spoken\s+languages?)$",
    re.IGNORECASE,
)
_CERT_LABEL_RE = re.compile(r"^(?:certifications?|certificates?|licenses?)$", re.IGNORECASE)

_PAREN_GROUP_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")


def _group_skill_lines(section_text: str) -> list[tuple[str, str]]:
    """
    Collapse the skills block into (label, items_text) groups.

    Unlabelled lines continue the group above. A line that ends in "," or "-"
    was wrapped mid-list and is joined without inserting a separator.
    """
    groups: list[list[str]] = []
    for raw in section_text.split("\n"):
        line = raw.strip().strip("•●▪").strip()
        if not line:
            continue
        m = _SKILL_LABEL_RE.match(line)
        if m and len(m.group(1).split()) <= 5:
            groups.append([m.group(1).strip(), m.group(2).strip()])
            continue
        if not groups:
            groups.append(["", line])
            continue
        prev = groups[-1][1]
        if not prev:
            groups[-1][1] = line
        elif prev.endswith("-"):
            groups[-1][1] = prev + line
        elif prev.endswith(","):
            groups[-1][1] = f"{prev} {line}"
        else:
            groups[-1][1] = f"{prev}, {line}"
    return [(label, text) for label, text in groups if text]


def _skill_items(items_text: str) -> list[str]:
    items = []
    for item in split_outside_parens(items_text):
        item = item.strip().strip("•-–— ").strip()
        if len(item) > 1 or item in {"C", "R"}:
            items.append(item)
    return items


def parse_skills_block(section_text: str) -> tuple[list[dict], dict[str, str]]:
    """
    Parse the skills section.

    Returns:
        categories: [{"category": str, "skills": [str]}] in résumé order, with
                    each item exactly as written ("AWS (EC2, S3)").
        other:      non-skill lines found inside the block, keyed by label
                    (e.g. {"Certifications": "Meta Front-End Developer, ..."}).
    """
    categories: list[dict] = []
    other: dict[str, str] = {}
    if not section_text or not section_text.strip():
        return categories, other

    for label, text in _group_skill_lines(section_text):
        if label and _NON_SKILL_LABEL_RE.match(label):
            other[label] = text
            continue
        items = _skill_items(text)
        if items:
            categories.append({"category": label or "Skills", "skills": items})

    log.info(
        "Parsed %d skill categories (%d skills)",
        len(categories),
        sum(len(c["skills"]) for c in categories),
    )
    return categories, other


def flatten_skills(categories: list[dict]) -> list[str]:
    """
    One flat, deduplicated list of individual skills.

    A parenthesised list is expanded so each part can be matched on its own:
    "AWS (EC2, S3)" → "AWS", "EC2", "S3". A non-list qualifier is dropped:
    "Python (advanced)" → "Python".
    """
    flat: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = name.strip()
        key = canonical_skill(name).lower()
        if name and key not in seen:
            seen.add(key)
            flat.append(name)

    for cat in categories:
        for item in cat["skills"]:
            m = _PAREN_GROUP_RE.match(item)
            if not m:
                _add(item)
                continue
            _add(m.group(1))
            inner = split_outside_parens(m.group(2))
            if len(inner) > 1:
                for sub in inner:
                    _add(sub)
    return flat


# ─────────────────────────────────────────────────────────────────────────────
# ALL-SKILLS AGGREGATION
# ─────────────────────────────────────────────────────────────────────────────


def _aggregate_all_skills(
    skills_section: list[str],
    experience: list[dict],
    projects: list[dict],
) -> list[str]:
    """
    Every skill the résumé evidences, in canonical spelling, from:
      - the skills section (each entry, plus vocabulary terms inside it,
        so "Linux/Unix Terminal" also yields "Linux" and "Unix")
      - vocabulary matches in experience bullets
      - vocabulary matches in project bullets, descriptions and tech stacks
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(items: list[str]) -> None:
        for s in items:
            canon = canonical_skill(s)
            if canon.lower() not in seen:
                seen.add(canon.lower())
                result.append(canon)

    # Skills section first (highest signal)
    for skill in skills_section:
        _add([skill])
        _add(extract_skills(skill))

    _add(extract_skills(" ".join(b for e in experience for b in e.get("bullets", []))))

    project_text = " ".join(
        part
        for p in projects
        for part in [p.get("description", ""), *p.get("bullets", []), *p.get("technologies", [])]
        if part
    )
    _add(extract_skills(project_text))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def parse_resume(file_path: str) -> dict:
    """
    Parse a résumé PDF into the Stage 1 → Stage 2 JSON contract.

    Returns:
        {
          "contact": {"name", "email", "phone", "linkedin", "location"},
          "sections": {
            "experience":         [{"company", "title", "dates", "location", "bullets"}],
            "education":          [{"school", "degree", "dates", "details", "courses"?}],
            "skills":             [str],     # flat, one entry per skill
            "skills_categorized": [{"category": str, "skills": [str]}],
            "projects":           [{"name", "description", "technologies", "bullets"}],
          },
          "extra_sections": {"publications" | "leadership" | "achievements"
                             | "certifications": raw text},
          "all_skills_detected": [str],  # canonical names, for matching
        }

    "projects" also includes any OPEN SOURCE section entries.

    Raises:
        FileNotFoundError: if the PDF does not exist.
        ValueError:        if the PDF contains no extractable text.
        ImportError:       if PyMuPDF is not installed.
    """
    raw_text = extract_text_from_pdf(file_path)
    sections = classify_sections(raw_text)

    contact = extract_contact_info(sections.get("contact", raw_text))

    experience = parse_experience(sections.get("experience", ""))
    education = parse_education(sections.get("education", ""))
    projects = parse_projects(sections.get("projects", "")) + parse_projects(
        sections.get("open_source", "")
    )
    skills_categorized, skills_other = parse_skills_block(sections.get("skills", ""))
    skills = flatten_skills(skills_categorized)

    extra_sections = {k: sections[k] for k in EXTRA_SECTIONS if k in sections}
    # An inline "Certifications: ..." line inside the skills block.
    if "certifications" not in extra_sections:
        certs = [t for label, t in skills_other.items() if _CERT_LABEL_RE.match(label)]
        if certs:
            extra_sections["certifications"] = "\n".join(
                f"• {c}" for t in certs for c in split_outside_parens(t, separators=",;")
            )

    all_skills = _aggregate_all_skills(skills, experience, projects)

    result = {
        "contact": contact,
        "sections": {
            "experience": experience,
            "education": education,
            "skills": skills,
            "skills_categorized": skills_categorized,
            "projects": projects,
        },
        "extra_sections": extra_sections,
        "all_skills_detected": all_skills,
    }

    log.info(
        "parse_resume complete — contact=%s, exp=%d, edu=%d, proj=%d, skills=%d, all_skills=%d",
        contact.get("name", "?"),
        len(experience),
        len(education),
        len(projects),
        len(skills),
        len(all_skills),
    )
    return result
