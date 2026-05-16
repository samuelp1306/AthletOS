// Grosse Score-Karte. Farbe nach Ampel (>=75 gruen, 50-74 gelb, <50 rot).
function trafficColor(score) {
  if (score >= 75) return "text-good";
  if (score >= 50) return "text-warn";
  return "text-bad";
}

export default function ScoreRing({
  adjusted,
  whoop,
  discrepancy,
  corrections = [],
}) {
  const color = trafficColor(adjusted);
  return (
    <div className="bg-card border border-border rounded-card p-6 mb-4 text-center">
      <div className={`text-7xl font-semibold leading-none ${color}`}>
        {adjusted}
      </div>
      <div className="text-[10px] tracking-widest text-muted uppercase mt-2">
        Readiness
      </div>
      {Math.abs(discrepancy ?? 0) > 15 && (
        <div className="text-xs text-muted mt-3">
          Whoop says {whoop}% — adjusted to {adjusted}%
        </div>
      )}
      {corrections.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2 mt-3">
          {corrections.map((c, i) => (
            <span
              key={i}
              className="text-[11px] px-2 py-1 rounded-pill border border-border text-muted"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
