"""
smoke_api.py
------------
Live smoke-test for the ResumeAI API. This is NOT a unit test — it exercises a
running server end to end. The pytest suite lives in backend/tests/.

Usage:
    1. Start the API:    python -m uvicorn api_app:app --port 8000
    2. Run this script:  python scripts/smoke_api.py
       (optionally:      python scripts/smoke_api.py --resume path/to/resume.pdf)

Requires:  pip install requests
"""

import argparse
import json
import sys
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
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print(f"   OK  {r.json()}")

    # ── Analyze ──────────────────────────────────────────────────────────
    if not RESUME.exists():
        print(f"\n   SKIP — resume not found at {RESUME}")
        print(f"   Place a PDF at {DEFAULT_RESUME}, or pass --resume <path>.")
        return

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
        print(f"   FAIL  status={r.status_code}")
        print(f"   {r.text[:500]}")
        return

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
    if r.status_code == 200:
        out = Path("test_output.pdf")
        out.write_bytes(r.content)
        print(f"   OK  saved to {out}  ({len(r.content)} bytes)")
    else:
        print(f"   FAIL  status={r.status_code}")

    # ── Full JSON dump for inspection ────────────────────────────────────
    print("\n4. Full API response:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
