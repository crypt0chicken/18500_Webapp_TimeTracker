# Pool Deck Time Tracker (TimeTracker)

A performance tracking and real-time analytics web application designed for competitive swim teams. The platform ingests telemetry from poolside compute units and swimmer wearables to display live workout metrics to coaches on deck and record historical split, stroke, and efficiency data for athletes.

---

## Technical Stack (Current & Planned)

* **Backend:** Python 3.10+, Django 5+
* **Real-Time Telemetry (Upcoming):** Django Channels (ASGI), Daphne/Uvicorn, Redis
* **Frontend:** Django Templates + Alpine.js (Hybrid architecture), CSS Custom Properties (Indoor/Outdoor High-Contrast Engine)
* **Database:** SQLite (local development), PostgreSQL (production target)

---

## Project Structure

```text
TimeTracker/
├── accounts/               # Custom user model with role-based permissions (Admin, Coach, Swimmer)
│   ├── admin.py
│   ├── models.py
│   └── tests.py
├── config/                 # Project configuration, ASGI/WSGI handlers, and routing
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── tracker/                # Swim analytics domain models, access control, and telemetry logic
│   ├── admin.py            # Tabular inlines, filters, and tag assignment actions
│   ├── models.py           # PracticeSession, WorkoutSet, Repetition, LapSplit, HardwareTag, etc.
│   ├── permissions.py     # Role verification decorators & metric boundary checks
│   ├── tests.py            # Step 1 validation test suite (access control, models, boundaries)
│   ├── urls.py
│   └── views.py
├── manage.py
└── README.md



Admin account:
    Username: "admin"
    Password" "adminpassword"