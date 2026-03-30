import { useId } from "react";
import type { PricePoint } from "../types";

type SparklineProps = {
  points: PricePoint[];
};

export function Sparkline({ points }: SparklineProps) {
  const gradientId = useId();

  if (!points.length) {
    return <div className="sparkline sparkline-empty">No trend data</div>;
  }

  const width = 180;
  const height = 56;
  const values = points.map((point) => point.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.close - min) / range) * height;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const areaPath = `${path} L ${width} ${height} L 0 ${height} Z`;

  const latest = values[values.length - 1];
  const earliest = values[0];
  const isPositive = latest >= earliest;
  const endX = width;
  const endY = height - ((latest - min) / range) * height;

  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img">
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={isPositive ? "rgba(15, 118, 110, 0.35)" : "rgba(185, 56, 21, 0.3)"} />
          <stop offset="100%" stopColor="rgba(255, 255, 255, 0)" />
        </linearGradient>
      </defs>
      <path className="sparkline-area" d={areaPath} fill={`url(#${gradientId})`} />
      <path className={isPositive ? "sparkline-path up" : "sparkline-path down"} d={path} />
      <circle className={isPositive ? "sparkline-marker up" : "sparkline-marker down"} cx={endX} cy={endY} r="3.5" />
    </svg>
  );
}
