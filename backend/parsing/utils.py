"""
utils.py — Shared utilities for the ResumeAI parsing pipeline.

Responsibilities:
  - PDF text extraction (PyMuPDF / fitz)
  - Shared regex patterns
  - Text normalization helpers (bullet lines, continuation lines)
  - Bullet / date / location extraction helpers
  - Standalone skill extraction (no external ML dependencies)

All functions are pure (no side effects) and importable by
resume_parser.py and jd_parser.py.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED REGEX CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?\.?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?|Spring|Summer|Fall|Winter)"
)
_DATE_SINGLE = rf"(?:{_MONTH}\.?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_DATE_END = rf"(?:{_DATE_SINGLE}|Present|Current|Now|Ongoing|present)"

DATE_RANGE: re.Pattern[str] = re.compile(
    rf"({_DATE_SINGLE})\s*(?:[-–—~]|to)\s*({_DATE_END})",
    re.IGNORECASE,
)

# Inline bullet prefix: "• text" / "- text" / "1. text"
BULLET_INLINE_RE: re.Pattern[str] = re.compile(
    r"^\s*[•●○▪▸]\s+|^\s*[-–—\*]\s+|^\s*\d+[.)]\s+"
)

# Standalone bullet symbol on its own line (PyMuPDF artefact)
BULLET_STANDALONE_RE: re.Pattern[str] = re.compile(r"^\s*[•●○▪▸\-–—\*]\s*$")

# "City, ST" or "Remote" at end of a string
LOCATION_RE: re.Pattern[str] = re.compile(
    r",?\s*([A-Z][a-zA-Z\s]+,\s*[A-Z]{2})\s*$" r"|,?\s*(Remote)\s*$",
    re.IGNORECASE,
)

# Separator between role and company: " - " / " | "
ROLE_SEP_RE: re.Pattern[str] = re.compile(r"\s+[-–—]\s+|\s*[|]\s*")

# Section headers that should terminate project/experience parsing
STOP_SECTIONS_RE: re.Pattern[str] = re.compile(
    r"^(?:ACHIEVEMENTS?|CERTIFICATIONS?|AWARDS?|HONORS?|LEADERSHIP|"
    r"RESEARCH|PUBLICATIONS?|VOLUNTEER|EXTRACURRICULAR|INTERESTS?|"
    r"REFERENCES?)\b",
    re.IGNORECASE,
)

# Company / institution keywords for title-vs-company disambiguation
COMPANY_HINTS_RE: re.Pattern[str] = re.compile(
    r"university|college|institute|inc\.?|corp|llc|ltd|bank|"
    r"pvt|private|global|technologies|labs?|studios?|"
    r"amazon|google|meta|microsoft|apple|nvidia|tesla",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# SKILL VOCABULARY
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_SKILLS: frozenset[str] = frozenset(
    {
        # ── Languages ──────────────────────────────────────────────────────
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "C",
        "C++",
        "C#",
        "Go",
        "Golang",
        "Rust",
        "Ruby",
        "PHP",
        "Swift",
        "Kotlin",
        "Scala",
        "R",
        "MATLAB",
        "Perl",
        "Shell",
        "Bash",
        "PowerShell",
        "Haskell",
        "Erlang",
        "Elixir",
        "Clojure",
        "Dart",
        "Lua",
        "Assembly",
        "COBOL",
        "Fortran",
        "Groovy",
        # ── Web / Frontend ─────────────────────────────────────────────────
        "HTML",
        "CSS",
        "Sass",
        "SCSS",
        "Less",
        "React",
        "Angular",
        "Vue",
        "Vue.js",
        "Next.js",
        "Nuxt.js",
        "Svelte",
        "SvelteKit",
        "Remix",
        "Gatsby",
        "jQuery",
        "Bootstrap",
        "Tailwind",
        "Tailwind CSS",
        "Webpack",
        "Vite",
        "Rollup",
        "Babel",
        "ESLint",
        "Prettier",
        # ── Backend / Frameworks ───────────────────────────────────────────
        "Node.js",
        "Express",
        "Express.js",
        "NestJS",
        "FastAPI",
        "Django",
        "Flask",
        "Spring",
        "Spring Boot",
        "Rails",
        "Ruby on Rails",
        "Laravel",
        "ASP.NET",
        ".NET",
        "gRPC",
        "GraphQL",
        "REST",
        "RESTful",
        "WebSockets",
        "WebSocket",
        "Gin",
        "Fiber",
        "Actix",
        # ── Databases ──────────────────────────────────────────────────────
        "PostgreSQL",
        "MySQL",
        "SQLite",
        "SQL Server",
        "Oracle",
        "MariaDB",
        "MongoDB",
        "DynamoDB",
        "Cassandra",
        "Redis",
        "Elasticsearch",
        "Neo4j",
        "CouchDB",
        "Firebase",
        "Firestore",
        "Supabase",
        "InfluxDB",
        "TimescaleDB",
        # ── Cloud / DevOps ─────────────────────────────────────────────────
        "AWS",
        "Azure",
        "GCP",
        "Google Cloud",
        "Docker",
        "Kubernetes",
        "k8s",
        "Terraform",
        "Ansible",
        "Puppet",
        "Chef",
        "Jenkins",
        "CircleCI",
        "GitHub Actions",
        "GitLab CI",
        "CI/CD",
        "Helm",
        "Istio",
        "Prometheus",
        "Grafana",
        "Datadog",
        "New Relic",
        "PagerDuty",
        "ECS",
        "EKS",
        "Lambda",
        "S3",
        "RDS",
        "ElastiCache",
        "EC2",
        "SNS",
        "SQS",
        # ── AI / ML ────────────────────────────────────────────────────────
        "TensorFlow",
        "PyTorch",
        "Keras",
        "scikit-learn",
        "sklearn",
        "pandas",
        "NumPy",
        "SciPy",
        "Matplotlib",
        "Seaborn",
        "Plotly",
        "Hugging Face",
        "transformers",
        "LangChain",
        "LlamaIndex",
        "OpenAI",
        "RAG",
        "LLM",
        "NLP",
        "NLTK",
        "spaCy",
        "XGBoost",
        "LightGBM",
        "CatBoost",
        "MLflow",
        "CUDA",
        "OpenCV",
        "Stable Diffusion",
        "Generative AI",
        # ── Data Engineering ───────────────────────────────────────────────
        "Spark",
        "Apache Spark",
        "Hadoop",
        "Apache Kafka",
        "Airflow",
        "Apache Airflow",
        "Apache Flink",
        "dbt",
        "Snowflake",
        "BigQuery",
        "Redshift",
        "Databricks",
        "Hive",
        "Presto",
        "Trino",
        "Parquet",
        "Avro",
        "RabbitMQ",
        "Celery",
        "Pub/Sub",
        # ── Version Control / Collaboration ────────────────────────────────
        "Git",
        "GitHub",
        "GitLab",
        "Bitbucket",
        "SVN",
        "Jira",
        "Confluence",
        "Linear",
        # ── Finance-specific ───────────────────────────────────────────────
        "QuantLib",
        "Open Source Risk Engine",
        "Bloomberg",
        "Excel",
        "VBA",
        # ── Testing ────────────────────────────────────────────────────────
        "pytest",
        "JUnit",
        "Mocha",
        "Jest",
        "Cypress",
        "Selenium",
        "Playwright",
        "Postman",
        "unittest",
        # ── Data Viz / BI ──────────────────────────────────────────────────
        "Tableau",
        "Power BI",
        "Looker",
        # ── Protocols / Standards ──────────────────────────────────────────
        "Protocol Buffers",
        "OpenAPI",
        "Swagger",
        "OAuth",
        "JWT",
        "SSL",
        "TLS",
        "SAML",
        "LDAP",
        # ── Mobile ─────────────────────────────────────────────────────────
        "React Native",
        "Flutter",
        "iOS",
        "Android",
        "Xcode",
        # ── Misc ───────────────────────────────────────────────────────────
        "Linux",
        "Unix",
        "SSH",
        "Agile",
        "Scrum",
        "Kanban",
        "Microservices",
        "Serverless",
    }
)

# Build a mapping of lowercase → canonical for fast lookup
_SKILLS_LOWER: dict[str, str] = {s.lower(): s for s in KNOWN_SKILLS}


def extract_skills(text: str) -> list[str]:
    """
    Extract recognized tech skills from arbitrary text.

    Strategy:
      1. Vocabulary match (case-insensitive, word-boundary aware).
         Returns the canonical casing stored in KNOWN_SKILLS.
      2. Deduplication preserving first-seen order.

    This is intentionally dependency-free (no spaCy, no ML).
    """
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    for skill_lower, canonical in _SKILLS_LOWER.items():
        # Word-boundary pattern; escape for skills with special chars (C++, .NET)
        pattern = (
            r"(?<![A-Za-z0-9.+#])" + re.escape(skill_lower) + r"(?![A-Za-z0-9.+#])"
        )
        if re.search(pattern, text, re.IGNORECASE) and skill_lower not in seen:
            seen.add(skill_lower)
            found.append(canonical)

    return found


# ─────────────────────────────────────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────


def _detect_columns(blocks: list, page_width: float) -> list[tuple[float, float]]:
    """
    Detect column boundaries from text-block x-coordinates.

    Scans for the widest horizontal gap between occupied x-bins.
    Returns [(col_start, col_end), ...].  Single-column → [(0, page_width)].
    """
    if not blocks:
        return [(0.0, page_width)]

    bin_width = 5.0
    num_bins = int(page_width / bin_width) + 1
    bin_counts = [0] * num_bins

    for b in blocks:
        x0, x1 = b[0], b[2]
        start_bin = max(0, int(x0 / bin_width))
        end_bin = min(num_bins - 1, int(x1 / bin_width))
        for i in range(start_bin, end_bin + 1):
            bin_counts[i] += 1

    best_gap_start = -1
    best_gap_end = -1
    best_gap_width = 0.0
    gap_start = -1

    for i, count in enumerate(bin_counts):
        if count == 0:
            if gap_start < 0:
                gap_start = i
        else:
            if gap_start >= 0:
                gap_width = (i - gap_start) * bin_width
                gap_center = ((gap_start + i) / 2) * bin_width
                if (
                    gap_width > best_gap_width
                    and gap_width >= 15
                    and page_width * 0.15 < gap_center < page_width * 0.85
                ):
                    best_gap_width = gap_width
                    best_gap_start = gap_start
                    best_gap_end = i
            gap_start = -1

    # Check trailing gap
    if gap_start >= 0:
        gap_width = (num_bins - gap_start) * bin_width
        gap_center = ((gap_start + num_bins) / 2) * bin_width
        if (
            gap_width > best_gap_width
            and gap_width >= 15
            and page_width * 0.15 < gap_center < page_width * 0.85
        ):
            best_gap_width = gap_width
            best_gap_start = gap_start
            best_gap_end = num_bins

    if best_gap_width >= 15:
        gap_x = ((best_gap_start + best_gap_end) / 2) * bin_width
        log.debug(
            "Column gap at x=%.0f (width=%.0f pt, page=%.0f pt)",
            gap_x,
            best_gap_width,
            page_width,
        )
        return [(0.0, gap_x), (gap_x, page_width)]

    return [(0.0, page_width)]


def _extract_page_text(page) -> str:  # page: fitz.Page
    """
    Extract text from one PDF page, respecting multi-column layout.

    Uses coordinate-ordered block reading so sidebar / two-column
    résumés are read column-by-column (left then right), not
    line-by-line across both columns.
    """
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return page.get_text("text")

    if not blocks:
        return page.get_text("text")

    # Only text blocks (type 0) with non-empty content
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
    if not text_blocks:
        return page.get_text("text")

    page_width = page.rect.width
    columns = _detect_columns(text_blocks, page_width)

    if len(columns) == 1:
        ordered = sorted(text_blocks, key=lambda b: (b[1], b[0]))
    else:
        col_blocks: list[list] = [[] for _ in columns]
        for b in text_blocks:
            cx = (b[0] + b[2]) / 2
            assigned = False
            for idx, (c0, c1) in enumerate(columns):
                if c0 <= cx <= c1:
                    col_blocks[idx].append(b)
                    assigned = True
                    break
            if not assigned:
                best = min(
                    range(len(columns)),
                    key=lambda i: abs(cx - (columns[i][0] + columns[i][1]) / 2),
                )
                col_blocks[best].append(b)

        ordered = []
        for col in col_blocks:
            ordered.extend(sorted(col, key=lambda b: b[1]))

        log.debug(
            "Multi-column: %d columns, blocks/col: %s",
            len(columns),
            [len(c) for c in col_blocks],
        )

    return "\n".join(b[4].strip() for b in ordered)


def extract_text_from_pdf(file_path: str | Path) -> str:
    """
    Extract full text from a PDF file using PyMuPDF.

    Raises FileNotFoundError if the path does not exist.
    Raises ValueError if no text could be extracted.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) is required: pip install pymupdf") from exc

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    log.info("Extracting text from: %s", file_path.name)
    doc = fitz.open(str(file_path))
    pages_text: list[str] = []

    for page_num, page in enumerate(doc):
        text = _extract_page_text(page)
        if text.strip():
            pages_text.append(text)
            log.debug("Page %d: %d chars", page_num + 1, len(text))

    doc.close()
    full_text = "\n\n".join(pages_text)

    if not full_text.strip():
        raise ValueError(f"No extractable text in: {file_path.name}")

    log.info("Extracted %d chars from %d pages", len(full_text), len(pages_text))
    return full_text


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    """
    Extract full text from an in-memory PDF (e.g., uploaded file bytes).

    Raises ValueError if no text could be extracted.
    """
    try:
        import fitz
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) is required: pip install pymupdf") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_text: list[str] = []

    for page in doc:
        text = _extract_page_text(page)
        if text.strip():
            pages_text.append(text)

    doc.close()
    full_text = "\n\n".join(pages_text)

    if not full_text.strip():
        raise ValueError("No extractable text in uploaded PDF.")

    return full_text


