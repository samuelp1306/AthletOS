import { useApi } from "../hooks/useApi.js";
import Banner from "../components/Banner.jsx";
import FlagBadge from "../components/FlagBadge.jsx";
import NutritionBar from "../components/NutritionBar.jsx";
import ReportCard from "../components/ReportCard.jsx";

function caloriesAccent(deficit) {
  if (deficit == null) return "muted";
  if (deficit > 400) return "bad";
  if (deficit >= 200) return "warn";
  return "good";
}

export default function Report({ date }) {
  const { data: daily, loading: dl, error: de } = useApi(
    `/api/daily?date=${date}`,
    [date]
  );
  const { data: nut } = useApi(`/api/nutrition?date=${date}`, [date]);

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

      {daily && <Banner protocol={daily.protocol} />}

      {/* ---- Flags ---- */}
      {daily?.protocol && (
        <FlagSection protocol={daily.protocol} />
      )}

      {/* ---- Nutrition ---- */}
      <div className="mb-4">
        <div className="text-[10px] tracking-widest text-muted uppercase mb-2 px-1">
          Nutrition
        </div>

        {!nut?.available && (
          <div className="bg-card border border-border rounded-card p-3 text-muted text-sm">
            Keine Ernaehrungsdaten fuer diesen Tag.
          </div>
        )}

        {nut?.available && (
          <>
            <NutritionBar
              label="Calories"
              current={nut.calories}
              target={nut.tdee}
              unit="kcal"
              accent={caloriesAccent(nut.deficit)}
              sub={
                nut.deficit != null
                  ? (nut.deficit > 0
                      ? `${Math.round(nut.deficit)} kcal unter TDEE`
                      : `${Math.abs(Math.round(nut.deficit))} kcal ueber TDEE`)
                  : null
              }
            />
            <NutritionBar
              label="Protein"
              current={nut.protein}
              target={nut.protein_target}
              unit="g"
              accent={
                nut.protein != null && nut.protein >= nut.protein_target
                  ? "good"
                  : "bad"
              }
            />
            {nut.carbs != null && (
              <div className="bg-card border border-border rounded-card p-3 mb-2">
                <div className="flex justify-between items-baseline">
                  <div className="text-[10px] tracking-widest text-muted uppercase">
                    Carbs
                  </div>
                  <div className="text-sm">
                    <span className="font-semibold">{Math.round(nut.carbs)} g</span>
                    {nut.weight_kg ? (
                      <span className="text-muted text-xs">
                        {" "}
                        · {(nut.carbs / nut.weight_kg).toFixed(1)} g/kg
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ---- AI Report ---- */}
      <ReportCard date={date} />
    </div>
  );
}

function FlagSection({ protocol }) {
  const flags = protocol.flags || [];
  const nut = protocol.nutrition_flags || [];
  const blood = protocol.bloodwork_flags || [];
  const total = flags.length + nut.length + blood.length;
  if (total === 0) return null;

  return (
    <div className="mb-4">
      <div className="text-[10px] tracking-widest text-muted uppercase mb-2 px-1">
        Aktive Flags · {total}
      </div>
      {flags.map((m, i) => (
        <FlagBadge key={`f${i}`} message={m} kind="warning" />
      ))}
      {nut.map((m, i) => (
        <FlagBadge key={`n${i}`} message={m} kind="monitor" />
      ))}
      {blood.map((m, i) => (
        <FlagBadge key={`b${i}`} message={m} kind="bloodwork" />
      ))}
    </div>
  );
}
