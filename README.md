# Pool Deck Time Tracker (TimeTracker)

A performance tracking and real-time analytics web application designed for competitive swim teams. The platform ingests telemetry from poolside compute units and swimmer wearables to display live workout metrics to coaches on deck and record historical split, stroke, and efficiency data for athletes.

---

## Technical Stack

* **Backend:** Python 3.10+, Django 5+
* **Real-Time Telemetry:** Django Channels (ASGI), Daphne, Redis (with fallback to InMemoryChannelLayer for local development)
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
│   └── urls.py
├── scripts/
│   ├── mock_telemetry_generator.py      # Simulates 1-50 concurrent swimmer data streams
│   └── verify_step2_concurrency.py      # Concurrency stress test (verified zero loss, <60ms p95 latency)
├── tracker/                # Swim analytics domain models, access control, and telemetry logic
│   ├── admin.py            # Tabular inlines, filters, and tag assignment actions
│   ├── consumers.py        # Async WebSocket consumer managing room groups & jitter buffer routing
│   ├── jitter_buffer.py    # Out-of-order reassembly, sequencing, and timeout flushing queue
│   ├── models.py           # PracticeSession, WorkoutSet, Repetition, LapSplit, HardwareTag, etc.
│   ├── permissions.py     # Role verification decorators & metric boundary checks
│   ├── routing.py          # WebSocket URL routing patterns
│   ├── tests.py            # Comprehensive test suite (Models, Access Control, Jitter Buffer, WebSockets)
│   ├── urls.py
│   └── views.py
├── manage.py
└── README.md