# ─────────────────────────────────────────────────────────────────────────────
# TEXT NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────


def normalize_bullet_lines(lines: list[str]) -> list[str]:
    """
    Normalize PyMuPDF bullet artefacts.

    Pattern A: "• Build REST APIs…"   → kept as-is
    Pattern B: "•" alone, next line has content  → merged into "• <content>"

    Strips each line but does NOT merge continuation lines (see below).
    """
    if not lines:
        return []

    normalized: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if BULLET_STANDALONE_RE.match(stripped):
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                normalized.append(f"• {next_line}")
                i += 2
                continue
            i += 1
            continue
        normalized.append(stripped)
        i += 1

    return normalized


# Words that signal the previous line ended mid-sentence (wrapping)
_TRAILING_PREPOSITIONS: frozenset[str] = frozenset(
    {
        "by",
        "to",
        "for",
        "with",
        "in",
        "on",
        "at",
        "of",
        "from",
        "and",
        "or",
        "the",
        "a",
        "an",
        "as",
        "into",
        "via",
        "using",
        "through",
        "across",
        "between",
        "about",
        "over",
        "after",
        "before",
        "that",
        "which",
        "including",
        "integrating",
        "reducing",
        "increasing",
        "enabling",
        "achieving",
        "delivering",
        "supporting",
        "maintaining",
        "&",
    }
)


