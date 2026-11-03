"""
resume_parser.py — Structured résumé parser for the ResumeAI pipeline.

Public API:
    parse_resume(file_path: str) -> dict

The returned dict strictly matches the Person-1 → Person-2 JSON contract:

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
    DATE_RANGE,
    BULLET_INLINE_RE,
    COMPANY_HINTS_RE,
    ROLE_SEP_RE,
    STOP_SECTIONS_RE,
    extract_bullets,
    extract_date_range,
    extract_location,
    extract_skills,
    extract_text_from_pdf,
    merge_continuation_lines,
    normalize_bullet_lines,
    remove_date_range,
    split_role_and_company,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "summary",
        re.compile(
            r"^(professional\s+)?summary|^(career\s+)?objective|^profile|^about(\s+me)?",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "experience",
        re.compile(
            r"^(work\s+)?experience|^employment|^work\s+history|^professional\s+experience",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "education",
        re.compile(
            r"^education(al)?(\s+background)?|^academic|^qualifications",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "skills",
        re.compile(
            r"^(technical\s+)?skills|^core\s+competencies|^technologies"
            r"|^proficiencies|^technical\s+toolkit|^tech\s+stack"
            r"|^areas\s+of\s+expertise|^competencies",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "projects",
        re.compile(
            r"^projects?|^project\s+work|^personal\s+projects?|^key\s+projects?|^portfolio",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "certifications",
        re.compile(
            r"^certifications?|^licenses?(\s+&\s+certifications?)?|^credentials"
            r"|^awards?\s*(and|&)\s*cert|^awards?",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
]


def classify_sections(text: str) -> dict[str, str]:
    """
    Split résumé text into labeled sections.

    Returns a dict mapping section name → section text.
    Always includes "full_text" and "contact" keys.
    """
    lines = text.split("\n")
    sections: dict[str, str] = {"full_text": text}

    # Treat first ~5 non-empty lines as contact block
    contact_lines = [ln.strip() for ln in lines[:12] if ln.strip()]
    sections["contact"] = "\n".join(contact_lines[:5])

    boundaries: list[tuple[int, str]] = []
    seen: set[str] = set()

    for line_num, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        # Section headers don't end with sentence punctuation
        if stripped.endswith((".", "!", "?", ",")):
            continue
        if len(stripped) > 35 and not stripped.isupper():
            continue

        for section_name, pattern in _SECTION_PATTERNS:
            if pattern.search(stripped) and section_name not in seen:
                boundaries.append((line_num, section_name))
                seen.add(section_name)
                break

    for i, (line_num, section_name) in enumerate(boundaries):
        start = line_num + 1
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            sections[section_name] = body

    log.info("Sections classified: %s", list(sections.keys()))
    return sections


# ─────────────────────────────────────────────────────────────────────────────
# CONTACT EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────


def extract_contact_info(text: str) -> dict[str, str]:
    """
    Extract name, email, and phone from the top of the résumé text.

    Returns {"name": str, "email": str, "phone": str}.
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

    # City/State location from contact block (first 5 lines)
    loc_m = re.search(r"\b([A-Z][a-zA-Z\s]+,\s*[A-Z]{2})\b|\b(Remote)\b", text)
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
        title_after_date = ""

        for idx_ln, ln in enumerate(block):
            if BULLET_INLINE_RE.match(ln):
                if _TECH_STACK_BULLET_RE.match(ln):
                    continue  # skip pure tech-stack lists
                in_bullets = True
                bullet_lines.append(ln)
            elif in_bullets:
                bullet_lines.append(ln)
            elif DATE_RANGE.search(ln):
                header_lines.append(ln)
                if idx_ln + 1 < len(block):
                    nxt = block[idx_ln + 1].strip()
                    if (
                        _TITLE_RE.match(nxt)
                        and not BULLET_INLINE_RE.match(nxt)
                        and len(nxt) < 60
                    ):
                        title_after_date = nxt
            elif title_after_date and ln.strip() == title_after_date:
                continue  # already captured
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

        header_text = " | ".join(header_lines)
        dates = extract_date_range(header_text)

        company = title = location = ""

        # Filter out standalone location lines
        clean_headers: list[str] = []
        for h in header_lines:
            h_clean = remove_date_range(h)
            if not h_clean:
                continue
            _, loc = extract_location(h_clean)
            remaining = (
                re.sub(
                    r",?\s*([A-Z][a-zA-Z\s]+,\s*[A-Z]{2})\s*$|,?\s*(Remote)\s*$",
                    "",
                    h_clean,
                    flags=re.IGNORECASE,
                )
                .strip()
                .rstrip("|,–-—")
                .strip()
            )
            if loc and not remaining:
                location = loc
            else:
                clean_headers.append(h_clean)

        if len(clean_headers) >= 2:
            line1, line2 = clean_headers[0], clean_headers[1]
            if ROLE_SEP_RE.search(line1):
                title, company = split_role_and_company(line1)
            elif ROLE_SEP_RE.search(line2):
                title, company = split_role_and_company(line2)
                if not company:
                    company = line1
            else:
                if COMPANY_HINTS_RE.search(line2) and not COMPANY_HINTS_RE.search(
                    line1
                ):
                    title, company = line1, line2
                elif COMPANY_HINTS_RE.search(line1) and not COMPANY_HINTS_RE.search(
                    line2
                ):
                    title, company = line2, line1
                else:
                    title, company = line1, line2  # default
        elif len(clean_headers) == 1:
            line1 = clean_headers[0]
            if ROLE_SEP_RE.search(line1):
                title, company = split_role_and_company(line1)
            else:
                company = line1

        if not location:
            company, loc1 = extract_location(company)
            title, loc2 = extract_location(title)
            location = loc1 or loc2

        if title_after_date:
            if not title:
                title = title_after_date
            elif not company:
                company = title_after_date

        bullets = extract_bullets(bullet_lines)

        if company or title or bullets:
            parsed.append(
                {
                    "company": company,
                    "title": title,
                    "dates": dates,
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


def parse_education(section_text: str) -> list[dict]:
    """
    Parse the education section into structured entries.

    Returns a list of dicts matching:
        {"school": str, "degree": str, "dates": str, "details": [str]}

    GPA, coursework, and other metadata go into details[].
    """
    if not section_text or not section_text.strip():
        return []

    raw_lines = [ln.strip() for ln in section_text.split("\n") if ln.strip()]
    lines = normalize_bullet_lines(raw_lines)
    lines = merge_continuation_lines(lines)

    entries: list[dict] = []
    pending_gpa = ""
    pending_year = ""

    def _new_entry() -> dict:
        return {"school": "", "degree": "", "year": "", "gpa": ""}

    current = _new_entry()

    for ln in lines:
        if BULLET_INLINE_RE.match(ln):
            continue

        gpa_m = _GPA_RE.search(ln)
        has_degree = any(kw.lower() in ln.lower() for kw in _DEGREE_KEYWORDS)
        year_m = _GRAD_YEAR_RE.search(ln)
        date_range = extract_date_range(ln)

        # Parenthetical metadata line "(Grad: Dec 2027 | GPA: 3.83)"
        if re.match(r"^\s*\(", ln) and not has_degree:
            if gpa_m:
                pending_gpa = gpa_m.group(1)
            if year_m:
                pending_year = year_m.group(0).strip()
            continue

        if re.match(r"^\s*Courses?:", ln, re.IGNORECASE):
            continue

        if has_degree:
            if current["degree"]:
                entries.append(current)
                current = _new_entry()

            if pending_gpa:
                current["gpa"] = pending_gpa
                pending_gpa = ""
            if pending_year:
                current["year"] = pending_year
                pending_year = ""

            if ROLE_SEP_RE.search(ln):
                parts = ROLE_SEP_RE.split(ln, maxsplit=1)
                degree_part = parts[0].strip()
                school_part = parts[1].strip() if len(parts) > 1 else ""
                school_part = DATE_RANGE.sub("", school_part).strip()
                school_part = (
                    re.sub(r"\(C?GPA[^)]*\)", "", school_part)
                    .strip()
                    .rstrip(",")
                    .strip()
                )
                current["degree"] = degree_part
                current["school"] = school_part
            else:
                current["degree"] = ln

            if gpa_m and not current["gpa"]:
                current["gpa"] = gpa_m.group(1)
            if date_range and not current["year"]:
                current["year"] = date_range
            elif year_m and not current["year"]:
                current["year"] = year_m.group(0).strip()

        elif current["degree"]:
            _, loc = extract_location(ln)
            if date_range and not current["year"]:
                current["year"] = date_range
            elif year_m and not current["year"]:
                current["year"] = year_m.group(0).strip()
            elif gpa_m and not current["gpa"]:
                current["gpa"] = gpa_m.group(1)
            elif loc and not ln.replace(loc, "").strip():
                pass  # pure location — skip for education
            elif _SCHOOL_HINTS_RE.search(ln) and not current["school"]:
                school_clean = DATE_RANGE.sub("", ln).strip()
                school_clean = (
                    re.sub(r"\(C?GPA[^)]*\)", "", school_clean)
                    .strip()
                    .rstrip(",")
                    .strip()
                )
                current["school"] = school_clean
            elif not current["school"] and not date_range:
                if current["degree"] and len(current["degree"]) < 10:
                    current["degree"] = current["degree"] + " " + ln
                elif not current["school"]:
                    current["school"] = ln
        else:
            if date_range and not current["year"]:
                current["year"] = date_range
            elif year_m and not current["year"]:
                current["year"] = year_m.group(0).strip()
            elif not current["school"]:
                current["school"] = ln

    if current["school"] or current["degree"]:
        entries.append(current)

    # Convert internal format → contract format
    result: list[dict] = []
    for e in entries:
        details: list[str] = []
        if e.get("gpa"):
            details.append(f"GPA: {e['gpa']}")
        result.append(
            {
                "school": e.get("school", ""),
                "degree": e.get("degree", ""),
                "dates": e.get("year", ""),
                "details": details,
            }
        )

    log.info("Parsed %d education entries", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PROJECTS PARSER
# ─────────────────────────────────────────────────────────────────────────────

_TECH_STACK_HEADER_RE = re.compile(r"^Tech\s+Stack\s*:", re.IGNORECASE)
_INLINE_PROJECT_RE = re.compile(r"^[•●○▪▸\-–—\*]\s+(.+?)\s*(?:\(\d{4}\))?\s*:\s+(.+)$")


def parse_projects(section_text: str) -> list[dict]:
    """
    Parse the projects section into structured entries.

    Returns a list of dicts matching:
        {"name": str, "description": str, "bullets": [str]}
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

    # Fallback: separator-based (Anurag format)
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

        sep_parts = re.split(r"\s+[|–—]\s+", header_clean)
        name = sep_parts[0].strip() if sep_parts else header_clean
        name = re.sub(r"\s*\(Link\)\s*", "", name).strip()
        name = re.sub(r"\s*\([^)]*Github[^)]*\)", "", name, flags=re.IGNORECASE).strip()

        description = " ".join(description_lines).strip()
        bullets = extract_bullets(bullet_lines)

        # No-bullet projects: long description lines become bullets
        if not bullets and description_lines:
            implicit: list[str] = []
            for dl in description_lines:
                if dl.rstrip().endswith((".", "%", ")")) and len(dl) > 40:
                    implicit.append(dl)
            if implicit:
                bullets = implicit
                description = ""

        if name and (bullets or description):
            parsed.append(
                {
                    "name": name,
                    "description": description,
                    "bullets": bullets,
                }
            )

    log.info("Parsed %d project entries", len(parsed))
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# SKILLS SECTION PARSER
# ─────────────────────────────────────────────────────────────────────────────


def parse_skills_section(section_text: str) -> list[str]:
    """
    Parse the skills section into a flat list of individual skill strings.

    Handles category labels with or without colons:
        "Languages: Python, Java"
        "Frameworks & Libraries: React, Django"
        "Frameworks & React, Next.js"   (malformed — no colon)
    """
    if not section_text or not section_text.strip():
        return []

    # Strip category labels WITH colons
    cleaned = re.sub(
        r"(?:[A-Z][A-Za-z]*(?:\s+[A-Za-z]+)*)"
        r"(?:\s*[&/]\s*(?:[A-Z][A-Za-z]*(?:\s+[A-Za-z]+)*))?",
        lambda m: "" if m.group(0).rstrip().endswith(":") else m.group(0),
        section_text,
    )
    # Simpler approach — direct colon removal
    cleaned = re.sub(
        r"(?:[A-Z][A-Za-z]*(?:\s+[A-Za-z]+)*)"
        r"(?:\s*[&/]\s*(?:[A-Z][A-Za-z]*(?:\s+[A-Za-z]+)*))?"
        r"\s*:\s*",
        "",
        section_text,
    )

    # Strip known category labels WITHOUT colons (start of line)
    cleaned = re.sub(
        r"^(?:Languages?|Programming\s+Languages?|Frameworks?|Tools?|"
        r"Technologies|Databases?|Platforms?|Libraries|DevOps|Cloud|"
        r"Other\s+Skills?|Software|Hardware|Web(?:\s+Development)?|"
        r"Mobile|Backend|Frontend|Data|Infrastructure|Concepts?|"
        r"Core\s+Competencies)"
        r"(?:\s*[&/]\s*"
        r"(?:Languages?|Frameworks?|Tools?|Technologies|Databases?|"
        r"Platforms?|Libraries|DevOps|Cloud|Other|Software|Hardware|"
        r"Web|Mobile|Backend|Frontend|Data|Infrastructure|ML|AI|Concepts?))?",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    skills: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[,|•●;]\s*|\n", cleaned):
        s = token.strip().strip("•-–— ")
        s = re.sub(r"^[&/]\s*", "", s).strip()
        if s and len(s) > 1 and s.lower() not in seen:
            seen.add(s.lower())
            skills.append(s)

    log.info("Parsed %d skills from skills section", len(skills))
    return skills


# ─────────────────────────────────────────────────────────────────────────────
# ALL-SKILLS AGGREGATION
# ─────────────────────────────────────────────────────────────────────────────


def _aggregate_all_skills(
    skills_section: list[str],
    experience: list[dict],
    projects: list[dict],
) -> list[str]:
    """
    Union of skills from:
      - skills section (raw strings)
      - vocabulary matches in experience bullets
      - vocabulary matches in project bullets/descriptions

    Returns deduplicated, canonically-cased list.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(items: list[str]) -> None:
        for s in items:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                result.append(s)

    # Skills section first (highest signal)
    _add(skills_section)

    # Vocabulary-matched skills from experience bullets
    all_exp_text = " ".join(b for entry in experience for b in entry.get("bullets", []))
    _add(extract_skills(all_exp_text))

    # Vocabulary-matched skills from projects
    all_proj_text = " ".join(
        b
        for entry in projects
        for b in ([entry.get("description", "")] + entry.get("bullets", []))
        if b
    )
    _add(extract_skills(all_proj_text))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORIZED SKILLS PARSER  (preserves "Label: skill1, skill2" structure)
# ─────────────────────────────────────────────────────────────────────────────


def parse_skills_section_categorized(section_text: str) -> list[dict]:
    """
    Parse the skills section preserving category labels.

    Returns a list of dicts: [{"category": str, "skills": [str]}, ...]
    Falls back to a single "Skills" category if no labels are detected.
    """
    if not section_text or not section_text.strip():
        return []

    categories: list[dict] = []
    _CAT_LINE = re.compile(r"^([A-Za-z][A-Za-z\s&/]+):\s*(.*)$")

    for line in section_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _CAT_LINE.match(line)
        if m:
            cat_name = m.group(1).strip()
            skills_str = m.group(2).strip()
            skills = [s.strip() for s in re.split(r"[,|;]", skills_str) if s.strip()]
            if skills:
                categories.append({"category": cat_name, "skills": skills})
        elif categories:
            # continuation line — append skills to last category
            extra = [s.strip() for s in re.split(r"[,|;]", line) if s.strip()]
            categories[-1]["skills"].extend(extra)

    if not categories:
        # No category labels found — return flat as single group
        flat = [s.strip() for s in re.split(r"[,|;\n]", section_text) if s.strip()]
        if flat:
            categories = [{"category": "Skills", "skills": flat}]

    return categories


# ─────────────────────────────────────────────────────────────────────────────
# EXTRA SECTIONS PARSER  (publications, leadership, achievements, certifications)
# ─────────────────────────────────────────────────────────────────────────────

_EXTRA_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "publications",
        re.compile(
            r"^(research\s*(&|and)\s*)?publications?|^research$",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "leadership",
        re.compile(
            r"^leadership(\s*(and|&)\s*teaching)?|^teaching\s+experience",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "achievements",
        re.compile(
            r"^achievements?|^extracurricular|^honors?|^awards?",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "certifications",
        re.compile(
            r"^certifications?|^licenses?",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
]


def parse_extra_sections(raw_text: str) -> dict[str, str]:
    """
    Extract extra resume sections (publications, leadership, achievements)
    as raw text blocks keyed by section name.
    """
    lines = raw_text.split("\n")
    result: dict[str, str] = {}
    boundaries: list[tuple[int, str]] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        if stripped.endswith((".", "!", "?", ",")):
            continue
        for section_name, pattern in _EXTRA_SECTION_PATTERNS:
            if pattern.search(stripped) and section_name not in seen:
                boundaries.append((i, section_name))
                seen.add(section_name)
                break

    for idx, (line_num, section_name) in enumerate(boundaries):
        start = line_num + 1
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            result[section_name] = body

    return result


# ─────────────────────────────────────────────────────────────────────────────
# COURSES EXTRACTOR  (from education section text)
# ─────────────────────────────────────────────────────────────────────────────


def extract_courses_from_education_text(section_text: str) -> dict[str, str]:
    """
    Extract "Courses: ..." lines and associate them with the most recent
    degree entry found before the courses line.
    Returns {degree_keyword: courses_string}.
    """
    courses: dict[str, str] = {}
    lines = [l.strip() for l in section_text.split("\n") if l.strip()]
    last_degree = ""

    for line in lines:
        # Detect degree lines
        if any(
            kw.lower() in line.lower()
            for kw in [
                "Bachelor",
                "Master",
                "B.S.",
                "M.S.",
                "B.E",
                "M.E",
                "B.Tech",
                "M.Tech",
                "Associate",
                "Diploma",
                "BS ",
                "MS ",
                "MASTER",
                "BACHELOR",
            ]
        ):
            last_degree = line[:60]

        # Detect course lines
        m = re.search(r"Courses?\s*:\s*(.+)", line, re.IGNORECASE)
        if m and last_degree:
            courses[last_degree] = m.group(1).strip()

    return courses


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def parse_resume(file_path: str) -> dict:
    """
    Parse a résumé PDF into the Person-1 → Person-2 JSON contract.

    Args:
        file_path: Absolute or relative path to the PDF file.

    Returns:
        {
          "contact": {"name": str, "email": str, "phone": str},
          "sections": {
            "experience": [...],
            "education":  [...],
            "skills":     [...],
            "projects":   [...]
          },
          "all_skills_detected": [...]
        }

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
    projects = parse_projects(sections.get("projects", ""))
    skills = parse_skills_section(sections.get("skills", ""))
    skills_categorized = parse_skills_section_categorized(sections.get("skills", ""))

    # Courses per degree from education section text
    courses_map = extract_courses_from_education_text(sections.get("education", ""))
    for edu_entry in education:
        for degree_key, courses_str in courses_map.items():
            if (
                edu_entry.get("degree", "")[:40].lower() in degree_key.lower()
                or degree_key.lower() in edu_entry.get("degree", "").lower()
            ):
                edu_entry["courses"] = courses_str
                break

    # Extra sections: publications, leadership, achievements
    extra_sections = parse_extra_sections(raw_text)

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
