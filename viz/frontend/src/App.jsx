import { useState } from "react";
import Today from "./screens/Today.jsx";
import Trends from "./screens/Trends.jsx";
import Report from "./screens/Report.jsx";
import TabBar from "./components/TabBar.jsx";
import { todayIso } from "./hooks/useApi.js";

export default function App() {
  const [tab, setTab] = useState("today");
  const [date] = useState(todayIso());

  return (
    <div className="min-h-screen bg-bg text-white pb-20">
      {tab === "today" && <Today date={date} />}
      {tab === "trends" && <Trends date={date} />}
      {tab === "report" && <Report date={date} />}
      <TabBar active={tab} onChange={setTab} />
    </div>
  );
}