def merge_continuation_lines(lines: list[str]) -> list[str]:
    """
    Merge continuation / wrapped lines into their predecessor.

    A line is a continuation when it:
    - Starts lowercase
    - Starts with ) ] }
    - Is a tiny digit fragment ("32%.")
    - Starts with a common mid-sentence word
    - Previous line ends with comma, hyphen, or trailing preposition
    """
    if not lines:
        return []

    merged: list[str] = []
    for ln in lines:
        if not ln:
            continue

        is_cont = False
        if merged:
            prev = merged[-1]
            prev_s = prev.rstrip()
            prev_words = prev_s.split()
            prev_last = prev_words[-1].lower().rstrip(".,;:") if prev_words else ""

            if (
                not BULLET_INLINE_RE.match(ln)
                and not DATE_RANGE.search(ln)
                and not STOP_SECTIONS_RE.match(ln)
            ):
                if ln[0].islower():
                    is_cont = True
                elif ln[0] in ")]}":
                    is_cont = True
                elif ln[0].isdigit() and len(ln) < 15:
                    is_cont = True
                elif re.match(
                    r"^(and |with |using |to |for |that |which |the |or |in |on )",
                    ln,
                    re.IGNORECASE,
                ):
                    is_cont = True
                elif prev_s.endswith((",", "-", "–")):
                    is_cont = True
                elif prev_last in _TRAILING_PREPOSITIONS:
                    is_cont = True
                elif prev_s.endswith("&"):
                    is_cont = True
                elif (
                    len(ln) < 50
                    and not ROLE_SEP_RE.search(ln)
                    and BULLET_INLINE_RE.match(prev)
                    and not re.match(r"^[A-Z][A-Za-z\s]+,\s*[A-Z][A-Za-z]+", ln)
                ):
                    is_cont = True

        if is_cont and merged:
            if merged[-1].rstrip().endswith("-"):
                merged[-1] = merged[-1].rstrip().rstrip("-") + ln
            else:
                merged[-1] = merged[-1].rstrip().rstrip(",") + " " + ln
        else:
            merged.append(ln)

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# BULLET / DATE / LOCATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def extract_bullets(lines: list[str]) -> list[str]:
    """
    Extract bullet text from normalized lines.

    Lines with a bullet prefix → strip prefix.
    Lines without a prefix    → treat as implicit bullet if ≥ 15 chars.
    """
    bullets: list[str] = []
    for ln in lines:
        text = (
            BULLET_INLINE_RE.sub("", ln).strip()
            if BULLET_INLINE_RE.match(ln)
            else ln.strip()
        )
        if text and len(text) >= 15:
            bullets.append(text)
    return bullets


