// Mapped training_recommendation -> Tailwind-Klassen + Label
const STYLES = {
  full_intensity: {
    bg: "bg-[#0a2818]",
    border: "border-good",
    text: "text-good",
    label: "FULL INTENSITY",
  },
  reduced: {
    bg: "bg-[#2a2410]",
    border: "border-warn",
    text: "text-warn",
    label: "REDUCED",
  },
  active_recovery: {
    bg: "bg-[#2a1a10]",
    border: "border-active",
    text: "text-active",
    label: "ACTIVE RECOVERY",
  },
  rest: {
    bg: "bg-[#2a1010]",
    border: "border-bad",
    text: "text-bad",
    label: "REST",
  },
};

export default function Banner({ protocol }) {
  if (!protocol || protocol.error) {
    return (
      <div className="bg-card border-l-[3px] border-muted rounded-card p-4 mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          Recommendation
        </div>
        <div className="text-2xl font-semibold mt-1">—</div>
        <div className="text-sm text-muted mt-1">
          No protocol output available.
        </div>
      </div>
    );
  }

  const s = STYLES[protocol.training_recommendation] || STYLES.reduced;
  const reasons = (protocol.recommendation_reasons || []).slice(0, 3);

  return (
    <div className={`${s.bg} border-l-[3px] ${s.border} rounded-card p-4 mb-4`}>
      <div className="text-[10px] tracking-widest text-muted uppercase">
        Recommendation · {protocol.confidence}
      </div>
      <div className={`text-2xl font-semibold mt-1 ${s.text}`}>{s.label}</div>
      {reasons.length > 0 && (
        <ul className="mt-2 space-y-1">
          {reasons.map((r, i) => (
            <li key={i} className="text-sm text-white/80 leading-snug">
              {r}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
