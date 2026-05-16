// Generischer Fortschrittsbalken fuer Kalorien/Protein.
// `current` und `target` sind Zahlen, `accent` ist eine Ampel-Stufe.
const ACCENT_BG = {
  good: "bg-good",
  warn: "bg-warn",
  bad: "bg-bad",
  active: "bg-active",
  muted: "bg-muted",
};

export default function NutritionBar({
  label,
  current,
  target,
  unit = "g",
  accent = "muted",
  sub,
}) {
  const pct = target > 0 ? Math.min(150, Math.max(0, (current / target) * 100)) : 0;
  const bar = ACCENT_BG[accent] || ACCENT_BG.muted;

  return (
    <div className="bg-card border border-border rounded-card p-3 mb-2">
      <div className="flex justify-between items-baseline mb-1">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          {label}
        </div>
        <div className="text-sm">
          <span className="font-semibold">
            {current == null ? "—" : Math.round(current)}
          </span>
          <span className="text-muted text-xs"> / {Math.round(target)} {unit}</span>
        </div>
      </div>
      <div className="h-2 bg-bg rounded-pill overflow-hidden border border-border">
        <div
          className={`h-full ${bar}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      {sub && <div className="text-[11px] text-muted mt-1">{sub}</div>}
    </div>
  );
}
