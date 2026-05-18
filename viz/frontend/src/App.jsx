import { useState } from "react";
import Today from "./screens/Today.jsx";
import Trends from "./screens/Trends.jsx";
import Report from "./screens/Report.jsx";
import TabBar from "./components/TabBar.jsx";

// Demo-Default: ein Tag mit echten Daten in der DB. todayIso() waere
// korrekt, aber bis whoop.py mit frischen Daten gelaufen ist, zeigt die
// App sonst nur 'Keine Daten'. Hier bei Bedarf auf todayIso() umstellen.
const DEMO_DATE = "2026-04-16";

export default function App() {
  const [tab, setTab] = useState("today");
  const [date] = useState(DEMO_DATE);

  return (
    <div className="min-h-screen bg-bg text-white pb-20">
      {tab === "today" && <Today date={date} />}
      {tab === "trends" && <Trends date={date} />}
      {tab === "report" && <Report date={date} />}
      <TabBar active={tab} onChange={setTab} />
    </div>
  );
}
