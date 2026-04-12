"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ScoreRing from "@/components/ScoreRing";
import SkillChips from "@/components/SkillChips";

/* ── Types ──────────────────────────────────────────────────────────────── */

interface PartialMatch {
  jd_skill: string;
  similarity: number;
  closest_bullet: string;
  note: string;
}

interface ExperienceEntry {
  company: string;
  title: string;
  avg_relevance: number;
  bullet_count: number;
}

interface ProjectEntry {
  name: string;
  avg_relevance: number;
}

interface AnalysisResult {
  job_id: string;
  scores: { semantic: number; keyword: number };
  skills_analysis: {
    covered: string[];
    missing: string[];
    partial_match: PartialMatch[];
  };
  gap_report: {
    missing_skills: string[];
    partial_matches: PartialMatch[];
    jd_title: string;
    jd_company: string;
    recommendation: string;
  };
  contact: { name: string; email: string };
  jd_meta: { title: string; company: string };
  experience_count: number;
  project_count: number;
  experience: ExperienceEntry[];
  projects: ProjectEntry[];
}

type AppState = "upload" | "analyzing" | "results" | "error";

/* ── Page Component ─────────────────────────────────────────────────────── */

export default function Home() {
  const [state, setState] = useState<AppState>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  /* ── File handlers ──────────────────────────────────────────────────── */

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped?.type === "application/pdf") {
      setFile(dropped);
    }
  }, []);

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) setFile(selected);
  }, []);

  /* ── Submit ─────────────────────────────────────────────────────────── */

  const handleSubmit = async () => {
    if (!file || !jdText.trim()) return;

    setState("analyzing");
    setError("");

    const formData = new FormData();
    formData.append("resume", file);
    formData.append("jd_text", jdText);

    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `Server error ${res.status}`);
      }

      const data: AnalysisResult = await res.json();
      setResult(data);
      setState("results");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error occurred");
      setState("error");
    }
  };

  /* ── Reset ──────────────────────────────────────────────────────────── */

  const handleReset = () => {
    setFile(null);
    setJdText("");
    setResult(null);
    setError("");
    setState("upload");
  };

  /* ── Download PDF ───────────────────────────────────────────────────── */

  const handleDownload = () => {
    if (!result) return;
    const link = document.createElement("a");
    link.href = `/api/download/${result.job_id}`;
    link.download = "tailored_resume.pdf";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  /* ── Composite score (60% semantic + 40% keyword) ───────────────────── */

  const composite = result
    ? 0.6 * result.scores.semantic + 0.4 * result.scores.keyword
    : 0;

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900">
          Resume<span className="text-brand-600">AI</span>
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          ATS-optimized resume analysis &amp; generation
        </p>
      </header>

      {/* ── UPLOAD STATE ─────────────────────────────────────────────── */}
      {state === "upload" && (
        <div className="space-y-6 rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
          {/* PDF upload zone */}
          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-700">
              Resume (PDF)
            </label>
            <div
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors ${
                dragOver
                  ? "drop-zone-active"
                  : file
                    ? "border-green-300 bg-green-50"
                    : "border-gray-300 bg-gray-50 hover:border-gray-400"
              }`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input
                ref={fileRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={onFileChange}
              />
              {file ? (
                <div className="text-center">
                  <div className="text-2xl">📄</div>
                  <p className="mt-1 text-sm font-medium text-green-700">
                    {file.name}
                  </p>
                  <p className="text-xs text-green-600">
                    {(file.size / 1024).toFixed(0)} KB — click to replace
                  </p>
                </div>
              ) : (
                <div className="text-center">
                  <div className="text-2xl text-gray-400">⬆</div>
                  <p className="mt-1 text-sm text-gray-600">
                    Drag &amp; drop your resume PDF here, or click to browse
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* JD textarea */}
          <div>
            <label
              htmlFor="jd"
              className="mb-2 block text-sm font-semibold text-gray-700"
            >
              Job Description
            </label>
            <textarea
              id="jd"
              rows={8}
              className="w-full rounded-xl border border-gray-300 bg-gray-50 px-4 py-3 text-sm text-gray-800 placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              placeholder="Paste the full job description here…"
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
            />
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={!file || !jdText.trim()}
            className="w-full rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            Analyze Resume
          </button>
        </div>
      )}

      {/* ── ANALYZING STATE ──────────────────────────────────────────── */}
      {state === "analyzing" && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-gray-200 bg-white p-16 shadow-sm">
          {/* Spinner */}
          <div className="relative mb-6">
            <div className="h-16 w-16 animate-spin rounded-full border-4 border-gray-200 border-t-brand-600" />
          </div>
          <h2 className="text-lg font-semibold text-gray-800">
            Analyzing your resume…
          </h2>
          <p className="mt-2 max-w-sm text-center text-sm text-gray-500">
            Parsing PDF, scoring against the JD with TF-IDF + semantic
            similarity, running gap analysis, and generating your tailored
            resume. This takes 10–30 seconds on first run.
          </p>

          {/* Animated steps */}
          <div className="mt-8 space-y-3 text-left text-sm text-gray-500">
            <StepLine text="Extracting resume sections" delay={0} />
            <StepLine text="Parsing job description" delay={2} />
            <StepLine text="Computing semantic similarity" delay={5} />
            <StepLine text="Running skill gap analysis" delay={8} />
            <StepLine text="Generating tailored PDF" delay={12} />
          </div>
        </div>
      )}

      {/* ── ERROR STATE ──────────────────────────────────────────────── */}
      {state === "error" && (
        <div className="rounded-2xl border border-red-200 bg-white p-8 shadow-sm">
          <h2 className="text-lg font-semibold text-red-700">
            Analysis failed
          </h2>
          <p className="mt-2 text-sm text-red-600">{error}</p>
          <button
            onClick={handleReset}
            className="mt-6 rounded-xl bg-gray-800 px-6 py-2.5 text-sm font-semibold text-white hover:bg-gray-700"
          >
            Try Again
          </button>
        </div>
      )}

      {/* ── RESULTS STATE ────────────────────────────────────────────── */}
      {state === "results" && result && (
        <div className="space-y-6">
          {/* JD meta header */}
          {(result.jd_meta.title || result.jd_meta.company) && (
            <div className="rounded-xl border border-brand-100 bg-brand-50 px-5 py-3 text-center text-sm">
              <span className="font-semibold text-brand-800">
                {result.jd_meta.title || "Role"}
              </span>
              {result.jd_meta.company && (
                <span className="text-brand-600">
                  {" "}
                  @ {result.jd_meta.company}
                </span>
              )}
            </div>
          )}

          {/* Score rings */}
          <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
            <h2 className="mb-6 text-center text-lg font-semibold text-gray-800">
              Match Scores
            </h2>
            <div className="flex flex-wrap items-center justify-center gap-10">
              <ScoreRing score={composite} label="Overall Match" size={170} />
              <ScoreRing
                score={result.scores.semantic}
                label="Semantic Score"
              />
              <ScoreRing
                score={result.scores.keyword}
                label="Keyword Score"
              />
            </div>
            <p className="mx-auto mt-6 max-w-lg text-center text-xs text-gray-500">
              Semantic score measures meaning-level similarity between your
              bullets and JD requirements (sentence-transformers). Keyword score
              measures TF-IDF term overlap. Overall = 60% semantic + 40%
              keyword.
            </p>
          </div>

          {/* Skills analysis */}
          <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
            <h2 className="mb-4 text-lg font-semibold text-gray-800">
              Skill Gap Analysis
            </h2>
            <SkillChips
              covered={result.skills_analysis.covered}
              missing={result.skills_analysis.missing}
              partial={result.skills_analysis.partial_match}
            />
          </div>

          {/* Recommendation */}
          {result.gap_report.recommendation && (
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-6 shadow-sm">
              <h3 className="mb-2 text-sm font-semibold text-blue-800">
                Recommendation
              </h3>
              <p className="text-sm leading-relaxed text-blue-700">
                {result.gap_report.recommendation}
              </p>
            </div>
          )}

          {/* Experience + Projects relevance */}
          <div className="grid gap-6 sm:grid-cols-2">
            {/* Experience */}
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="mb-3 text-sm font-semibold text-gray-800">
                Experience Relevance ({result.experience_count})
              </h3>
              <div className="space-y-3">
                {result.experience.map((e, i) => (
                  <div key={i} className="text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-700">
                        {e.title}
                      </span>
                      <span className="text-xs tabular-nums text-gray-500">
                        {Math.round(e.avg_relevance * 100)}%
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-gray-500">
                      {e.company} · {e.bullet_count} bullets
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${Math.min(e.avg_relevance * 100, 100)}%`,
                          backgroundColor:
                            e.avg_relevance >= 0.5
                              ? "#22c55e"
                              : e.avg_relevance >= 0.3
                                ? "#eab308"
                                : "#ef4444",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Projects */}
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="mb-3 text-sm font-semibold text-gray-800">
                Project Relevance ({result.project_count})
              </h3>
              <div className="space-y-3">
                {result.projects.map((p, i) => (
                  <div key={i} className="text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-700">
                        {p.name}
                      </span>
                      <span className="text-xs tabular-nums text-gray-500">
                        {Math.round(p.avg_relevance * 100)}%
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${Math.min(p.avg_relevance * 100, 100)}%`,
                          backgroundColor:
                            p.avg_relevance >= 0.5
                              ? "#22c55e"
                              : p.avg_relevance >= 0.3
                                ? "#eab308"
                                : "#ef4444",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-4">
            <button
              onClick={handleDownload}
              className="flex-1 rounded-xl bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
            >
              Download Tailored Resume (PDF)
            </button>
            <button
              onClick={handleReset}
              className="rounded-xl border border-gray-300 bg-white px-6 py-3 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50"
            >
              Analyze Another
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

/* ── Animated step indicator ─────────────────────────────────────────── */

function StepLine({ text, delay }: { text: string; delay: number }) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setActive(true), delay * 1000);
    return () => clearTimeout(timer);
  }, [delay]);

  return (
    <div className="flex items-center gap-2">
      {active ? (
        <span className="inline-block h-4 w-4 animate-spin-slow rounded-full border-2 border-gray-300 border-t-brand-600" />
      ) : (
        <span className="inline-block h-4 w-4 rounded-full border-2 border-gray-200" />
      )}
      <span className={active ? "text-gray-700" : "text-gray-400"}>
        {text}
      </span>
    </div>
  );
}
