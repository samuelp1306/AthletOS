import { useApi } from "../hooks/useApi.js";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

// --- Farben fuer Discrepancy-Bars --------------------------------------

function discrepancyColor(value) {
  if (value == null) return "#3d4151";
  const abs = Math.abs(value);
  if (abs < 10) return "#00ff87";
  if (abs <= 20) return "#ffd60a";
  return "#ff3b3b";
}

function acwrColor(v) {
  if (v == null) return "#3d4151";
  if (v < 0.8) return "#ffd60a";
  if (v > 1.3) return "#ff3b3b";
  return "#00ff87";
}

// --- Helpers -----------------------------------------------------------

function mean(arr) {
  const nums = arr.filter((v) => v != null && !Number.isNaN(v));
  if (nums.length === 0) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function count(arr, pred) {
  return arr.filter(pred).length;
}

function shortDate(s) {
  // YYYY-MM-DD -> MM-DD
  return s ? s.slice(5) : "";
}

// --- Screen ------------------------------------------------------------

export default function Trends({ date }) {
  const { data, loading, error } = useApi(`/api/trends?days=30&end_date=${date}`, [date]);

  if (loading) {
    return (
      <div className="max-w-md mx-auto px-4 pt-4 text-muted text-sm">
        Loading trends...
      </div>
    );
  }
  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 pt-4 text-bad text-sm">{error}</div>
    );
  }
  if (!data || !data.dates || data.dates.length === 0) {
    return (
      <div className="max-w-md mx-auto px-4 pt-4 text-muted text-sm">
        No data in this range.
      </div>
    );
  }

  // Daten zu Recharts-tauglichen Rows umformen
  const rows = data.dates.map((d, i) => ({
    date: d,
    label: shortDate(d),
    hrv: data.hrv[i],
    recovery: data.recovery[i],
    adjusted: data.adjusted_readiness[i],
    acwr: data.acwr[i],
    sleep: data.sleep_hours[i],
    discrepancy: data.discrepancy[i],
  }));

  // HRV-Baseline ueber das Fenster
  const hrvBaseline = mean(rows.map((r) => r.hrv));

  // Weekly summary
  const avgReadiness = mean(rows.map((r) => r.adjusted));
  const avgSleep = mean(rows.map((r) => r.sleep));
  const trainingDays = count(rows.map((r) => r.recovery), (v) => v != null);
  const discCount = count(
    rows.map((r) => r.discrepancy),
    (v) => v != null && Math.abs(v) > 15
  );

  return (
    <div className="max-w-md mx-auto px-4 pt-4">
      {/* Header */}
      <div className="flex justify-between items-baseline mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          Trends · 30 days
        </div>
        <div className="text-xs text-muted">{date}</div>
      </div>

      {/* ---- 1. Discrepancy (USP, daher zuerst) ---- */}
      <div className="bg-card border border-border rounded-card p-4 mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase mb-2">
          Whoop vs Reality
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={rows} margin={{ top: 10, right: 6, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#1c1f26" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9 }}
              interval={Math.floor(rows.length / 6)}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "#1c1f26" }} />
            <ReferenceLine y={0} stroke="#3d4151" />
            <Bar dataKey="discrepancy" name="Δ Whoop − System">
              {rows.map((r, i) => (
                <Cell key={i} fill={discrepancyColor(r.discrepancy)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* ---- 2. HRV ---- */}
      <div className="bg-card border border-border rounded-card p-4 mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase mb-2">
          HRV (ms)
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={rows} margin={{ top: 10, right: 6, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#1c1f26" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9 }}
              interval={Math.floor(rows.length / 6)}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ stroke: "#3d4151" }} />
            {hrvBaseline != null && (
              <ReferenceLine
                y={hrvBaseline}
                stroke="#3d4151"
                strokeDasharray="3 3"
                label={{
                  value: `baseline ${hrvBaseline.toFixed(0)}`,
                  position: "insideTopRight",
                  fill: "#3d4151",
                  fontSize: 9,
                }}
              />
            )}
            <Line
              type="monotone"
              dataKey="hrv"
              stroke="#00ff87"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ---- 3. ACWR ---- */}
      <div className="bg-card border border-border rounded-card p-4 mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase mb-2">
          ACWR
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={rows} margin={{ top: 10, right: 6, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#1c1f26" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9 }}
              interval={Math.floor(rows.length / 6)}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              domain={[0.5, 1.6]}
            />
            <Tooltip cursor={{ stroke: "#3d4151" }} />
            <ReferenceLine y={1.0} stroke="#3d4151" strokeDasharray="3 3" />
            {/* Recharts faerbt eine Line-Path nicht segmentweise -- wir
                emulieren das, indem wir die Linie als unsichtbar zeichnen
                und stattdessen dots je Wert einfaerben. */}
            <Line
              type="monotone"
              dataKey="acwr"
              stroke="#1c1f26"
              strokeWidth={1}
              dot={(props) => {
                const { cx, cy, value } = props;
                if (value == null || cx == null || cy == null) return null;
                return (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={3}
                    fill={acwrColor(value)}
                    key={`${cx}-${cy}`}
                  />
                );
              }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ---- Weekly stats ---- */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <StatCard label="Avg Readiness" value={avgReadiness?.toFixed(0) ?? "—"} />
        <StatCard
          label="Avg Sleep"
          value={avgSleep != null ? `${avgSleep.toFixed(1)} h` : "—"}
        />
        <StatCard label="Training Days" value={trainingDays} />
        <StatCard label="High Discrepancy" value={discCount} />
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="bg-card border border-border rounded-card p-3">
      <div className="text-[9px] tracking-widest text-muted uppercase">
        {label}
      </div>
      <div className="text-xl font-semibold mt-1">{value}</div>
    </div>
  );
}
