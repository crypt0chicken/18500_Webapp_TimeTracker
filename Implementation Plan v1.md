Implementation Plan v1

### Step 1: Core Django Architecture, Data Modeling & Access Control

Establish the project foundation, database schema, and permission boundaries required to manage teams, hardware tags, and practice sessions.

*Sub-steps:*

1. Initialize a Django project configured with PostgreSQL (or SQLite for local development) and implement a custom user model supporting roles: `Admin`, `Coach`, and `Swimmer`.
2. Define the core relational models:
* `Team` and `SwimmerProfile` (including personal bests per stroke and distance, baseline threshold velocities, and team affiliations).
* `HardwareTag` (tracking tag ID/MAC address, battery level, firmware version, and active swimmer assignment).
* `PracticeSession` (supporting pool course standards: `SCY_25Y`, `SCM_25M`, `LCM_50M`; practice mode: `FREE_SWIM` vs. `STRUCTURED`).


* `WorkoutSet`, `Repetition`, and `LapSplit` (storing split times, stroke count, average DPS, stroke rate, breakout distance, and effort percentage).




3. Implement administrative configuration toggles: self-registration enabled/disabled, team-wide metric visibility vs. strict private access, and global pool default courses.
4. Configure Django Admin with custom search filters, tag assignment actions, and tabular inlines for workout sets and splits.

**Validation Test:** Run an automated test suite (`python manage.py test`) verifying that:

* All database migrations apply without errors.
* Users with the `Swimmer` role receive an HTTP 403 Forbidden when attempting to access coach endpoints or another swimmer's restricted data.
* Admin toggles dynamically toggle visibility of teammate records across API endpoints.

---

### Step 2: Real-Time Telemetry Pipeline (ASGI, Redis & Mock Ingestion)

Build the asynchronous ingestion layer capable of receiving high-frequency telemetry from the compute unit and broadcasting updates to connected clients within a 1-second latency window.

*Sub-steps:*

1. Configure an ASGI application entry point using Daphne/Uvicorn and integrate `channels_redis` as the high-throughput channel layer.
2. Define WebSocket routing (`/ws/pool/<session_id>/`) and create an asynchronous consumer (`PoolTelemetryConsumer`) to manage coach dashboard room groups.
3. Build a standalone Python mock generator script that simulates 1 to 50 wearable devices transmitting timestamped telemetry packets (X/Y coordinates, acceleration, roll/pitch/yaw, and sequence IDs) at 10–20 Hz.


4. Implement an in-memory jitter buffer and sequencing queue in the consumer to handle out-of-order packet delivery before processing telemetry.

**Validation Test:** Execute the mock generator script simulating 50 concurrent streams streaming to the backend for 10 minutes. Verify via a headless test client that:

* Zero packet drops occur in the ingestion queue.
* Broadcast latency from ingestion to client receipt remains strictly below 100 ms under a 50-device load.



---

### Step 3: State Machine & Metric Extraction Engine

Implement the server-side logic that transforms raw spatial coordinates and IMU motion data into discrete swimming events, laps, and sets.

*Sub-steps:*

1. Construct the swimmer state machine containing four distinct states: `IDLE_AT_WALL`, `SWIMMING`, `TURN_TRANSITION`, and `OUTSIDE_POOL`.
2. Implement push-off detection requiring an acceleration impulse ($> 1.5\text{g}$) away from the wall followed by at least 2 consecutive seconds of sustained forward velocity ($> 0.8\text{ m/s}$).
3. Implement the timestamp backtracking algorithm: when 5 seconds of idle is confirmed at the wall boundary, backtrack through the rolling coordinate buffer to locate the exact millisecond forward velocity dropped below $0.2\text{ m/s}$ to establish the official split/finish timestamp.
4. Implement automatic set-break detection (wall dwell time $> 90\text{ seconds}$) and calculate derived metrics: Lap Time, Distance Per Stroke (DPS), Stroke Rate, Breakout Distance, and Effort % ($v_{\text{current}} / v_{\text{PB}}$).
5. Implement event-driven persistence: write aggregated `LapSplit` and `Repetition` records to the relational database strictly upon state completion, keeping raw streaming packets in Redis.

**Validation Test:** Feed synthetic telemetry traces into the engine representing:

* A 50m swim ending in a soft-touch glide.
* Two swimmers in the same lane pushing off on a 5-second stagger.
* A swimmer standing on the pool deck for 45 seconds.
Verify unit tests assert that:
* The soft-touch finish timestamp matches the physical wall touch within $\pm 100\text{ ms}$ (rather than the 5-second idle trigger time).


