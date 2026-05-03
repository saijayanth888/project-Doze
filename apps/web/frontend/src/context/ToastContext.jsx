import { createContext, useCallback, useContext, useMemo, useState } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [msg, setMsg] = useState(null);

  const show = useCallback((text, tone = 'info') => {
    setMsg({ text, tone, id: Date.now() });
    window.setTimeout(() => setMsg(null), 4000);
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {msg ? (
        <div
          role="status"
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 9999,
            maxWidth: 360,
            padding: '12px 16px',
            borderRadius: 8,
            fontFamily: 'var(--font-ui, Outfit, sans-serif)',
            fontSize: 13,
            color: 'var(--text-primary, #f1f5f9)',
            background: toneBg(msg.tone),
            border: '1px solid var(--border, #1e293b)',
            boxShadow: 'var(--shadow-tooltip, 0 8px 32px rgba(0,0,0,0.5))',
          }}
        >
          {msg.text}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

function toneBg(tone) {
  if (tone === 'danger') return 'rgba(239,68,68,0.15)';
  if (tone === 'success') return 'rgba(34,197,94,0.12)';
  return 'var(--bg-elevated, #1a2235)';
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) return { show: () => {} };
  return ctx;
}
