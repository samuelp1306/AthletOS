import { useEffect, useState } from "react";
import { apiPost } from "../hooks/useApi.js";

// Morning Check-in: EINE Frage (Vollgas/Eingeschraenkt/Nein), bei den
// negativen Antworten ein optionaler Grund. Kein RPE -- das gehoert ins
// Training Log nach der Session, nicht in den Morgens-Check-in.

const READINESS_OPTIONS = [
  { id: "yes", label: "Full intensity" },
  { id: "limited", label: "Limited" },
  { id: "no", label: "No" },
];

const REASON_OPTIONS = [
  { id: "soreness", label: "Soreness" },
  { id: "fatigue", label: "Fatigue" },
  { id: "mental", label: "Mental" },
  { id: "sleep", label: "Bad sleep" },
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
  const [readiness, setReadiness] = useState(initial?.readiness || null);
  const [reason, setReason] = useState(initial?.reason || "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  // Daten kommen evtl. asynchron rein, oder Datum wechselt
  useEffect(() => {
    if (initial?.readiness) {
      setReadiness(initial.readiness);
      setReason(initial.reason || "");
      setExpanded(false);
    } else {
      setReadiness(null);
      setReason("");
      setExpanded(true);
    }
  }, [date, initial?.readiness, initial?.reason]);

  const needsReason = readiness === "limited" || readiness === "no";
  const canSubmit =
    readiness != null && (!needsReason || (reason && reason !== ""));

  async function submit() {
    if (!canSubmit) return;
    setSaving(true);
    setErr(null);
    try {
      // 'yes' speichert reason 'none' fuer konsistente Auswertung downstream.
      const payload = {
        date,
        readiness,
        reason: needsReason ? reason : "none",
        rpe: null,
      };
      await apiPost("/api/checkin", payload);
      onSaved?.(payload);
      setExpanded(false);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  // ---------- Collapsed ----------
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
                  {" "}· {REASON_LABEL[reason] || reason}
                </span>
              )}
            </div>
          </div>
        </div>
        <span className="text-muted text-xs">Edit</span>
      </button>
    );
  }

  // ---------- Expanded ----------
  return (
    <div className="bg-card border border-border rounded-card p-4 mb-4">
      <div className="text-[10px] tracking-widest text-muted uppercase mb-3">
        Ready for full intensity?
      </div>

      {/* Drei grosse Buttons -- die einzige Frage */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {READINESS_OPTIONS.map((o) => {
          const isOn = readiness === o.id;
          const variant =
            o.id === "yes"
              ? "good"
              : o.id === "limited"
              ? "warn"
              : "bad";
          const classes = isOn
            ? variant === "good"
              ? "bg-good/15 border-good text-good"
              : variant === "warn"
              ? "bg-warn/15 border-warn text-warn"
              : "bg-bad/15 border-bad text-bad"
            : "border-border text-muted";

          return (
            <button
              key={o.id}
              onClick={() => {
                setReadiness(o.id);
                // 'yes' braucht keinen Grund -> reset
                if (o.id === "yes") setReason("");
              }}
              className={`py-4 rounded-pill text-base font-medium border-2 ${classes}`}
            >
              {o.label}
            </button>
          );
        })}
      </div>

      {/* Reason nur wenn limited/no */}
      {needsReason && (
        <div className="mb-3">
          <label className="block text-xs text-muted mb-1">Reason</label>
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full bg-bg border border-border rounded-pill px-3 py-3 text-base text-white"
          >
            <option value="">Please choose ...</option>
            {REASON_OPTIONS.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <button
        onClick={submit}
        disabled={!canSubmit || saving}
        className="w-full py-3 rounded-pill bg-good text-bg font-semibold text-base disabled:opacity-40"
      >
        {saving ? "Saving..." : "Submit"}
      </button>
      {err && <div className="text-bad text-xs mt-2">{err}</div>}
    </div>
  );
}
