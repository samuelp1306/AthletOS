// Plain-English Status-Satz auf Basis von training_recommendation + Kontext.
// Keine Zahlen, keine Charts, keine Zonen -- ein Satz.

function pickSentence(daily) {
  if (!daily) return "";
  const rec = daily.protocol?.training_recommendation;
  const zone = daily.acwr_zone;
  const reasons = daily.protocol?.recommendation_reasons || [];
  const flagCount = (daily.protocol?.flags || []).length;
  const text = reasons.join(" ").toLowerCase();

  if (rec === "full_intensity" && zone === "optimal") {
    return "All systems green. Train hard today.";
  }
  if (rec === "reduced" && /soreness/.test(text)) {
    return "Your body needs lighter work today.";
  }
  if (rec === "reduced") {
    return "Hold intensity back today.";
  }
  if (rec === "active_recovery") {
    return "Recovery day. Light movement only.";
  }
  if (rec === "rest" && flagCount >= 3) {
    return "Multiple warning signals. Full rest recommended.";
  }
  if (rec === "rest") {
    return "Full rest recommended today.";
  }
  return "Listen to your body today.";
}

export default function LoadStatus({ daily }) {
  return (
    <div className="bg-card border border-border rounded-card p-4 mb-4">
      <div className="text-[10px] tracking-widest text-muted uppercase">
        Today
      </div>
      <p className="mt-2 text-lg leading-snug">{pickSentence(daily)}</p>
    </div>
  );
}
