// Mapped Flag-Quelle -> Akzentfarbe.
const KIND_STYLES = {
  warning: { border: "border-bad", bg: "bg-bad/10", text: "text-white" },
  monitor: { border: "border-warn", bg: "bg-warn/10", text: "text-white" },
  info: { border: "border-good", bg: "bg-good/10", text: "text-white" },
  bloodwork: { border: "border-[#a070d0]", bg: "bg-[#a070d0]/10", text: "text-white" },
};

export default function FlagBadge({ message, kind = "warning" }) {
  const s = KIND_STYLES[kind] || KIND_STYLES.warning;
  return (
    <div
      className={`${s.bg} ${s.text} border-l-[3px] ${s.border} rounded-card p-3 mb-2 text-sm leading-snug`}
    >
      {message}
    </div>
  );
}
