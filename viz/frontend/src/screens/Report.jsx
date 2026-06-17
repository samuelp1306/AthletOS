import { useApi } from "../hooks/useApi.js";
import Banner from "../components/Banner.jsx";
import FlagBadge from "../components/FlagBadge.jsx";
import ReportCard from "../components/ReportCard.jsx";

export default function Report({ date }) {
  const { data: daily, loading: dl, error: de } = useApi(
    `/api/daily?date=${date}`,
    [date]
  );

  return (
    <div className="max-w-md mx-auto px-4 pt-4">
      <div className="flex justify-between items-baseline mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase">
          Report
        </div>
        <div className="text-xs text-muted">{date}</div>
      </div>

      {dl && <div className="text-muted text-sm">Loading...</div>}
      {de && <div className="text-bad text-sm">{de}</div>}

      {daily && daily.available === false && (
        <div className="bg-card border-l-[3px] border-muted rounded-card p-4 mb-4">
          <div className="text-[10px] tracking-widest text-muted uppercase">
            No data
          </div>
          <div className="mt-2 text-sm leading-snug">
            {daily.message || "No Whoop data for this day."}
          </div>
        </div>
      )}

      {daily && daily.available !== false && <Banner protocol={daily.protocol} />}

      {/* ---- Flags ---- */}
      {daily?.available !== false && daily?.protocol && (
        <FlagSection protocol={daily.protocol} />
      )}

      {/* ---- AI Report ---- */}
      <ReportCard date={date} />
    </div>
  );
}

function FlagSection({ protocol }) {
  const flags = protocol.flags || [];
  const blood = protocol.bloodwork_flags || [];
  const total = flags.length + blood.length;
  if (total === 0) return null;

  return (
    <div className="mb-4">
      <div className="text-[10px] tracking-widest text-muted uppercase mb-2 px-1">
        Active flags · {total}
      </div>
      {flags.map((m, i) => (
        <FlagBadge key={`f${i}`} message={m} kind="warning" />
      ))}
      {blood.map((m, i) => (
        <FlagBadge key={`b${i}`} message={m} kind="bloodwork" />
      ))}
    </div>
  );
}
