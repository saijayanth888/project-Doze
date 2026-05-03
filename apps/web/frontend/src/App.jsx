import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';

const LandingPage = lazy(() => import('./pages/LandingPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LineagePage = lazy(() => import('./pages/LineagePage'));
const BenchmarksPage = lazy(() => import('./pages/BenchmarksPage'));
const PlaygroundPage = lazy(() => import('./pages/PlaygroundPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

function PageFallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '40vh',
        color: 'var(--text-muted, #64748b)',
        fontFamily: 'var(--font-mono, monospace)',
        fontSize: 13,
      }}
    >
      Loading…
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/lineage" element={<LineagePage />} />
            <Route path="/benchmarks" element={<BenchmarksPage />} />
            <Route path="/playground" element={<PlaygroundPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
