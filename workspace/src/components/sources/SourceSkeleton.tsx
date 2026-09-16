'use client';

export function SourceSkeleton() {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
    >
      {/* Thumbnail */}
      <div className="skeleton" style={{ paddingTop: '56.25%', width: '100%' }} />
      <div className="p-3 space-y-2">
        {/* Title */}
        <div className="skeleton rounded h-4 w-full" />
        <div className="skeleton rounded h-4 w-3/4" />
        {/* Meta */}
        <div className="flex gap-2">
          <div className="skeleton rounded h-3 w-16" />
          <div className="skeleton rounded h-3 w-12" />
        </div>
        {/* Description */}
        <div className="skeleton rounded h-3 w-full" />
        <div className="skeleton rounded h-3 w-5/6" />
        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <div className="skeleton rounded-lg h-7 w-20" />
          <div className="skeleton rounded-lg h-7 w-16" />
        </div>
      </div>
    </div>
  );
}