def extract_date_range(text: str) -> str:
    """Return 'StartDate - EndDate' if found, else empty string."""
    m = DATE_RANGE.search(text)
    return f"{m.group(1).strip()} - {m.group(2).strip()}" if m else ""


def remove_date_range(text: str) -> str:
    """Strip any date range from text, trimming trailing punctuation."""
    return DATE_RANGE.sub("", text).strip().rstrip("|,–-—").strip()


def extract_location(text: str) -> tuple[str, str]:
    """
    Extract a trailing 'City, ST' or 'Remote' from text.

    Returns (text_without_location, location_string).
    """
    m = LOCATION_RE.search(text)
    if m:
        loc = (m.group(1) or m.group(2)).strip()
        cleaned = LOCATION_RE.sub("", text).strip().rstrip("|,–-—").strip()
        return cleaned, loc
    return text, ""


def split_role_and_company(header: str) -> tuple[str, str]:
    """
    Split 'TITLE - COMPANY' or 'COMPANY | TITLE' into (title, company).

    Uses COMPANY_HINTS_RE to determine which part is the company.
    Falls back to: longer part = company.
    """
    parts = ROLE_SEP_RE.split(header, maxsplit=1)
    if len(parts) < 2:
        return "", header

    a, b = parts[0].strip(), parts[1].strip()
    a_co = bool(COMPANY_HINTS_RE.search(a))
    b_co = bool(COMPANY_HINTS_RE.search(b))

    if a_co and not b_co:
        return b, a
    if b_co and not a_co:
        return a, b
    if len(b) > len(a):
        return a, b
    return b, a
