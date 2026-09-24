Implementation Plan v1

### Step 1: Core Relational Schema & Role-Based Access Control

Establish the foundational PostgreSQL database schema and user permission structure for team administration, swimmer profiles, and practice tracking.

* **Sub-steps:**
* Initialize the Django project with PostgreSQL as the backend datastore.
* Configure custom user models with three distinct roles: `Admin`, `Coach`, and `Swimmer`.
* Build relational models: `SwimmerProfile` (storing personal bests indexed by stroke, distance, and course format), `PracticeSession` (capturing pool standard: `25y`, `25m`, `50m`, date, and active coaches), `SetGroup` (capturing set parameters, target send-offs, and free-swim flags), `Repetition`, and `LapSplit`.
* Implement row-level access control: configure Django middleware and QuerySet filters so swimmers can strictly query their own historical performances, while admins control team-wide permissions.


* **Testable Verification:**
* Execute an automated test suite (`pytest-django` or Django `TestCase`) that creates dummy coach and swimmer accounts, seeds personal bests for SCY, SCM, and LCM courses, and asserts that a swimmer account attempting to access another swimmer's session endpoints returns an HTTP `403 Forbidden` response. Verify all foreign key cascade and deletion behaviors across `PracticeSession` down to `LapSplit`.



---

### Step 2: High-Contrast Base UI, Theme Engine & Poolside Hardware Integrations

Create the responsive base application layout tailored for tablets, laptops, and smartphones, integrating outdoor visibility and wet-screen mitigations.

* **Sub-steps:**
* Build the primary `base.html` layout utilizing Alpine.js and a CSS custom-properties theming engine.
* Implement an **Indoor / Outdoor Sunlight Mode** toggle that switches CSS variables between a glare-resistant dark theme and an outdoor theme (pure `#FFFFFF` backgrounds, thick black borders, and heavy typography).
* Implement a **Deck Touch Lock** overlay with an intentional unlock mechanism (e.g., a 3-second hold or swipe slider) to block ghost touches caused by pool splashes.
* Integrate the browser's native **Screen Wake Lock API** in JavaScript to keep the tablet screen continuously awake while on the active deck view.


* **Testable Verification:**
* Run Cypress or Playwright browser tests across tablet viewport dimensions ($1024 \times 768$ and $1180 \times 820$). Assert that clicking the outdoor toggle updates the root `data-theme` attribute and verifies computed CSS color contrast ratios exceed WCAG AAA standards ($7:1$). Verify that enabling the "Deck Lock" disables pointer events on all background action buttons until the unlock gesture sequence executes.



---

### Step 3: Deck-Side Swimmer-to-Tracker Pairing Interface

Build an interactive staging interface allowing the coach to map physical wearable tags to swimmers in under 60 seconds before practice starts.

* **Sub-steps:**
* Create a check-in screen displaying two responsive columns: *Active Hardware Tags* (represented by bold numerical badges 1–50) and the *Team Roster*.
* Implement quick-tap pairing via Alpine.js: tapping Tag #3 and then tapping Swimmer "Matthew" assigns the active hardware ID to that swimmer’s profile for the current session.
* Build a **Mid-Practice Hot Swap** modal to reassign a new tag ID to an active swimmer seamlessly without fracturing or terminating their existing practice session records.


* **Testable Verification:**
* Execute an automated UI test simulating a coach assigning 10 tags to 10 swimmers. Assert that session state accurately records all 10 hardware-to-swimmer mappings. Trigger a simulated tag hot-swap mid-session and verify that subsequent mock telemetry sent from the new tag ID routes directly to the original swimmer's record.



---

### Step 4: Real-Time Telemetry Pipeline & Concurrency Test Bench

Set up the asynchronous WebSocket ingestion pipeline capable of receiving and routing real-time telemetry from up to 50 concurrent streams.

* **Sub-steps:**
* Configure ASGI using Daphne and establish a Redis channel layer for high-throughput message routing.
* Build a Django Channels WebSocket consumer (`/ws/pool/<session_id>/`) to ingest JSON telemetry packets (containing `tag_id`, `device_timestamp`, $X$/$Y$ pool coordinates, and accelerometer/gyroscope readings).
* Develop an external Python mock telemetry generator script that broadcasts synthetic burst data for 50 concurrent virtual swimmers at $10\text{ Hz}$.




* **Testable Verification:**
* Run the mock generator with 50 concurrent virtual tags streaming data to the WebSocket endpoint for 10 minutes. Assert zero server crashes, confirm no packet drops inside the Redis channel layer, and verify that the end-to-end transport latency from packet injection to client receipt remains under the 1-second threshold.





---

### Step 5: Swim State Machine & Wall Backtracking Algorithm Engine

Implement the core analytics logic to identify swim states, classify turns, filter out turbulence, and accurately timestamp rep completions.

