// Topics and event names of a result, from the index (or the AI once the file was summarised).
// Renders nothing until there is something to show, so cards do not jump while topics load.

interface Props {
  topics?: string[];
  events?: string[];
  max?: number;
  className?: string;
}

export default function TopicChips({ topics = [], events = [], max = 3, className = '' }: Props) {
  const eventKeys = new Set(events.map((e) => e.toLowerCase()));
  const all = [
    ...events.map((label) => ({ label, event: true })),
    ...topics.filter((t) => !eventKeys.has(t.toLowerCase())).map((label) => ({ label, event: false })),
  ];
  if (all.length === 0) return null;
  const shown = all.slice(0, max);
  const rest = all.slice(max);
  return (
    <div className={`flex flex-wrap items-center gap-1 ${className}`} aria-label="Topics">
      {shown.map((t) => (
        <span
          key={t.label}
          className="max-w-[11rem] truncate px-2 py-0.5 rounded-full text-[10px] font-semibold"
          title={t.event ? `Event: ${t.label}` : t.label}
          style={{
            background: t.event ? 'var(--accent-ai-muted)' : 'var(--bg-active)',
            color: t.event ? 'var(--accent-ai)' : 'var(--text-secondary)',
          }}
        >
          {t.event ? '◆ ' : ''}{t.label}
        </span>
      ))}
      {rest.length > 0 && (
        <span className="text-[10px] font-semibold" style={{ color: 'var(--text-muted)' }} title={rest.map((r) => r.label).join(', ')}>
          +{rest.length}
        </span>
      )}
    </div>
  );
}
