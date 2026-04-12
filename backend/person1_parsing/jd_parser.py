"""
jd_parser.py — Structured Job Description parser for the ResumeAI pipeline.

Public API:
    parse_jd(text: str) -> dict

The returned dict strictly matches the Person-1 → Person-2 JSON contract:

    {
      "title": str,
      "company": str,
      "requirements": {
        "required_skills":      [str, ...],
        "preferred_skills":     [str, ...],
        "experience_years":     int | None,
        "requirement_sentences": [
          {"text": str, "type": "required" | "preferred"}
        ]
      },
      "raw_text": str
    }

Architecture:
    Step 1  Normalize (handle LinkedIn single-line pastes)
    Step 2  Extract title + company (heuristic, best-effort)
    Step 3  Extract experience_years
    Step 4  Zone-based line classification (required / preferred / skip)
    Step 5  Fallback if no zones detected
    Step 6  Per-zone skill extraction + deduplication
    Step 7  Build requirement_sentences with type tags
    Step 8  Assemble final dict
"""

from __future__ import annotations

import logging
import re

from .utils import BULLET_INLINE_RE, extract_skills

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ZONE HEADER PATTERNS  (standalone header lines — full line = header)
# ─────────────────────────────────────────────────────────────────────────────

_RESPONSIBILITIES_HEADER = re.compile(
    r"^\s*(?:"
    r"Responsibilities"
    r"|What\s+you'?(?:ll|'ll)\s+do"
    r"|What\s+You\s+Will\s+Do"
    r"|Key\s+Responsibilities"
    r"|Your\s+(?:Role|Responsibilities|Impact)"
    r"|The\s+Role"
    r"|Job\s+Duties"
    r"|Day\s+to\s+Day"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

_REQUIRED_HEADER = re.compile(
    r"^\s*(?:"
    r"(?:Minimum\s+)?Requirements?"
    r"|(?:Minimum|Basic|Required)\s+Qualifications?"
    r"|Required\s+(?:Skills?|Technical\s+Skills?|Soft\s+Skills?)"
    r"|Must\s+Have"
    r"|Who\s+You\s+Are"
    r"|What\s+(?:We'?re|You'?re)\s+Looking\s+For"
    r"|What\s+(?:We|You)\s+Need(?:\s+To\s+Succeed)?"
    r"|What\s+You\s+(?:Bring|Need|Need\s+To\s+Succeed)"
    r"|Qualifications?"
    r"|Minimum\s+Qualifications?"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

_PREFERRED_HEADER = re.compile(
    r"^\s*(?:"
    r"(?:Preferred|Desired|Additional|Bonus)\s+(?:Qualifications?|Skills?|Requirements?)"
    r"|Nice\s+to\s+Have"
    r"|Nice\s+to\s+Haves?"
    r"|What\s+(?:Sets\s+You\s+Apart|Would\s+Be\s+Nice)"
    r"|(?:A\s+)?(?:Plus|Bonus)"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

_SKIP_HEADER = re.compile(
    r"^\s*(?:"
    r"About\s+(?:the\s+)?(?:Job|Role|Team|Company|Us|Stripe|Tinder|Adobe|Intel|PayPal)"
    r"|About\s+[A-Z][A-Za-z]+"          # "About Stripe", "About Tinder", etc.
    r"|Who\s+We\s+Are"
    r"|Our\s+Mission"
    r"|Company\s+(?:Overview|Description)"
    r"|Program\s+Duration"
    r"|Where\s+(?:you'?(?:ll|'ll)\s+work|You'?(?:ll|'ll)\s+Work)"
    r"|In-?\s*[Oo]ffice\s+[Ee]xpectations?"
    r"|Pay\s+and\s+[Bb]enefits?"
    r"|Subsidiary"
    r"|Benefits?|Compensation|Salary"
    r"|Commitment\s+to\s+(?:Inclusion|Diversity)"
    r"|EEO|Equal\s+Opportunity"
    r"|How\s+to\s+Apply"
    r"|What\s+We\s+Offer"
    r"|The\s+Opportunity"
    r"|#\w+"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# INLINE HEADER PATTERNS  (header + content on the same line)
# ─────────────────────────────────────────────────────────────────────────────

_INLINE_PREFERRED = re.compile(
    r"^\s*(?:Nice\s+to\s+have|Preferred|Bonus)\s*:\s*(.+)$",
    re.IGNORECASE,
)

_INLINE_REQUIRED = re.compile(
    r"^\s*(?:Minimum\s+Requirements?|Required|What\s+we'?re\s+looking\s+for)\s*:\s*(.+)$",
    re.IGNORECASE,
)

_INLINE_RESPONSIBILITIES = re.compile(
    r"^\s*(?:What\s+you'?(?:ll|'ll)\s+do|Responsibilities)\s*:\s*(.+)$",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# SKIP TRIGGERS  (mid-text signals to stop collecting)
# ─────────────────────────────────────────────────────────────────────────────

_SKIP_TRIGGER = re.compile(
    r"^\s*(?:"
    r"Commitment\s+to"
    r"|At\s+\w+,?\s+we\s+don'?t\s+just"
    r"|The\s+compensation"
    r"|Factors\s+such\s+as"
    r"|This\s+(?:salary|hourly)"
    r"|We\s+may\s+use\s+artificial"
    r"|If\s+you\s+require\s+reasonable"
    r"|Adobe\s+is\s+proud"
    r"|PayPal\s+(?:provides|does\s+not)"
    r"|Intel\s+is\s+committed"
    r"|Annual\s+Salary\s+Range"
    r"|Expected\s+Pay\s+Range"
    r"|State-Specific\s+Notices"
    r"|The\s+base\s+pay"
    r"|#\w+"
    r")",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL WORDS  (classify lines when no explicit zone headers exist)
# ─────────────────────────────────────────────────────────────────────────────

_PREFERRED_SIGNALS = re.compile(
    r"\b(?:prefer(?:red|ably)?|nice\s+to\s+have|bonus|plus|ideal(?:ly)?|"
    r"desir(?:ed|able)|optional|advantage|asset|not\s+required|"
    r"familiarity\s+with|exposure\s+to)\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# EXPERIENCE YEARS PATTERN
# ─────────────────────────────────────────────────────────────────────────────

_EXP_YEARS_RE = re.compile(
    r"(\d+)\+?\s*(?:[-–]?\s*\d+)?\s*\+?\s*years?\s*(?:of)?\s*(?:experience|exp\.?)?",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# TITLE & COMPANY EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_ROLE_KEYWORD_RE = re.compile(
    r"(?:software|senior|junior|staff|principal|lead|full\s*stack|"
    r"front\s*end|back\s*end|data|ml|machine\s+learning|ai|cloud|"
    r"devops|sre|platform|mobile|ios|android|web|security|qa|test)"
    r"\s*(?:engineer|developer|scientist|architect|analyst|intern|manager)",
    re.IGNORECASE,
)

_TITLE_SKIP_RE = re.compile(
    r"^(?:About|Who\s+(?:We|You)|Our\s+Mission|Program|Where|Commitment|#|"
    r"The\s+compensation|Factors|What\s+you|What\s+we|Responsibilities|"
    r"Requirements?|Qualifications?|Minimum|Preferred|Nice\s+to|"
    r"In-?\s*office|Pay\s+and|Benefits?|Salary|We're\s+looking|EEO)",
    re.IGNORECASE,
)


def _extract_title_and_company(text: str) -> tuple[str, str]:
    """Best-effort extraction of job title and company from raw JD text."""
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if not lines:
        return "", ""

    title = ""
    company = ""

    # Pattern 1: "Title at Company" on first line
    m = re.match(r"^(.+?)\s+(?:at|@)\s+(.+)$", lines[0], re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern 2: "Company — Title" or "Title | Company" on first line
    m = re.match(r"^(.+?)\s*[|–—]\s*(.+)$", lines[0])
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        # Longer part is likely company
        return (b, a) if len(a) < len(b) else (a, b)

    # Pattern 3: "As a [Title] at [Company]" anywhere in first 3 000 chars
    m = re.search(
        r"[Aa]s\s+(?:a|an)\s+(.+?)\s+at\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)",
        text[:3000],
    )
    if m:
        candidate = m.group(1).strip().rstrip(",")
        if _ROLE_KEYWORD_RE.search(candidate):
            title = candidate
            company = m.group(2).strip()

    # Pattern 4: Scan early lines for a role keyword
    if not title:
        for ln in lines[:30]:
            if len(ln) > 80 or _TITLE_SKIP_RE.match(ln) or ln.endswith("."):
                continue
            if _ROLE_KEYWORD_RE.search(ln):
                title = re.sub(
                    r"^About\s+the\s+(?:job|role)\s*", "", ln, flags=re.IGNORECASE
                ).strip()
                break

    # Pattern 5: Company from "About <CompanyName>"
    if not company:
        m = re.search(
            r"About\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s*$",
            text[:3000],
            re.MULTILINE,
        )
        if m:
            candidate = m.group(1).strip()
            _skip_words = {"the", "our", "this", "your", "team", "role", "job"}
            if candidate.lower() not in _skip_words:
                company = candidate

    return title, company


# ─────────────────────────────────────────────────────────────────────────────
# SENTENCE EXTRACTION HELPER
# ─────────────────────────────────────────────────────────────────────────────


def _clean_lines_to_sentences(source_lines: list[str]) -> list[str]:
    """
    Strip bullet prefixes and return non-trivial sentence strings.
    Skips lines that are pure section headers (end with ':' and are short).
    """
    result: list[str] = []
    for ln in source_lines:
        text = (
            BULLET_INLINE_RE.sub("", ln).strip()
            if BULLET_INLINE_RE.match(ln)
            else ln.strip()
        )
        if not text or len(text) < 15:
            continue
        if text.endswith(":") and len(text) < 40:
            continue
        result.append(text)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────


def parse_jd(text: str) -> dict:
    """
    Parse a raw job description string into the Person-1 → Person-2 JSON contract.

    Args:
        text: Raw JD text (supports multi-line and LinkedIn single-line paste).

    Returns:
        {
          "title": str,
          "company": str,
          "requirements": {
            "required_skills":       [str],
            "preferred_skills":      [str],
            "experience_years":      int | None,
            "requirement_sentences": [{"text": str, "type": "required"|"preferred"}]
          },
          "raw_text": str
        }
    """
    _empty: dict = {
        "title": "",
        "company": "",
        "requirements": {
            "required_skills": [],
            "preferred_skills": [],
            "experience_years": None,
            "requirement_sentences": [],
        },
        "raw_text": text or "",
    }

    if not text or not text.strip():
        return _empty

    # ── Step 1: Normalize LinkedIn single-line pastes ─────────────────────────
    # LinkedIn sometimes collapses newlines; double-spaces become separators.
    if text.count("\n") < 5 and "  " in text:
        text = re.sub(r"  +", "\n", text)

    # ── Step 2: Title & company ───────────────────────────────────────────────
    title, company = _extract_title_and_company(text)

    # experience_years resolved after zone extraction (Step 3b below)

    # ── Step 4: Zone-based line classification ────────────────────────────────
    lines = text.strip().split("\n")

    required_lines: list[str] = []
    preferred_lines: list[str] = []
    zone = "skip"  # preamble before first recognized header is skipped

    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            continue

        # Standalone header detection (full line = header)
        if _RESPONSIBILITIES_HEADER.match(stripped):
            zone = "responsibilities"
            continue
        if _REQUIRED_HEADER.match(stripped):
            zone = "required"
            continue
        if _PREFERRED_HEADER.match(stripped):
            zone = "preferred"
            continue
        if _SKIP_HEADER.match(stripped):
            zone = "skip"
            continue

        # Inline header detection (header: content on same line)
        m = _INLINE_RESPONSIBILITIES.match(stripped)
        if m:
            zone = "responsibilities"
            # remainder of line is a responsibility, not a requirement → skip
            continue

        m = _INLINE_PREFERRED.match(stripped)
        if m:
            zone = "preferred"
            remainder = m.group(1).strip()
            if remainder:
                preferred_lines.append(remainder)
            continue

        m = _INLINE_REQUIRED.match(stripped)
        if m:
            zone = "required"
            remainder = m.group(1).strip()
            if remainder:
                required_lines.append(remainder)
            continue

        # Skip triggers that appear mid-text
        if _SKIP_TRIGGER.match(stripped):
            zone = "skip"
            continue

        # Assign to current zone (responsibilities → skip for JD contract purposes)
        if zone == "required":
            required_lines.append(stripped)
        elif zone == "preferred":
            preferred_lines.append(stripped)
        # "responsibilities" and "skip" are discarded (not in JD contract output)

    # ── Step 5: Fallback — no zones detected → classify by signal words ───────
    if not required_lines and not preferred_lines:
        for ln in lines:
            stripped = ln.strip()
            if not stripped or len(stripped) < 15:
                continue
            if _PREFERRED_SIGNALS.search(stripped):
                preferred_lines.append(stripped)
            else:
                required_lines.append(stripped)

    # ── Step 6: Skill extraction per zone ─────────────────────────────────────
    required_text = "\n".join(required_lines)
    preferred_text = "\n".join(preferred_lines)

    # Experience years — scope to requirements zone to avoid false positives
    # like "25 years in business" or "40 years of creativity" in the preamble.
    years_search_text = required_text if required_text.strip() else text
    exp_matches = _EXP_YEARS_RE.findall(years_search_text)
    experience_years: int | None = int(exp_matches[0]) if exp_matches else None

    required_skill_set: set[str] = set(extract_skills(required_text))
    preferred_skill_set: set[str] = set(extract_skills(preferred_text))

    # Skills found in both → required wins; remove from preferred
    preferred_only = preferred_skill_set - required_skill_set

    required_skills = sorted(required_skill_set)
    preferred_skills = sorted(preferred_only)

    # ── Step 7: Build requirement_sentences with type tags ────────────────────
    req_sentences = _clean_lines_to_sentences(required_lines)
    pref_sentences = _clean_lines_to_sentences(preferred_lines)

    requirement_sentences: list[dict] = [
        {"text": s, "type": "required"} for s in req_sentences
    ] + [
        {"text": s, "type": "preferred"} for s in pref_sentences
    ]

    log.info(
        "parse_jd: title=%r company=%r req_skills=%d pref_skills=%d "
        "req_sent=%d pref_sent=%d exp_years=%s",
        title,
        company,
        len(required_skills),
        len(preferred_skills),
        len(req_sentences),
        len(pref_sentences),
        experience_years,
    )

    return {
        "title": title,
        "company": company,
        "requirements": {
            "required_skills": required_skills,
            "preferred_skills": preferred_skills,
            "experience_years": experience_years,
            "requirement_sentences": requirement_sentences,
        },
        "raw_text": text,
    }
