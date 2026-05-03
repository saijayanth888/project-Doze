# ModelForge Frontend — Design Spec
**Date:** 2026-05-03  
**Status:** Approved

## Overview
Complete 6-page SPA for ModelForge, a self-evolving LLM platform. Single self-contained HTML file — CDN React 18 + Babel + D3, no build tool. Extends the existing `model-forge/frontend/index.html` (1060-line dashboard-only prototype) to all 6 pages.

## Architecture

**File:** `model-forge/frontend/index.html` (single file, complete rewrite)  
**Routing:** Hash-based (`#/`, `#/dashboard`, `#/lineage`, `#/benchmarks`, `#/playground`, `#/settings`)  
**Charts:** D3 SVG (matching existing code and design system prototypes — animated line-draw, full CSS control)  
**Icons:** Inline SVG paths (no external icon CDN)  
**API:** `http://localhost:8000` — live fetch with mock-data fallback on error  
**State:** React `useState` / `useReducer` only. No localStorage/sessionStorage.

## Design System

**Fonts:** Instrument Serif (headlines), Outfit (UI/labels), JetBrains Mono (numbers/metrics/paths)  
**Colors:**
- Backgrounds: `#06080d` page, `#0c1018` sidebar, `#111827` cards, `#1a2235` elevated
- Primary accent: `#76b900` NVIDIA green (CTAs, live states, promoted)
- Secondary: `#818cf8` indigo (AI/intelligence)
- Evolution gradient: `linear-gradient(135deg, #818cf8, #c084fc, #f472b6)`
- Patent gold: `#d4a574` (badges and IP callouts only)
- Semantic: `#22c55e` success, `#f59e0b` warning, `#ef4444` danger

**Theme:** Dark luxe-industrial mission control. Bloomberg Terminal meets SpaceX dashboard.

## Pages

### Page 1: Landing (`#/`)
- Hero with typing reveal animation ("Models That Evolve Themselves"), mesh gradient bg, magnetic CTA buttons
- Live ticker (infinite horizontal scroll, pause on hover)
- How It Works: 6-step grid with stagger entrance
- Protected Innovation: 3 patent cards with gold borders
- Tech Stack: badge grid
- Footer with patent/copyright text

### Page 2: Dashboard (`#/dashboard`)
- Fixed topbar (56px): breadcrumb + GPU/memory/champion stats
- Collapsible sidebar (240px→64px): sliding green active indicator
- 6 panels with stagger card entrance:
  1. Evolution Status: animated gradient border when running, FlipCounter gen number, 7-step progress, radar ping
  2. Score Trends: D3 LineChart, 5 benchmarks, animated draw, custom tooltip
  3. Champion Card: floating crown, ScoreBar per benchmark, RadarChart (D3 SVG), action buttons
  4. Latest Generation: parent vs child comparison, delta bars
  5. GPU Monitor: animated progress bars, temp, platform
  6. Activity Feed: slide-in events, proprietary method callouts in patent gold

### Page 3: Lineage (`#/lineage`)
- Full-width D3 tree: nodes sized by avg score, promoted=green/discarded=red
- Champion path: pulsing glow edges
- Node birth animation (spring easing)
- Click node → detail panel slides from right
- Zoom/pan via D3 zoom
- Diagonal MODELFORGE watermark at 3% opacity

**Shipped app (Vite) note:** routing uses **React Router** paths (`/lineage`, not hash). The tree is **React + SVG** (not D3 in the current implementation), loads `GET /api/lineage/tree`, and uses `viewBox` + `preserveAspectRatio="xMidYMid meet"`. The chart wrapper must receive height from a **flex chain** (`Layout` `<main>` column flex + `minHeight: 0` → `LineagePage` `flex: 1` → tree wrapper `flex: 1` → `LineageTree` `height: 100%`); otherwise the SVG collapses and the graph appears clipped.

### Page 4: Benchmarks (`#/benchmarks`)
- Sortable heatmap table (25 gens × 5 benchmarks)
- Solid hex cell bg colors (pre-blended, no RGBA)
- Crosshair hover: row+col highlight + cell scale
- 5 compact D3 trend charts below table

### Page 5: Playground (`#/playground`)
- Split pane: textarea + two response panels
- Typewriter animation on responses (20ms/char)
- DNA helix loading spinner
- Generation selector (range slider)
- API: POST `/api/infer` with mock fallback

### Page 6: Settings (`#/settings`)
- Evolution config sliders (max gens, batch size, LR, LoRA rank/alpha)
- Benchmark checkboxes
- API key fields with show/hide toggle and Connected/Not Set badges
- System info card (fetches `/api/system/gpu`)
- n8n webhook URL + notification toggles

## Mock Data
25 generations seeded: gens 1-5 modest gains, 6-15 steady climb, 16-20 plateau, 21-25 breakthrough.
Base scores: MMLU 0.634, ARC 0.582, HellaSwag 0.612, GSM8K 0.471, HumanEval 0.354. ~65% promotion rate.

## API Integration (preserve & extend)
Existing endpoints used by dashboard:
- `GET /api/evolution/status` → Evolution Status panel
- `GET /api/models/champion` → Champion card
- `GET /api/evolution/generations` → Score trends + benchmarks
- `GET /api/system/gpu` → GPU monitor + Settings system info
- `POST /api/evolve/start` / `POST /api/evolve/stop` → Start/Stop buttons
- `POST /api/infer` (new) → Playground compare

All API calls wrapped in try/catch with mock-data fallback.

## Animations (all required)
FlipCounter, typing reveal, card stagger (slide-up-fade), node-birth spring, crown float (translateY oscillation), radar ping, gradient shimmer border, sparkline draw, ticker scroll, magnetic hover + ripple, D3 chart line draw, crosshair heatmap, DNA helix spinner, slide-in-right activity feed.

## Patent Elements
- `PAT. PEND.` badge (patent gold) on Evolution Status panel
- `™` method callouts in Activity Feed with tooltip "ModelForge Proprietary Method"
- Protected Innovation section on Landing
- Diagonal MODELFORGE watermark on Lineage tree
- Patent gold footer text
