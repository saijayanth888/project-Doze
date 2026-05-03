export default function PatentBadge({ className = '' }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold tracking-widest border ${className}`}
      style={{ color: '#d4a574', borderColor: '#d4a574', background: 'rgba(212,165,116,0.08)' }}
    >
      PAT. PEND.
    </span>
  );
}
