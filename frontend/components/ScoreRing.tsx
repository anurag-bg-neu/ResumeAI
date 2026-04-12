"use client";

import { useEffect, useState } from "react";

interface ScoreRingProps {
  /** Score between 0 and 1 */
  score: number;
  /** Label shown below the number */
  label: string;
  /** Ring diameter in px */
  size?: number;
}

function getColor(score: number): string {
  if (score >= 0.6) return "#22c55e"; // green-500
  if (score >= 0.35) return "#eab308"; // yellow-500
  return "#ef4444"; // red-500
}

function getLabel(score: number): string {
  if (score >= 0.6) return "Strong";
  if (score >= 0.35) return "Moderate";
  return "Weak";
}

export default function ScoreRing({ score, label, size = 160 }: ScoreRingProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Trigger animation after mount
    const timer = setTimeout(() => setMounted(true), 100);
    return () => clearTimeout(timer);
  }, []);

  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - score * circumference;
  const color = getColor(score);
  const pct = Math.round(score * 100);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
        >
          {/* Track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            className="score-ring-track"
          />
          {/* Fill */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            className="score-ring-fill"
            stroke={color}
            strokeDasharray={circumference}
            strokeDashoffset={mounted ? offset : circumference}
          />
        </svg>
        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold tabular-nums" style={{ color }}>
            {pct}
          </span>
          <span
            className="text-xs font-medium uppercase tracking-wide"
            style={{ color }}
          >
            {getLabel(score)}
          </span>
        </div>
      </div>
      <span className="text-sm font-medium text-gray-600">{label}</span>
    </div>
  );
}