* **Sub-steps:**
* Build an in-memory state engine tracking three states per swimmer: `IDLE_AT_WALL`, `SWIMMING`, and `OUTSIDE_POOL`.
* Implement push-off validation: transition from `IDLE_AT_WALL` to `SWIMMING` requires an acceleration spike ($>1.5g$) accompanied by sustained forward velocity ($>0.8\text{ m/s}$) for at least 2 seconds.
* Implement the **Timestamp Backtracking Algorithm**: when a swimmer remains in the wall zone ($\le 1.0\text{ m}$) with velocity near zero for $>5\text{ seconds}$, backtrack through the rolling position/velocity buffer to extract the exact millisecond when the swimmer crossed into the wall boundary.
* Incorporate breaststroke pullout tolerance: prevent long glides ($>8\text{ m}$) without arm strokes from prematurely triggering an idle or rest state.
* Detect `OUTSIDE_POOL` based on coordinate boundaries combined with continuous above-water RF transmission ($>30\text{ seconds}$) or vertical walking gait signatures.


* **Testable Verification:**
* Execute a suite of unit tests feeding pre-recorded synthetic time-series coordinate and IMU datasets:
1. A dataset with a 3-second soft glide into the wall followed by 5 seconds of resting: verify the recorded finish time matches the initial wall-entry point rather than the end of the 5-second idle window.
2. A dataset simulating water chop/turbulence while resting at the wall: verify no false push-off is triggered.
3. A dataset with a 12-meter breaststroke underwater pullout: verify the state remains `SWIMMING`.





---

### Step 6: Live Coach Dashboard with Dynamic Lane Grid & Circle-Swimming Support

Develop the primary poolside operational screen displaying live swim metrics across lanes.

* **Sub-steps:**
* Construct an 8-lane grid layout via Django templates and Alpine.js.
* Implement dynamic lane assignment: place swimmers into lane cards based on their measured lateral $Y$-coordinate rather than a static configuration.
* Implement circle-swimming cards: display the lane leader prominently while rendering staggered followers as compact, expandable badges displaying live split, stroke rate, and time per 50yd/m.
* Add color-coded visual thresholds on cards (e.g., green for high effort, red for missed send-offs).
* Provide a persistent, high-contrast **"End / Next Set"** button for manual set overrides.


* **Testable Verification:**
* Run an integration test feeding real-time multi-swimmer mock data into 4 lanes (with 2 swimmers sharing Lane 1). Verify via browser automation that:
1. Incoming WebSocket messages update numeric values (split time, stroke rate) directly in the DOM without full component re-rendering or visual jitter.
2. When a mock swimmer changes their $Y$-coordinate to cross into an adjacent lane, their UI card dynamically transitions to the new lane container.





---

### Step 7: Workout Programming & Dynamic Set Mode Management

Implement both structured workout authoring and dynamic free-swim workout handling.

* **Sub-steps:**
* Build a workout builder interface allowing the coach to pre-program structured sets (e.g., $10 \times 100\text{m}$ Freestyle on a 1:30 interval).
* Implement a **Mode Toggle** on the deck view: "Pre-Programmed Set" vs. "Free-Swim Capture".
* Build the "Effort %" engine: for pre-programmed sets, automatically pull the relevant event PB; for free-swim mode, display time per 50yd/100m by default and provide a single-tap dropdown to assign stroke and target distance mid-set (applying strictly to subsequent push-offs).
* Trigger automatic set demarcation during free-swim mode if all swimmers remain idle at the wall for $>90\text{ seconds}$.


* **Testable Verification:**
* Execute functional tests comparing:
1. A pre-programmed workout where send-off intervals count down and effort percentage displays against the athlete's 100m Freestyle PB.
2. A free-swim session where swimmers complete varied distances, verifying that a 90-second wall dwell automatically segments the completed reps into a distinct `SetGroup` in the database.





---

### Step 8: Swimmer Historical Portal & Analytical Visualization

Build the post-practice web portal for swimmers and coaches to review long-term progression, biomechanical efficiency, and fatigue metrics.

* **Sub-steps:**
* Create the authenticated swimmer landing view with a practice session calendar and performance logs.
* Integrate Chart.js (via Alpine.js components) to plot session fatigue curves (lap velocity vs. stroke rate drift).
* Build analytical displays for transition metrics: breakout distance, breakout velocity, turn time ($5\text{m}$ in to $5\text{m}$ out), and Distance Per Stroke (DPS).
* Provide course-normalized PB tracking (distinguishing between 25y, 25m, and 50m pools).


* **Testable Verification:**
* Seed the database with 5 distinct historical practice sessions for a swimmer. Run end-to-end tests verifying:
1. All aggregated metrics (average DPS, breakout distance, pacing decay rate) calculate and display accurately.
2. Exporting session metrics to CSV generates correctly formatted time-series data.
3. Swimmer accounts cannot access any administrative or coach-only settings from this portal.





---

### Step 9: Edge-Case Integration & End-to-End System Validation

Conduct a full-scale integration audit simulating an entire practice session from start to finish under adverse network and operational conditions.

* **Sub-steps:**
* Run an end-to-end rehearsal: create a team $\rightarrow$ configure pool type $\rightarrow$ complete tag check-in $\rightarrow$ stream simulated 50-swimmer telemetry through free-swim and pre-programmed sets $\rightarrow$ end practice $\rightarrow$ review generated swimmer reports.


* Inject artificial network disconnects: drop the client WebSocket connection for 15 seconds, reconnect, and verify the client requests and receives a consolidated state-sync packet.


* **Testable Verification:**
* Assert that after a 15-second network dropout, the coach's screen resynchronizes with correct lap counts and elapsed times within 500 ms of reconnection without data loss or corruption in the underlying PostgreSQL database. Verify that all 50 swimmer profiles contain complete, non-fragmented rep histories.