* The staggered swimmers maintain independent, uncorrupted rep timers.
* The swimmer on deck transitions cleanly to `OUTSIDE_POOL` without triggering ghost laps.

---

### Step 4: Tag Management & Deck Staging Interface

Create a touch-first staging interface allowing coaches to rapidly pair hardware tags with roster athletes before practice.

*Sub-steps:*

1. Build the staging template using large touch targets (minimum $48 \times 48\text{ px}$, target $64 \times 64\text{ px}$) optimized for wet hands on a tablet.


2. Integrate Alpine.js to handle a rapid 3-tap pairing workflow: Tap Tag $\rightarrow$ Tap Swimmer $\rightarrow$ Select Lane.
3. Build a 1-tap "Swap Tag" modal that rebinds an active swimmer to a replacement hardware ID mid-session while preserving their historical set data.
4. Add live battery indicators, signal status indicators, and unassigned tag pools to the staging overview.

**Validation Test:** Execute an end-to-end browser automation test (via Playwright or Selenium) that assigns 8 tags to 8 swimmers across 4 lanes. The assignment of all 8 athletes must complete in under 30 seconds, and the backend must confirm active WebSocket subscriptions for all 8 pairs immediately.

---

### Step 5: Live Coach Deck Dashboard

Develop the primary poolside operational screen with glanceable telemetry cards, high-contrast theming, and tablet stability controls.

*Sub-steps:*

1. Construct the live dashboard template using a responsive CSS grid displaying physical pool lanes (Lanes 1 through 8).
2. Implement stacked multi-swimmer cards within each lane: prominent real-time badges for the lane leader with collapsible secondary tiles for staggered trailers.
3. Add the outdoor/sunlight high-contrast toggle using CSS custom properties (`:root[data-theme="outdoor"]`) featuring pure white backgrounds, heavy black borders, and high-visibility typography.
4. Integrate the browser HTML5 Screen Wake Lock API to prevent the tablet display from sleeping during an active session.
5. Implement a software "Deck Lock" slider to prevent water droplets from registering accidental screen touches.
6. Provide manual coach override controls: a prominent "End / Next Set" button and a stroke/distance selector that updates parameters strictly for subsequent push-offs.

**Validation Test:** Load the live dashboard on an emulated tablet device while the mock generator runs 8 lanes with 2 swimmers per lane (16 active athletes). Verify that:

* The UI renders at 60 FPS without frame stutter during continuous metric streaming.
* Clicking the theme toggle switches to the outdoor palette instantly without re-rendering active timers.
* The wake lock successfully requests and retains screen activation.

---

### Step 6: Swimmer Historical Portal & Analytics

Build the post-practice analytical interface where swimmers and coaches review long-term progression, split pacing, and stroke efficiency.

*Sub-steps:*

1. Construct swimmer-facing views displaying chronological session logs, set summaries, and personal best records.


2. Embed Chart.js (controlled via Alpine.js) to render:
* Lap velocity decay curves across multi-rep sets.
* Stroke Rate vs. Distance Per Stroke (DPS) efficiency plots.
* Breakout distance progression over time.


3. Build an interactive workout drill-down modal displaying individual rep splits, turn times ($5\text{m}$ in to $5\text{m}$ out), and calculated Effort %.
4. Enforce backend permission checks ensuring swimmers can view only their own historical records unless the admin has enabled team-wide leaderboard visibility.

**Validation Test:** Seed the database with 5 historical practice sessions containing multiple sets and splits. Log in as an athlete account and verify that:

* All charts render correctly with accurate data points.
* Attempting to navigate directly to another athlete’s historical session URL returns an HTTP 403 Forbidden error.

---

### Step 7: Network Resilience, Reconnection & Production Deployment

Prepare the application for unstable pool-deck Wi-Fi and deploy the production stack to AWS.

*Sub-steps:*

1. Implement client-side WebSocket heartbeat checks and exponential-backoff auto-reconnection in Alpine.js.
2. Build a backend `sync_request` handler that responds to reconnection events with a consolidated JSON snapshot of the active workout state (restoring running timers and active sets).
3. Configure an AWS EC2 instance running Daphne and Redis behind an Nginx reverse proxy with SSL termination.


4. Run an end-to-end stress test simulating 50 concurrent wearable streams pushing telemetry while 3 separate tablet/laptop clients view the live dashboard.



**Validation Test:** While the 50-stream load test is running, sever the tablet client's network connection for 20 seconds, then reconnect. Verify that:

* The client re-establishes the WebSocket connection automatically.
* The dashboard recovers the correct current lap, split, and timer states from the server snapshot within 1 second of reconnection.


* The end-to-end telemetry latency remains under the 1-second threshold.