"""
smoke_api.py
------------
Live smoke-test for the ResumeAI API. This is NOT a unit test — it exercises a
running server end to end. The unit tests live in backend/tests/ (pytest).

Usage:
    1. Start the API:    python -m uvicorn api_app:app --port 8000
    2. Run this script:  python scripts/smoke_api.py
       (optionally:      python scripts/smoke_api.py --resume path/to/resume.pdf)

Exits non-zero on any failure, so it can gate CI.

Requires:  pip install requests
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests first:  pip install requests")
    sys.exit(1)

# This script lives in backend/scripts/, so data/ is one level up.
BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_RESUME = BACKEND / "data" / "sample_resumes" / "resume.pdf"
JD = BACKEND / "data" / "sample_jds" / "jd1.txt"


def fail(msg: str) -> None:
    print(f"   FAIL  {msg}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Smoke-test a running ResumeAI API.")
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL")
    ap.add_argument(
        "--resume",
        type=Path,
        default=DEFAULT_RESUME,
        help=f"Resume PDF to submit (default: {DEFAULT_RESUME})",
    )
    args = ap.parse_args()
    BASE, RESUME = args.base, args.resume

    # ── Health check ─────────────────────────────────────────────────────
    print("1. Health check...")
    r = requests.get(f"{BASE}/api/health", timeout=5)
    if r.status_code != 200:
        fail(f"health check status={r.status_code}")
    print(f"   OK  {r.json()}")

    # ── Analyze ──────────────────────────────────────────────────────────
    if not RESUME.exists():
        fail(f"resume not found at {RESUME} (pass --resume <path>)")

    jd_text = JD.read_text() if JD.exists() else "Software Engineer at Google"

    print("\n2. Submitting resume + JD for analysis...")
    print(f"   Resume: {RESUME.name}  |  JD: {len(jd_text)} chars")
    with open(RESUME, "rb") as f:
        r = requests.post(
            f"{BASE}/api/analyze",
            files={"resume": (RESUME.name, f, "application/pdf")},
            data={"jd_text": jd_text},
            timeout=120,
        )

    if r.status_code != 200:
        fail(f"status={r.status_code}  {r.text[:500]}")

    result = r.json()
    print(f"   OK  job_id={result['job_id']}")
    print(f"   Semantic score : {result['scores']['semantic']}")
    print(f"   Keyword score  : {result['scores']['keyword']}")
    print(f"   Skills covered : {len(result['skills_analysis']['covered'])}")
    print(f"   Skills missing : {len(result['skills_analysis']['missing'])}")
    print(f"   Experiences    : {result['experience_count']}")
    print(f"   Projects       : {result['project_count']}")

    # ── Download PDF ─────────────────────────────────────────────────────
    print(f"\n3. Downloading tailored PDF (job_id={result['job_id']})...")
    r = requests.get(f"{BASE}/api/download/{result['job_id']}", timeout=30)
    if r.status_code != 200 or not r.content.startswith(b"%PDF-"):
        fail(f"status={r.status_code}, {len(r.content)} bytes")
    out = Path(tempfile.gettempdir()) / "resumeai_smoke_output.pdf"
    out.write_bytes(r.content)
    print(f"   OK  saved to {out}  ({len(r.content)} bytes)")

    # ── Full JSON dump for inspection ────────────────────────────────────
    print("\n4. Full API response:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
