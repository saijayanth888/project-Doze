import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { C } from '../../config/colors';
import { apiFetch } from '../../config/api';

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [champion, setChampion] = useState(null);

  useEffect(() => {
    const load = () => apiFetch('/api/models/champion').then(setChampion).catch(() => {});
    load();
    const iv = setInterval(load, 15_000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div style={{ display: 'flex', height: '100vh', background: C.bg, overflow: 'hidden' }}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} champion={champion} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        <TopBar champion={champion} />
        <main
          className="mf-dashboard-canvas"
          style={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            overflowY: 'auto',
            padding: 24,
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
