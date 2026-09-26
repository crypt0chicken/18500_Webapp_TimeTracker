```markdown
# Pool Deck Time Tracker (TimeTracker)

A performance tracking and real-time analytics web application designed for competitive swim teams. The platform ingests telemetry from poolside compute units and swimmer wearables to display live workout metrics to coaches on deck and record historical split, stroke, and efficiency data for athletes.

---

## Technical Stack

* **Backend:** Python 3.10+, Django 5+
* **Real-Time Telemetry:** Django Channels (ASGI), Daphne, Redis (with in-memory fallback for local development)
* **Frontend:** Django Templates + Alpine.js (Hybrid architecture), CSS Custom Properties (Indoor/Outdoor High-Contrast Engine)
* **Database:** SQLite (local development), PostgreSQL (production target via `dj-database-url`)

---

## Project Structure

```text
TimeTracker/
├── accounts/               # Custom user model with role-based permissions (Admin, Coach, Swimmer)
├── config/                 # Project configuration, ASGI/WSGI handlers, and routing
│   ├── settings.py
│   ├── asgi.py             # Configured with ProtocolTypeRouter and URLRouter
│   └── urls.py             # Root redirection to active session staging & admin
├── scripts/
│   ├── mock_telemetry_generator.py      # Simulates 1-50 concurrent swimmer data streams
│   ├── verify_step2_concurrency.py      # Concurrency stress test (zero loss, <60ms p95 latency)
│   └── verify_step4_staging.py          # Rapid 8-tag deck staging & pairing validation benchmark
├── tracker/                # Swim analytics domain models, state machine, and persistence
│   ├── admin.py            # Tabular inlines, filters, and tag assignment actions
│   ├── consumers.py        # Async WebSocket consumer managing room groups & state transitions
│   ├── jitter_buffer.py    # Out-of-order reassembly, sequencing, and timeout flushing queue
│   ├── models.py           # PracticeSession, LaneAssignment, Repetition, LapSplit, HardwareTag, etc.
│   ├── permissions.py      # Role verification decorators & metric boundary checks
│   ├── persistence.py      # Event-driven async SQL persistence for completed reps and splits
│   ├── routing.py          # WebSocket URL routing patterns
│   ├── state_machine.py    # 4-state lifecycle, impulse push-off, backtracking, and metrics
│   ├── static/             # Static assets (style.css with wet-deck touch ergonomics)
│   │   └── tracker/css/style.css
│   ├── templates/          # Base template and touch-first deck staging interfaces
│   │   └── tracker/
│   │       ├── base.html
│   │       └── staging.html
│   ├── tests.py            # Complete test suite (Steps 1, 2, 3, and 4 validation)
│   ├── urls.py             # Staging, pairing, swapping, unassigning, and metric routes
│   └── views.py            # Deck staging view, 3-tap pair API, 1-tap swap modal API
├── manage.py
└── README.md

```

---

## Implemented Architecture & Features

### Step 1: Core Architecture & Access Control

* Custom `User` model supporting `ADMIN`, `COACH`, and `SWIMMER` roles.
* Domain models: `Team`, `SwimmerProfile`, `PersonalBest`, `HardwareTag`, `PracticeSession`, `WorkoutSet`, `Repetition`, `LapSplit`, and singleton `SystemConfiguration`.
* Pool standards supported: `SCY_25Y` (25yd), `SCM_25M` (25m), and `LCM_50M` (50m).
* Role verification decorators and configurable teammate leaderboard visibility boundaries.

### Step 2: Real-Time Ingestion Pipeline

* Asynchronous WebSocket routing (`/ws/pool/<session_id>/`) managed via Channels and room groups.
* Stream-level `StreamJitterBuffer` for sequence reassembly, duplicate discard, and timeout flushing.
* Concurrency verified: stress-tested with 50 concurrent simulated streams yielding 0.00% packet loss and a 58.44 ms 95th percentile latency.

### Step 3: State Machine & Metric Extraction Engine

* **4-State Lifecycle:** `IDLE_AT_WALL`, `SWIMMING`, `TURN_TRANSITION`, and `OUTSIDE_POOL` with hysteresis boundaries.
* **Push-Off Detection:** Requires an acceleration impulse (>1.5g) away from the wall followed by 2 consecutive seconds of sustained forward velocity (>0.8 m/s).
* **Timestamp Backtracking:** 5-second wall dwell triggers reverse-scanning through the rolling buffer to pinpoint the exact millisecond velocity dropped below 0.20 m/s, ensuring split accuracy within ±100 ms on soft finishes.
* **Biomechanical Metrics:** Distance Per Stroke (DPS), Stroke Cadence (SPM), Breakout Distance, and Effort % ($v_{\text{current}} / v_{\text{PB}}$).
* **Auto Set-Break:** Detects wall dwell > 90 seconds, increments the set order, and resets repetition counters for subsequent push-offs.
* **Tiered Event-Driven Persistence:** High-frequency packets (10–20 Hz) stream strictly through memory/WebSockets, while aggregated `Repetition` and `LapSplit` rows are transactionally committed to SQL upon state completion.

### Step 4: Touch-First Deck Staging & Tag Assignment Interface

* **Wet-Deck Touch Ergonomics:** ≥64px touch target primitives, elimination of tap delays (`touch-action: manipulation`), and touch feedback in `style.css`.
* **3-Tap Pairing Workflow:** Interactive guidance banner guiding coaches through `Tap Tag -> Tap Swimmer -> Select Lane (1-8)` in a single transaction via `/api/tracker/session/<id>/pair/`.
* **1-Tap Swap Tag Modal:** Mid-session hardware reassignment via `/api/tracker/session/<id>/swap-tag/` that rebinds replacement tags while preserving existing repetitions, splits, and workout data.
* **Live Status & Unassigned Pool:** Real-time battery meter bars, 4-bar RSSI link quality indicators (-60 to -95 dBm), online/offline status dots, and segmented tag pool tabs (`Unassigned`, `All Tags`, `Assigned`).
* **Root Redirection:** Automatic routing from `/` to the active practice session staging view.

---

## Getting Started (Local Development)

### 1. Environment Setup (PowerShell / Windows)

```powershell
# Clone the repository
git clone <your-repo-url>
cd TimeTracker

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install django daphne channels channels_redis websockets

```

### 2. Apply Migrations & Run Test Suite

```powershell
python manage.py makemigrations accounts tracker
python manage.py migrate
python manage.py test tracker

```

### 3. Run Development Server & Benchmarks

```powershell
# Terminal 1: Start ASGI Server
python manage.py runserver

# Terminal 2: Run Step 4 Rapid Staging Benchmark
python scripts/verify_step4_staging.py

```

Open `http://127.0.0.1:8000/` in your browser to launch the Deck Staging interface.

---

## Roadmap

* [x] **Step 1:** Core Django Architecture, Data Modeling, Admin Inlines & Role-Based Access Control
* [x] **Step 2:** Real-Time Telemetry Pipeline (ASGI, Redis Channel Layer, Jitter Buffer & 50-Stream Concurrency Verification)
* [x] **Step 3:** State Machine Engine (Push-off detection, timestamp backtracking, metrics, and event persistence)
* [x] **Step 4:** Touch-First Deck Staging & Tag Assignment Interface (3-tap pairing, 1-tap swap modal, live battery/RSSI)
* [ ] **Step 5:** Live Coach Deck Dashboard (Multi-lane grid, outdoor high-contrast mode, wake-lock)
* [ ] **Step 6:** Swimmer Historical Portal & Interactive Performance Analytics
* [ ] **Step 7:** Network Resilience, Snapshot Reconnection & Production AWS Deployment

```