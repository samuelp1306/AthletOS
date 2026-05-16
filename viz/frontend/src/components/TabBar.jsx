const TABS = [
  { id: "today", label: "Today" },
  { id: "trends", label: "Trends" },
  { id: "report", label: "Report" },
];

export default function TabBar({ active, onChange }) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-card border-t border-border safe-bottom">
      <div className="max-w-md mx-auto flex">
        {TABS.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              className={
                "flex-1 py-3 text-[11px] uppercase tracking-widest " +
                (isActive ? "text-good" : "text-muted")
              }
            >
              {t.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
