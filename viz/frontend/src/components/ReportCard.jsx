import { useState } from "react";

export default function ReportCard({ date }) {
  const [text, setText] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setLoading(true);
    setError(null);
    setText(null);
    try {
      const r = await fetch(`/api/report?date=${encodeURIComponent(date)}`);
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      setText(body.report || "");
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-card border border-border rounded-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          AI Report
        </div>
        <button
          onClick={generate}
          disabled={loading}
          className="text-xs px-3 py-2 rounded-pill bg-good text-bg font-semibold disabled:opacity-50"
        >
          {loading ? "Generating..." : text ? "Regenerate" : "Generate Report"}
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-muted text-sm">
          <span className="inline-block w-3 h-3 border-2 border-good border-t-transparent rounded-full animate-spin" />
          Calling Claude...
        </div>
      )}
      {error && <div className="text-bad text-sm">{error}</div>}
      {text && (
        <div className="text-sm whitespace-pre-line leading-relaxed text-white/90">
          {text}
        </div>
      )}
      {!text && !loading && !error && (
        <div className="text-muted text-xs">
          Klick auf Generate -- Claude liest die Tageswerte und schreibt
          einen kurzen Coach-Report.
        </div>
      )}
    </div>
  );
}
