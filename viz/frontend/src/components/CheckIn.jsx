import { useEffect, useState } from "react";
import { apiPost } from "../hooks/useApi.js";

const READINESS_OPTIONS = [
  { id: "yes", label: "Ja" },
  { id: "limited", label: "Limited" },
  { id: "no", label: "Nein" },
];

const REASON_OPTIONS = [
  { id: "none", label: "Good" },
  { id: "soreness", label: "Soreness" },
  { id: "fatigue", label: "Fatigue" },
  { id: "mental", label: "Mental" },
  { id: "deficit", label: "Deficit" },
  { id: "sleep", label: "Bad Sleep" },
];

const READINESS_LABEL = Object.fromEntries(
  READINESS_OPTIONS.map((o) => [o.id, o.label])
);
const REASON_LABEL = Object.fromEntries(
  REASON_OPTIONS.map((o) => [o.id, o.label])
);

export default function CheckIn({ date, initial, onSaved }) {
  const wasSubmitted = !!(initial && initial.readiness);

  const [expanded, setExpanded] = useState(!wasSubmitted);
  const [rpe, setRpe] = useState(initial?.rpe ?? 5);
  const [readiness, setReadiness] = useState(initial?.readiness || "yes");
  const [reason, setReason] = useState(initial?.reason || "none");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  // Daten kommen evtl. asynchron rein
  useEffect(() => {
    if (initial?.readiness) {
      setRpe(initial.rpe ?? 5);
      setReadiness(initial.readiness);
      setReason(initial.reason || "none");
      setExpanded(false);
    }
  }, [initial?.readiness, initial?.rpe, initial?.reason]);

  async function submit() {
    setSaving(true);
    setErr(null);
    try {
      await apiPost("/api/checkin", { date, rpe, readiness, reason });
      onSaved?.({ rpe, readiness, reason });
      setExpanded(false);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  // ---------- Collapsed -----------
  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full bg-card border border-border rounded-card p-3 mb-4 flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <span className="text-good text-xl leading-none">✓</span>
          <div className="text-left">
            <div className="text-[10px] tracking-widest text-muted uppercase">
              Check-in
            </div>
            <div className="text-sm">
              {READINESS_LABEL[readiness] || readiness}
              {reason && reason !== "none" && (
                <span className="text-muted">
                  {" "}
                  · {REASON_LABEL[reason] || reason}
                </span>
              )}
              {rpe != null && (
                <span className="text-muted"> · RPE {rpe}</span>
              )}
            </div>
          </div>
        </div>
        <span className="text-muted text-xs">Edit</span>
      </button>
    );
  }

  // ---------- Expanded -----------
  return (
    <div className="bg-card border border-border rounded-card p-4 mb-4">
      <div className="text-[10px] tracking-widest text-muted uppercase mb-3">
        Check-in
      </div>

      {/* RPE */}
      <label className="block text-xs text-muted mb-1">RPE · {rpe}</label>
      <input
        type="range"
        min="1"
        max="10"
        step="1"
        value={rpe}
        onChange={(e) => setRpe(Number(e.target.value))}
        className="w-full mb-4"
      />

      {/* Readiness Buttons */}
      <div className="text-xs text-muted mb-1">Vollgas heute?</div>
      <div className="grid grid-cols-3 gap-2 mb-4">
        {READINESS_OPTIONS.map((o) => {
          const isOn = readiness === o.id;
          return (
            <button
              key={o.id}
              onClick={() => setReadiness(o.id)}
              className={
                "py-2 rounded-pill text-sm border " +
                (isOn
                  ? "bg-good/10 border-good text-good"
                  : "border-border text-muted")
              }
            >
              {o.label}
            </button>
          );
        })}
      </div>

      {/* Reason */}
      <label className="block text-xs text-muted mb-1">Grund</label>
      <select
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="w-full bg-bg border border-border rounded-pill px-3 py-2 text-sm mb-4 text-white"
      >
        {REASON_OPTIONS.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>

      <button
        onClick={submit}
        disabled={saving}
        className="w-full py-2 rounded-pill bg-good text-bg font-semibold text-sm disabled:opacity-50"
      >
        {saving ? "Saving..." : "Submit"}
      </button>
      {err && <div className="text-bad text-xs mt-2">{err}</div>}
    </div>
  );
}
