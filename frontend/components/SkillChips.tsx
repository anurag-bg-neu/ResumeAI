"use client";

interface PartialMatch {
  jd_skill: string;
  similarity: number;
  closest_bullet: string;
  note: string;
}

interface SkillChipsProps {
  covered: string[];
  missing: string[];
  partial: PartialMatch[];
}

function Chip({
  text,
  variant,
}: {
  text: string;
  variant: "covered" | "missing" | "partial";
}) {
  const styles = {
    covered: "bg-green-100 text-green-800 border-green-200",
    missing: "bg-red-100 text-red-800 border-red-200",
    partial: "bg-amber-100 text-amber-800 border-amber-200",
  };

  const icons = {
    covered: "✓",
    missing: "✗",
    partial: "~",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium ${styles[variant]}`}
    >
      <span className="text-[10px]">{icons[variant]}</span>
      {text}
    </span>
  );
}

export default function SkillChips({ covered, missing, partial }: SkillChipsProps) {
  return (
    <div className="space-y-5">
      {/* Covered */}
      {covered.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-green-700">
            Covered Skills ({covered.length})
          </h4>
          <div className="flex flex-wrap gap-2">
            {covered.map((s) => (
              <Chip key={s} text={s} variant="covered" />
            ))}
          </div>
        </div>
      )}

      {/* Missing */}
      {missing.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-red-700">
            Missing Skills ({missing.length})
          </h4>
          <div className="flex flex-wrap gap-2">
            {missing.map((s) => (
              <Chip key={s} text={s} variant="missing" />
            ))}
          </div>
        </div>
      )}

      {/* Partial */}
      {partial.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-amber-700">
            Partial Matches ({partial.length})
          </h4>
          <div className="flex flex-wrap gap-2">
            {partial.map((p) => (
              <Chip key={p.jd_skill} text={p.jd_skill} variant="partial" />
            ))}
          </div>
          <div className="mt-3 space-y-2">
            {partial.map((p) => (
              <div
                key={p.jd_skill}
                className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"
              >
                <span className="font-semibold">&quot;{p.jd_skill}&quot;</span>{" "}
                — similarity {Math.round(p.similarity * 100)}%
                <br />
                <span className="text-amber-700">
                  Closest bullet: &quot;{p.closest_bullet.slice(0, 90)}
                  {p.closest_bullet.length > 90 ? "…" : ""}&quot;
                </span>
                <br />
                <span className="italic">{p.note}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
