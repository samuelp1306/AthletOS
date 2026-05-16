import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import Banner from "../components/Banner.jsx";
import ScoreRing from "../components/ScoreRing.jsx";
import MiniCard from "../components/MiniCard.jsx";
import LoadStatus from "../components/LoadStatus.jsx";
import CheckIn from "../components/CheckIn.jsx";

// --- Ampel-Helfer ------------------------------------------------------

function trafficHrv(value, baseline) {
  if (value == null || !baseline) return "muted";
  const delta = ((value - baseline) / baseline) * 100;
  if (delta >= -5) return "good";
  if (delta >= -10) return "warn";
  return "bad";
}

function trafficSleep(h, e) {
  if (h == null || e == null) return "muted";
  if (h >= 7.5 && e >= 90) return "good";
  if (h < 6 || e < 75) return "bad";
  return "warn";
}

function trafficRhr(value, baseline) {
  if (value == null || !baseline) return "muted";
  // RHR niedriger = besser. Vergleich: >baseline+3 = schlecht
  const delta = value - baseline;
  if (delta <= 0) return "good";
  if (delta <= 3) return "warn";
  return "bad";
}

// --- Screen ------------------------------------------------------------

export default function Today({ date }) {
  const [refresh, setRefresh] = useState(0);
  const { data, error, loading } = useApi(`/api/daily?date=${date}`, [date, refresh]);

  return (
    <div className="max-w-md mx-auto px-4 pt-4">
      {/* Header */}
      <div className="flex justify-between items-baseline mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          Performance OS
        </div>
        <div className="text-xs text-muted">{date}</div>
      </div>

      {/* Check-In (auch ohne /daily-Antwort schon bedienbar) */}
      <CheckIn
        date={date}
        initial={
          data && data.checkin
            ? { readiness: data.checkin, reason: data.checkin_reason, rpe: data.rpe }
            : null
        }
        onSaved={() => setRefresh((r) => r + 1)}
      />

      {loading && (
        <div className="text-muted text-sm py-6 text-center">Loading...</div>
      )}
      {error && (
        <div className="text-bad text-sm py-6 text-center">
          {error}
        </div>
      )}

      {data && !error && (
        <>
          {/* Recommendation Banner */}
          <Banner protocol={data.protocol} />

          {/* Readiness Score */}
          <ScoreRing
            adjusted={data.adjusted_readiness}
            whoop={data.whoop_recovery}
            discrepancy={data.discrepancy}
            corrections={data.corrections_applied || []}
          />

          {/* Mini-Karten HRV / Sleep / RHR */}
          <div className="flex gap-2 mb-4">
            <MiniCard
              label="HRV"
              value={data.hrv != null ? `${Math.round(data.hrv)} ms` : "—"}
              sub={
                data.hrv != null && data.hrv_baseline
                  ? `${(((data.hrv - data.hrv_baseline) / data.hrv_baseline) * 100).toFixed(0)}% vs base`
                  : "—"
              }
              accent={trafficHrv(data.hrv, data.hrv_baseline)}
            />
            <MiniCard
              label="Sleep"
              value={data.sleep_hours != null ? `${data.sleep_hours.toFixed(1)} h` : "—"}
              sub={
                data.sleep_efficiency != null
                  ? `${Math.round(data.sleep_efficiency)}% eff`
                  : "—"
              }
              accent={trafficSleep(data.sleep_hours, data.sleep_efficiency)}
            />
            <MiniCard
              label="RHR"
              value={data.rhr != null ? `${Math.round(data.rhr)} bpm` : "—"}
              sub={
                data.rhr != null && data.rhr_baseline
                  ? `${(data.rhr - data.rhr_baseline).toFixed(1)} bpm`
                  : "—"
              }
              accent={trafficRhr(data.rhr, data.rhr_baseline)}
            />
          </div>

          {/* Plain-English Status-Satz */}
          <LoadStatus daily={data} />
        </>
      )}
    </div>
  );
}
