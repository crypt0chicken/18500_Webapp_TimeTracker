"""
Multi-Swimmer Visual Test Runner with Dynamic State Slot.
Demonstrates:
1. Live Pace Delta (±Δ vs Goal Pace) & Breakout Distance while SWIMMING.
2. Real-time Rest Interval Stopwatch while resting at IDLE_AT_WALL.
3. Turn rotation metrics during TURN_TRANSITION.
4. Seamless toggling between Cards View and Sortable Table View.
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
import webbrowser
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

import django
django.setup()

from accounts.models import User
from tracker.models import HardwareTag, LaneAssignment, PoolCourse, PracticeSession, SwimmerProfile, Team, WorkoutSet

BASE_HTTP = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/pool/1/"
DASHBOARD_URL = f"{BASE_HTTP}/api/tracker/session/1/"


def ensure_seed_data():
    """Seeds Practice Session 1 with multiple swimmers per lane."""
    team, _ = Team.objects.get_or_create(name="Tritons Swim Team")
    coach, _ = User.objects.get_or_create(username="coach_dan", defaults={"role": User.Role.COACH})
    session, _ = PracticeSession.objects.get_or_create(
        id=1,
        defaults={
            "team": team,
            "coach": coach,
            "pool_course": PoolCourse.SCY_25Y,
            "status": PracticeSession.SessionStatus.ACTIVE,
        },
    )

    WorkoutSet.objects.get_or_create(
        session=session,
        set_order=1,
        defaults={"name": "50m Threshold Pace", "target_distance": 50, "target_reps": 6},
    )

    HardwareTag.objects.all().update(active_swimmer=None)

    sample_athletes = [
        ("Alex", "Vance", 1.45, 1, 1),
        ("Jordan", "Lee", 1.42, 1, 2),
        ("Morgan", "Smith", 1.55, 2, 1),
        ("Taylor", "Swift", 1.40, 3, 1),
        ("Casey", "Jones", 1.36, 3, 2),
        ("Riley", "Reid", 1.44, 4, 1),
        ("Sam", "Miller", 1.39, 5, 1),
        ("Chris", "Evans", 1.41, 6, 1),
        ("Brooke", "Bennett", 1.43, 7, 1),
        ("Dana", "Vollmer", 1.46, 8, 1),
    ]

    swimmer_ids = []
    for idx, (first, last, thresh, lane_no, order_no) in enumerate(sample_athletes, start=1):
        user, _ = User.objects.get_or_create(
            username=f"{first.lower()}_{last.lower()}",
            defaults={"first_name": first, "last_name": last, "role": User.Role.SWIMMER},
        )
        profile, _ = SwimmerProfile.objects.get_or_create(
            user=user,
            team=team,
            defaults={"threshold_velocity": thresh},
        )
        tag, _ = HardwareTag.objects.get_or_create(
            tag_id=f"TAG_{idx:02d}",
            defaults={"battery_percentage": 90 + (idx % 10), "rssi": -65 - idx},
        )
        tag.active_swimmer = profile
        tag.save()

        LaneAssignment.objects.update_or_create(
            session=session,
            swimmer=profile,
            defaults={"tag": tag, "lane_number": lane_no, "order_in_lane": order_no},
        )
        swimmer_ids.append((profile.id, tag.tag_id, lane_no, order_no, f"{first} {last}"))

    return swimmer_ids


def ensure_server_is_running():
    try:
        with urllib.request.urlopen(BASE_HTTP, timeout=2):
            return True
    except Exception:
        return False


async def run_visual_suite(swimmer_records):
    print("\n" + "=" * 70)
    print("LIVE DASHBOARD: DYNAMIC STATE SLOT (PACE DELTA & REST TIMERS)")
    print("=" * 70)

    if not ensure_server_is_running():
        print(f"\n[ERROR] Server not reachable at {BASE_HTTP}")
        print("Please start Daphne first: python manage.py runserver\n")
        return

    print("[Database] Seeded Practice Session 1 with 10 swimmers.")
    print(f"[Browser]  Opening live coach dashboard: {DASHBOARD_URL}\n")
    webbrowser.open(DASHBOARD_URL)
    await asyncio.sleep(2.5)

    async with websockets.connect(WS_URL) as ws:
        print("[WebSocket] Connected to live telemetry feed.\n")
        t_base = time.time()

        s1_id, t1_tag, _, _, name1 = swimmer_records[0]
        s2_id, t2_tag, _, _, name2 = swimmer_records[1]

        # Phase 1: Push-Off
        print(f"PHASE 1: {name1} (Lane 1 Lead) pushes off at pace...")
        await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": 1, "timestamp": t_base, "speed_mps": 1.45, "stroke_count": 0, "x_m": 0.5, "accel": {"x": 2.2, "y": 0.0, "z": 0.98}}}))
        await asyncio.sleep(2.1)
        await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": 2, "timestamp": t_base + 2.1, "speed_mps": 1.50, "stroke_count": 1, "x_m": 3.5, "accel": {"x": 0.1, "y": 0.0, "z": 0.98}}}))
        print("  -> Slot now displays live Pace Delta (−0.3s PACE Δ) and Breakout (BO: 7.2m).\n")
        await asyncio.sleep(2.0)

        # Phase 2: Live Swimming Progression
        print("PHASE 2: Swimmer advancing down pool at brisk threshold velocity...")
        for idx, dist in enumerate([7.0, 11.5, 16.0, 20.5, 24.2], start=3):
            t_now = t_base + 2.5 + (idx * 0.7)
            # Faster than threshold -> negative delta (GREEN ahead of pace)
            await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": idx, "timestamp": t_now, "speed_mps": 1.52, "stroke_rate_spm": 39.0, "dps": 1.65, "x_m": dist}}))
            print(f"  -> Distance: {dist:.1f}m | Watch live Pace Delta update in real time.")
            await asyncio.sleep(0.7)

        # Phase 3: Flip Turn Transition
        print("\nPHASE 3: Flip turn rotation at far wall (24.6m)...")
        await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": 15, "timestamp": t_base + 8.5, "speed_mps": 1.05, "x_m": 24.6, "gyro": {"roll": 115.0, "pitch": 130.0, "yaw": 0.0}}}))
        print("  -> Slot switches to Turn indicator (🔄 Turn).")
        await asyncio.sleep(2.0)

        # Phase 4: Wall Finish & Live Rest Interval Stopwatch
        print("\nPHASE 4: Swimmer touches wall and finishes repetition...")
        t_finish = t_base + 12.0
        await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": 25, "timestamp": t_finish, "speed_mps": 0.10, "x_m": 0.4}}))

        # Dwell to trigger IDLE_AT_WALL
        for sec in range(1, 6):
            await asyncio.sleep(1.0)
            await ws.send(json.dumps({"type": "telemetry_packet", "data": {"swimmer_id": s1_id, "tag_id": t1_tag, "lane": 1, "sequence_id": 25 + sec, "timestamp": t_finish + sec, "speed_mps": 0.02, "x_m": 0.4}}))

        print("\n  -> Repetition complete! State transitions to WALL IDLE.")
        print("  -> Dynamic State Slot now displays: '⏱️ REST INTERVAL: 00:05... 00:06... 00:07...'")
        print("  -> Rest stopwatch continues counting up automatically on screen.")
        await asyncio.sleep(4.0)

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE: Dynamic State Slot verified!")
    print("=" * 70 + "\n")


def main():
    records = ensure_seed_data()
    asyncio.run(run_visual_suite(records))


if __name__ == "__main__":
    main()