const ACCENT_CLASSES = {
  good: "border-good text-good",
  warn: "border-warn text-warn",
  bad: "border-bad text-bad",
  muted: "border-muted text-muted",
};

// Kompakte Karte fuer HRV/Sleep/RHR-Reihe. `accent` ist eine der Ampel-Stufen.
export default function MiniCard({ label, value, sub, accent = "muted" }) {
  const a = ACCENT_CLASSES[accent] || ACCENT_CLASSES.muted;
  return (
    <div className={`bg-card border-l-[3px] ${a.split(" ")[0]} rounded-card p-3 flex-1`}>
      <div className="text-[9px] tracking-widest text-muted uppercase">
        {label}
      </div>
      <div className={`text-2xl font-semibold mt-1 ${a.split(" ")[1]}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted mt-1 leading-tight">{sub}</div>}
    </div>
  );
}
