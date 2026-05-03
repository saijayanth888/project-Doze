export default function Ticker({ items = [] }) {
  const doubled = [...items, ...items];
  return (
    <div className="overflow-hidden w-full" style={{ height: 32, background: '#0c1018', borderBottom: '1px solid #1e293b' }}>
      <div
        className="flex items-center gap-8 h-full whitespace-nowrap animate-ticker"
        style={{ width: 'max-content' }}
      >
        {doubled.map((item, i) => (
          <span key={i} className="flex items-center gap-2 text-xs font-mono">
            <span style={{ color: '#64748b' }}>{item.label}</span>
            <span style={{ color: item.color || '#f1f5f9', fontWeight: 600 }}>{item.value}</span>
            <span style={{ color: '#1e293b' }}>|</span>
          </span>
        ))}
      </div>
    </div>
  );
}
