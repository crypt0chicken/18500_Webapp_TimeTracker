import time
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
import asyncio

from config.asgi import application
from tracker.jitter_buffer import StreamJitterBuffer, reset_session_jitter_buffer
from tracker.models import (
    HardwareTag,
    LapSplit,
    PersonalBest,
    PoolCourse,
    PracticeSession,
    Repetition,
    StrokeType,
    SwimmerProfile,
    SystemConfiguration,
    Team,
    WorkoutSet,
)

User = get_user_model()


# =====================================================================
# STEP 1 TESTS: Models, Access Control & System Configuration
# =====================================================================

class TrackerModelHierarchyTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Tritons Swim Club")
        self.coach_user = User.objects.create_user(
            username="coach_sarah",
            password="testpassword",
            role=User.Role.COACH,
        )
        self.swimmer_user = User.objects.create_user(
            username="swimmer_john",
            password="testpassword",
            role=User.Role.SWIMMER,
        )
        self.swimmer_profile = SwimmerProfile.objects.create(
            user=self.swimmer_user,
            team=self.team,
            threshold_velocity=1.45,
        )

    def test_personal_best_uniqueness(self):
        PersonalBest.objects.create(
            swimmer=self.swimmer_profile,
            stroke=StrokeType.FREESTYLE,
            distance_units=PoolCourse.SCY_25Y,
            distance=50,
            time_seconds=22.85,
        )
        with self.assertRaises(Exception):
            PersonalBest.objects.create(
                swimmer=self.swimmer_profile,
                stroke=StrokeType.FREESTYLE,
                distance_units=PoolCourse.SCY_25Y,
                distance=50,
                time_seconds=23.10,
            )

    def test_hardware_tag_assignment_and_reassignment(self):
        tag = HardwareTag.objects.create(
            tag_id="TAG_A1",
            battery_percentage=92,
            active_swimmer=self.swimmer_profile,
        )
        self.assertEqual(self.swimmer_profile.active_tag, tag)

        tag.active_swimmer = None
        tag.save()
        self.assertIsNone(tag.active_swimmer)

    def test_practice_hierarchy_and_split_aggregation(self):
        session = PracticeSession.objects.create(
            team=self.team,
            coach=self.coach_user,
            pool_course=PoolCourse.SCY_25Y,
            mode=PracticeSession.PracticeMode.STRUCTURED,
            status=PracticeSession.SessionStatus.ACTIVE,
        )
        wset = WorkoutSet.objects.create(
            session=session,
            set_order=1,
            name="10x50 Free Fast",
            stroke=StrokeType.FREESTYLE,
            target_distance=50,
            target_interval_sec=45,
            target_reps=10,
        )
        rep = Repetition.objects.create(
            workout_set=wset,
            swimmer=self.swimmer_profile,
            rep_number=1,
            total_time_seconds=24.50,
            rest_time_seconds=20.50,
            effort_percentage=93.2,
        )
        LapSplit.objects.create(
            repetition=rep,
            lap_number=1,
            split_time_seconds=11.80,
            stroke_count=14,
            stroke_rate=38.5,
            dps=1.63,
            breakout_distance_m=6.8,
        )
        LapSplit.objects.create(
            repetition=rep,
            lap_number=2,
            split_time_seconds=12.70,
            stroke_count=16,
            stroke_rate=40.0,
            dps=1.43,
            breakout_distance_m=5.4,
        )

        self.assertEqual(rep.splits.count(), 2)
        total_lap_split = sum(s.split_time_seconds for s in rep.splits.all())
        self.assertAlmostEqual(total_lap_split, 24.50, places=2)


class StepOneValidationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.team = Team.objects.create(name="Predators Swim Club")

        self.coach_user = User.objects.create_user(
            username="coach_mike",
            password="securepassword123",
            role=User.Role.COACH,
        )
        self.swimmer_user_1 = User.objects.create_user(
            username="swimmer_alice",
            password="securepassword123",
            role=User.Role.SWIMMER,
        )
        self.profile_1 = SwimmerProfile.objects.create(
            user=self.swimmer_user_1,
            team=self.team,
        )
        self.swimmer_user_2 = User.objects.create_user(
            username="swimmer_bob",
            password="securepassword123",
            role=User.Role.SWIMMER,
        )
        self.profile_2 = SwimmerProfile.objects.create(
            user=self.swimmer_user_2,
            team=self.team,
        )

        self.session = PracticeSession.objects.create(
            team=self.team,
            coach=self.coach_user,
            pool_course=PoolCourse.SCY_25Y,
        )

        self.config = SystemConfiguration.get_solo()
        self.config.team_leaderboard_visible = False
        self.config.save()

    def test_swimmer_blocked_from_coach_endpoint(self):
        self.client.login(username="swimmer_alice", password="securepassword123")
        url = reverse('tracker:coach_session', kwargs={'session_id': self.session.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_coach_permitted_on_coach_endpoint(self):
        self.client.login(username="coach_mike", password="securepassword123")
        url = reverse('tracker:coach_session', kwargs={'session_id': self.session.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_swimmer_can_view_own_metrics(self):
        self.client.login(username="swimmer_alice", password="securepassword123")
        url = reverse('tracker:swimmer_metrics', kwargs={'swimmer_id': self.profile_1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_teammate_visibility_toggle_behavior(self):
        self.client.login(username="swimmer_alice", password="securepassword123")
        target_url = reverse('tracker:swimmer_metrics', kwargs={'swimmer_id': self.profile_2.id})

        response = self.client.get(target_url)
        self.assertEqual(response.status_code, 403)

        self.config.team_leaderboard_visible = True
        self.config.save()

        response = self.client.get(target_url)
        self.assertEqual(response.status_code, 200)


# =====================================================================
# STEP 2 TESTS: Jitter Buffer & Real-Time WebSocket Telemetry
# =====================================================================

class JitterBufferUnitTests(TestCase):
    def test_in_order_packets_zero_latency(self):
        buf = StreamJitterBuffer(stream_id="1", max_delay=0.15)
        p1 = {"swimmer_id": 1, "sequence_id": 1, "val": "a"}
        p2 = {"swimmer_id": 1, "sequence_id": 2, "val": "b"}

        self.assertEqual(buf.push(p1), [p1])
        self.assertEqual(buf.push(p2), [p2])

    def test_out_of_order_packets_reordering(self):
        buf = StreamJitterBuffer(stream_id="1", max_delay=0.15)
        p1 = {"swimmer_id": 1, "sequence_id": 1, "val": "a"}
        p2 = {"swimmer_id": 1, "sequence_id": 2, "val": "b"}
        p3 = {"swimmer_id": 1, "sequence_id": 3, "val": "c"}

        self.assertEqual(buf.push(p1), [p1])
        self.assertEqual(buf.push(p3), [])
        self.assertEqual(buf.push(p2), [p2, p3])

    def test_duplicate_packets_discarded(self):
        buf = StreamJitterBuffer(stream_id="1", max_delay=0.15)
        p1 = {"swimmer_id": 1, "sequence_id": 1, "val": "a"}
        p2 = {"swimmer_id": 1, "sequence_id": 2, "val": "b"}

        self.assertEqual(buf.push(p1), [p1])
        self.assertEqual(buf.push(p2), [p2])
        self.assertEqual(buf.push(p2), [])

    def test_timeout_flush_on_packet_loss(self):
        buf = StreamJitterBuffer(stream_id="1", max_delay=0.10)
        p1 = {"swimmer_id": 1, "sequence_id": 1, "val": "a"}
        p3 = {"swimmer_id": 1, "sequence_id": 3, "val": "c"}

        self.assertEqual(buf.push(p1), [p1])
        self.assertEqual(buf.push(p3), [])

        time.sleep(0.12)
        flushed = buf.flush_expired()
        self.assertEqual(flushed, [p3])


class PoolTelemetryConsumerTests(TransactionTestCase):
    async def test_websocket_connection_and_broadcast(self):
        session_id = "test_session_101"
        communicator_coach = WebsocketCommunicator(application, f"/ws/pool/{session_id}/")
        communicator_ingestion = WebsocketCommunicator(application, f"/ws/pool/{session_id}/")

        connected_coach, _ = await communicator_coach.connect()
        connected_ingestion, _ = await communicator_ingestion.connect()

        self.assertTrue(connected_coach)
        self.assertTrue(connected_ingestion)

        sample_packet = {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": 1,
                "lane": 3,
                "speed": 1.52,
                "stroke_rate": 38.0,
                "effort_pct": 94.2,
            }
        }
        await communicator_ingestion.send_json_to(sample_packet)

        response = await communicator_coach.receive_json_from(timeout=2.0)
        self.assertEqual(response["type"], "telemetry_packet")
        self.assertEqual(response["data"]["swimmer_id"], 1)
        self.assertEqual(response["data"]["lane"], 3)
        self.assertAlmostEqual(response["data"]["speed"], 1.52, places=2)

        await communicator_coach.disconnect()
        await communicator_ingestion.disconnect()

    async def test_websocket_reorders_out_of_order_stream(self):
        session_id = "test_reorder_session"
        reset_session_jitter_buffer(session_id)

        communicator_ingest = WebsocketCommunicator(application, f"/ws/pool/{session_id}/")
        communicator_coach = WebsocketCommunicator(application, f"/ws/pool/{session_id}/")

        await communicator_ingest.connect()
        await communicator_coach.connect()

        p1 = {"type": "telemetry_packet", "data": {"swimmer_id": 1, "sequence_id": 1, "speed": 1.4}}
        p3 = {"type": "telemetry_packet", "data": {"swimmer_id": 1, "sequence_id": 3, "speed": 1.6}}
        p2 = {"type": "telemetry_packet", "data": {"swimmer_id": 1, "sequence_id": 2, "speed": 1.5}}

        await communicator_ingest.send_json_to(p1)
        r1 = await communicator_coach.receive_json_from(timeout=1.0)
        self.assertEqual(r1["data"]["sequence_id"], 1)

        await communicator_ingest.send_json_to(p3)
        await communicator_ingest.send_json_to(p2)

        r2 = await communicator_coach.receive_json_from(timeout=1.0)
        self.assertEqual(r2["data"]["sequence_id"], 2)

        r3 = await communicator_coach.receive_json_from(timeout=1.0)
        self.assertEqual(r3["data"]["sequence_id"], 3)

        await communicator_ingest.disconnect()
        await communicator_coach.disconnect()


from tracker.state_machine import (
    SwimmerState,
    SwimmerStateMachine,
    SessionStateMachineManager,
)


class SwimmerStateMachineStep31Tests(TestCase):
    def setUp(self):
        self.sm = SwimmerStateMachine(swimmer_id="test_swimmer_1", pool_length=25.0)

    def test_initial_state_defaults_to_idle_at_wall(self):
        self.assertEqual(self.sm.current_state, SwimmerState.IDLE_AT_WALL)
        self.assertEqual(len(self.sm.history), 0)

    def test_rolling_buffer_evicts_points_older_than_window(self):
        # Insert point at t=0.0
        self.sm.update({
            "timestamp": 0.0,
            "sequence_id": 1,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.0,
        })
        # Insert point at t=5.0
        self.sm.update({
            "timestamp": 5.0,
            "sequence_id": 2,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.0,
        })
        self.assertEqual(len(self.sm.history), 2)

        # Insert point at t=11.5 (older than 10s window from t=0.0)
        self.sm.update({
            "timestamp": 11.5,
            "sequence_id": 3,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.0,
        })
        # Point at t=0.0 should be evicted; history holds t=5.0 and t=11.5
        self.assertEqual(len(self.sm.history), 2)
        self.assertEqual(self.sm.history[0].timestamp, 5.0)
        self.assertEqual(self.sm.history[1].timestamp, 11.5)

    def test_transition_from_idle_to_swimming(self):
        # Swimmer pushes off and exits wall zone with forward speed
        event = self.sm.update({
            "timestamp": 1.0,
            "sequence_id": 1,
            "x_m": 2.5,  # Exits 1.8m hysteresis threshold
            "y_m": 2.5,
            "speed_mps": 1.4,
        })
        self.assertIsNotNone(event)
        self.assertEqual(event.previous_state, SwimmerState.IDLE_AT_WALL)
        self.assertEqual(event.new_state, SwimmerState.SWIMMING)
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)

    def test_transition_from_swimming_to_turn_transition(self):
        # Put into SWIMMING first
        self.sm.current_state = SwimmerState.SWIMMING
        self.sm.state_entered_time = 1.0

        # Swimmer approaches far wall (x >= 24.0m) and executes a flip turn somersault
        event = self.sm.update({
            "timestamp": 15.0,
            "sequence_id": 50,
            "x_m": 24.3,
            "y_m": 2.5,
            "speed_mps": 1.1,
            "gyro": {"roll": 110.0, "pitch": 130.0, "yaw": 0.0},
        })
        self.assertIsNotNone(event)
        self.assertEqual(event.previous_state, SwimmerState.SWIMMING)
        self.assertEqual(event.new_state, SwimmerState.TURN_TRANSITION)
        self.assertEqual(self.sm.current_state, SwimmerState.TURN_TRANSITION)

    def test_transition_to_outside_pool_and_return(self):
        # Swimmer exits pool onto deck (x = -2.5m)
        event_exit = self.sm.update({
            "timestamp": 10.0,
            "sequence_id": 20,
            "x_m": -2.5,
            "y_m": 2.5,
            "speed_mps": 0.8,
        })
        self.assertIsNotNone(event_exit)
        self.assertEqual(event_exit.new_state, SwimmerState.OUTSIDE_POOL)
        self.assertEqual(self.sm.current_state, SwimmerState.OUTSIDE_POOL)

        # Swimmer returns to pool edge (x = 0.5m)
        event_return = self.sm.update({
            "timestamp": 45.0,
            "sequence_id": 65,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.1,
        })
        self.assertIsNotNone(event_return)
        self.assertEqual(event_return.previous_state, SwimmerState.OUTSIDE_POOL)
        self.assertEqual(event_return.new_state, SwimmerState.IDLE_AT_WALL)
        self.assertEqual(self.sm.current_state, SwimmerState.IDLE_AT_WALL)

    def test_session_manager_tracks_independent_swimmers(self):
        manager = SessionStateMachineManager(session_id="pool_sess_1", pool_length=25.0)

        # Packet for Swimmer 1 (stays at wall)
        evt1 = manager.process_packet({
            "swimmer_id": "1",
            "timestamp": 1.0,
            "x_m": 0.5,
            "y_m": 1.25,
            "speed_mps": 0.0,
        })
        # Packet for Swimmer 2 (swimming mid-pool)
        evt2 = manager.process_packet({
            "swimmer_id": "2",
            "timestamp": 1.0,
            "x_m": 12.0,
            "y_m": 3.75,
            "speed_mps": 1.45,
        })

        sm1 = manager.get_or_create("1")
        sm2 = manager.get_or_create("2")

        self.assertEqual(sm1.current_state, SwimmerState.IDLE_AT_WALL)
        self.assertEqual(sm2.current_state, SwimmerState.SWIMMING)
        self.assertIsNone(evt1)
        self.assertIsNotNone(evt2)


class TimestampBacktrackingStep33Tests(TestCase):
    def setUp(self):
        self.sm = SwimmerStateMachine(
            swimmer_id="test_swimmer_backtrack",
            pool_length=25.0,
            initial_state=SwimmerState.SWIMMING,
        )
        self.sm.state_entered_time = 0.0

    def test_soft_touch_glide_finish_backtracking(self):
        # 1. Swimmer is swimming mid-pool at t=20.0
        self.sm.update({
            "timestamp": 20.0,
            "x_m": 20.0,
            "y_m": 2.5,
            "speed_mps": 1.45,
            "accel": {"x": 0.2, "y": 0.0, "z": 0.98},
        })

        # 2. Enters wall zone (x=24.2 >= 24.0) gliding at t=21.5 (speed=0.45 m/s)
        self.sm.update({
            "timestamp": 21.5,
            "x_m": 24.2,
            "y_m": 2.5,
            "speed_mps": 0.45,
            "accel": {"x": 0.0, "y": 0.0, "z": 0.98},
        })

        # 3. Soft touch: speed drops to 0.16 m/s at x=24.8 at t=22.4 (exact touch point)
        self.sm.update({
            "timestamp": 22.4,
            "x_m": 24.8,
            "y_m": 2.5,
            "speed_mps": 0.16,
            "accel": {"x": 0.0, "y": 0.0, "z": 0.98},
        })
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)
        self.assertEqual(self.sm.wall_idle_start_time, 22.4)

        # 4. Swimmer rests at wall: t=23.4 (1.0s dwell) -> still SWIMMING
        evt_1s = self.sm.update({
            "timestamp": 23.4,
            "x_m": 24.8,
            "y_m": 2.5,
            "speed_mps": 0.08,
            "accel": {"x": 0.0, "y": 0.0, "z": 0.98},
        })
        self.assertIsNone(evt_1s)
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)

        # 5. Exactly 5.0 seconds of idle confirmed at t=27.4 (22.4 + 5.0 = 27.4)
        evt_5s = self.sm.update({
            "timestamp": 27.4,
            "x_m": 24.8,
            "y_m": 2.5,
            "speed_mps": 0.02,
            "accel": {"x": 0.0, "y": 0.0, "z": 0.98},
        })
        self.assertIsNotNone(evt_5s)
        self.assertEqual(evt_5s.previous_state, SwimmerState.SWIMMING)
        self.assertEqual(evt_5s.new_state, SwimmerState.IDLE_AT_WALL)
        self.assertEqual(self.sm.current_state, SwimmerState.IDLE_AT_WALL)

        # Verification: finish_timestamp must backtrack to t=22.4 within 100ms tolerance
        self.assertAlmostEqual(evt_5s.details["finish_timestamp"], 22.4, places=2)
        # backtrack_delta_sec must equal the 5.0s dwell confirmation window
        self.assertAlmostEqual(evt_5s.details["backtrack_delta_sec"], 5.0, places=2)

    def test_idle_interrupted_before_5s_resets_counter(self):
        # Swimmer slows down at wall at t=10.0
        self.sm.update({
            "timestamp": 10.0,
            "x_m": 24.6,
            "y_m": 2.5,
            "speed_mps": 0.15,
            "accel": {"x": 0.0, "y": 0.0, "z": 0.98},
        })
        self.assertEqual(self.sm.wall_idle_start_time, 10.0)

        # Swimmer pushes off again after only 3 seconds (t=13.0, speed accelerates to 1.1 m/s)
        self.sm.update({
            "timestamp": 13.0,
            "x_m": 23.0,
            "y_m": 2.5,
            "speed_mps": 1.1,
            "accel": {"x": -1.2, "y": 0.0, "z": 0.98},
        })
        # Idle counter should reset, swimmer remains in SWIMMING
        self.assertIsNone(self.sm.wall_idle_start_time)
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)

    def test_backtracking_at_near_wall(self):
        # Swimmer finishes lap at near wall (x <= 1.0m)
        self.sm.update({
            "timestamp": 30.0,
            "x_m": 0.8,
            "y_m": 2.5,
            "speed_mps": 0.5,
        })
        # Touches wall at t=31.2 with speed dropping to 0.12 m/s
        self.sm.update({
            "timestamp": 31.2,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.12,
        })
        # 5 seconds later at t=36.2
        evt = self.sm.update({
            "timestamp": 36.2,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.01,
        })
        self.assertIsNotNone(evt)
        self.assertEqual(evt.new_state, SwimmerState.IDLE_AT_WALL)
        self.assertAlmostEqual(evt.details["finish_timestamp"], 31.2, places=2)



from tracker.state_machine import (
    calculate_dps,
    calculate_effort_percentage,
    LapMetrics,
    RepetitionMetrics,
)


class MetricCalculationAndSetBreakStep34Tests(TestCase):
    def setUp(self):
        self.sm = SwimmerStateMachine(
            swimmer_id="test_swimmer_metrics",
            pool_length=25.0,
            pb_time_seconds=24.0,  # 24.0s PB for 50m
            threshold_velocity_mps=1.35,
            set_break_dwell_threshold_sec=90.0,
            initial_state=SwimmerState.IDLE_AT_WALL,
        )

    def test_dps_formula_calculation(self):
        # 25m pool, 5m breakout -> clean distance = 20m. 10 strokes -> DPS = 2.0m
        self.assertEqual(calculate_dps(clean_distance_m=20.0, stroke_count=10), 2.0)
        # 0 strokes should safely return 0.0 without ZeroDivisionError
        self.assertEqual(calculate_dps(clean_distance_m=20.0, stroke_count=0), 0.0)

    def test_effort_percentage_formula(self):
        # With PB: 50m completed in 25.0s, PB = 24.0s -> (24/25)*100 = 96.0%
        effort_with_pb = calculate_effort_percentage(
            total_time_seconds=25.0,
            distance_m=50.0,
            pb_time_seconds=24.0,
        )
        self.assertEqual(effort_with_pb, 96.0)

        # Faster than PB: 50m in 23.5s -> (24/23.5)*100 = 102.13%
        effort_beat_pb = calculate_effort_percentage(
            total_time_seconds=23.5,
            distance_m=50.0,
            pb_time_seconds=24.0,
        )
        self.assertEqual(effort_beat_pb, 102.13)

        # Without PB (uses threshold velocity = 1.35 m/s): 50m in 34.0s (v = 1.4705 m/s)
        # Effort = (1.4705 / 1.35) * 100 = 108.93%
        effort_no_pb = calculate_effort_percentage(
            total_time_seconds=34.0,
            distance_m=50.0,
            pb_time_seconds=None,
            threshold_velocity_mps=1.35,
        )
        self.assertEqual(effort_no_pb, 108.93)

    def test_auto_set_break_detection_after_90s_dwell(self):
        # 1. Swimmer completes a rep at t=30.0
        self.sm.last_rep_finish_time = 30.0
        self.sm.current_state = SwimmerState.IDLE_AT_WALL
        self.sm.state_entered_time = 30.0
        self.sm.current_set_number = 1

        # 2. Dwell at wall for 85s (t=115.0) -> No set break event emitted yet
        evt_85s = self.sm.update({
            "timestamp": 115.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.0,
        })
        self.assertIsNone(evt_85s)
        self.assertFalse(self.sm.set_break_emitted)

        # 3. Dwell reaches 91s (t=121.0 > 90.0s threshold) -> SET_BREAK event emitted
        evt_91s = self.sm.update({
            "timestamp": 121.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.0,
        })
        self.assertIsNotNone(evt_91s)
        self.assertEqual(evt_91s.details.get("event_type"), "SET_BREAK")
        self.assertEqual(evt_91s.details.get("completed_set_number"), 1)
        self.assertEqual(evt_91s.details.get("next_set_number"), 2)
        self.assertTrue(self.sm.set_break_emitted)

        # 4. Swimmer pushes off after the break: initial impulse at t=130.0
        self.sm.update({
            "timestamp": 130.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 1.2,
            "accel": {"x": 2.2, "y": 0.0, "z": 0.98},
        })
        # Sustained speed confirmation at t=132.1s
        push_evt = self.sm.update({
            "timestamp": 132.1,
            "x_m": 2.8,
            "y_m": 2.5,
            "speed_mps": 1.45,
            "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
        })
        self.assertIsNotNone(push_evt)
        self.assertEqual(push_evt.new_state, SwimmerState.SWIMMING)
        # Set number must have incremented to 2, rep number reset to 1
        self.assertEqual(self.sm.current_set_number, 2)
        self.assertEqual(self.sm.current_rep_number, 1)

    def test_full_repetition_metrics_extraction(self):
        # 1. Swimmer pushes off at t=10.0 (near wall x=0.5m)
        self.sm.update({
            "timestamp": 10.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 1.2,
            "stroke_count": 0,
            "accel": {"x": 2.2, "y": 0.0, "z": 0.98},
        })
        self.sm.update({
            "timestamp": 12.1,
            "x_m": 2.8,
            "y_m": 2.5,
            "speed_mps": 1.45,
            "stroke_count": 0,
            "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
        })
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)

        # 2. Breakout at x=6.5m at t=14.0
        self.sm.update({
            "timestamp": 14.0,
            "x_m": 6.5,
            "y_m": 2.5,
            "speed_mps": 1.4,
            "stroke_count": 1,
            "stroke_rate_spm": 38.0,
            "phase": "SURFACE_SWIM",
        })
        self.assertEqual(self.sm.lap_breakout_distance, 6.5)

        # 3. Lap 1 Turn at far wall (x=24.5m) at t=23.5 (13.5s lap split, 12 strokes)
        turn_evt = self.sm.update({
            "timestamp": 23.5,
            "x_m": 24.5,
            "y_m": 2.5,
            "speed_mps": 1.1,
            "stroke_count": 12,
            "stroke_rate_spm": 39.0,
            "gyro": {"roll": 100.0, "pitch": 120.0, "yaw": 0.0},
        })
        self.assertIsNotNone(turn_evt)
        self.assertEqual(turn_evt.new_state, SwimmerState.TURN_TRANSITION)
        lap_1 = turn_evt.details.get("completed_lap")
        self.assertIsNotNone(lap_1)
        self.assertEqual(lap_1["lap_number"], 1)
        self.assertEqual(lap_1["split_time_seconds"], 13.5)
        self.assertEqual(lap_1["breakout_distance_m"], 6.5)
        self.assertEqual(lap_1["stroke_count"], 12)
        # clean_dist = 25 - 6.5 = 18.5m; dps = 18.5 / 12 = 1.54m
        self.assertEqual(lap_1["dps"], 1.54)

        # 4. Turn push-off resumes swimming down pool toward near wall
        self.sm.update({
            "timestamp": 25.0,
            "x_m": 22.5,
            "y_m": 2.5,
            "speed_mps": 1.4,
            "stroke_count": 12,
        })
        self.assertEqual(self.sm.current_state, SwimmerState.SWIMMING)

        # 5. Soft-touch finish at near wall (x=0.4m) at t=37.5 (speed drops to 0.15 m/s)
        self.sm.update({
            "timestamp": 37.5,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.15,
            "stroke_count": 24,
            "stroke_rate_spm": 37.0,
        })
        # 5 seconds of idle confirmed at t=42.5
        finish_evt = self.sm.update({
            "timestamp": 42.5,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.02,
            "stroke_count": 24,
            "stroke_rate_spm": 0.0,
        })
        self.assertIsNotNone(finish_evt)
        self.assertEqual(finish_evt.new_state, SwimmerState.IDLE_AT_WALL)

        rep_metrics = finish_evt.details.get("repetition_metrics")
        self.assertIsNotNone(rep_metrics)
        self.assertEqual(rep_metrics["rep_number"], 1)
        self.assertEqual(len(rep_metrics["splits"]), 2)
        # Backtracked total time: 37.5 - 10.0 = 27.5s for 50m
        self.assertEqual(rep_metrics["total_time_seconds"], 27.5)
        # Effort %: PB is 24.0s -> (24.0 / 27.5) * 100 = 87.27%
        self.assertEqual(rep_metrics["effort_percentage"], 87.27)


from tracker.persistence import save_repetition_metrics_sync, persist_completed_repetition
from tracker.state_machine import reset_session_state_machine


class EventDrivenPersistenceStep35Tests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Stingrays Swim Team")
        self.coach = User.objects.create_user(
            username="coach_dan",
            password="securepassword123",
            role=User.Role.COACH,
        )
        self.swimmer_user = User.objects.create_user(
            username="swimmer_clara",
            password="securepassword123",
            role=User.Role.SWIMMER,
        )
        self.profile = SwimmerProfile.objects.create(
            user=self.swimmer_user,
            team=self.team,
            threshold_velocity=1.40,
        )
        self.session = PracticeSession.objects.create(
            team=self.team,
            coach=self.coach,
            pool_course=PoolCourse.SCY_25Y,
            status=PracticeSession.SessionStatus.ACTIVE,
        )

    def test_direct_repetition_and_splits_persistence(self):
        rep_data = {
            "set_number": 1,
            "rep_number": 1,
            "total_time_seconds": 25.40,
            "rest_time_seconds": 15.00,
            "effort_percentage": 94.50,
            "splits": [
                {
                    "lap_number": 1,
                    "split_time_seconds": 12.20,
                    "stroke_count": 14,
                    "stroke_rate": 38.0,
                    "dps": 1.60,
                    "breakout_distance_m": 6.2,
                },
                {
                    "lap_number": 2,
                    "split_time_seconds": 13.20,
                    "stroke_count": 16,
                    "stroke_rate": 39.5,
                    "dps": 1.45,
                    "breakout_distance_m": 5.0,
                },
            ],
        }

        repetition = save_repetition_metrics_sync(
            session_id=self.session.id,
            swimmer_identifier=self.profile.id,
            rep_metrics=rep_data,
        )

        self.assertIsNotNone(repetition)
        self.assertEqual(Repetition.objects.count(), 1)
        self.assertEqual(LapSplit.objects.count(), 2)

        # Verify parent workout set was created automatically
        wset = repetition.workout_set
        self.assertEqual(wset.set_order, 1)
        self.assertEqual(wset.session, self.session)

        # Verify repetition attributes
        self.assertEqual(repetition.swimmer, self.profile)
        self.assertEqual(repetition.rep_number, 1)
        self.assertEqual(repetition.total_time_seconds, 25.40)
        self.assertEqual(repetition.effort_percentage, 94.50)

        # Verify lap splits
        splits = list(repetition.splits.all())
        self.assertEqual(len(splits), 2)
        self.assertEqual(splits[0].lap_number, 1)
        self.assertEqual(splits[0].split_time_seconds, 12.20)
        self.assertEqual(splits[0].dps, 1.60)
        self.assertEqual(splits[1].lap_number, 2)
        self.assertEqual(splits[1].split_time_seconds, 13.20)


class WebSocketEventDrivenPersistenceIntegrationTests(TransactionTestCase):
    async def test_full_lap_sequence_triggers_sql_persistence_via_websocket(self):
        team = await Team.objects.acreate(name="Barracudas")
        coach = await User.objects.acreate_user(
            username="coach_tom",
            password="testpassword",
            role=User.Role.COACH,
        )
        swimmer = await User.objects.acreate_user(
            username="swimmer_zoe",
            password="testpassword",
            role=User.Role.SWIMMER,
        )
        profile = await SwimmerProfile.objects.acreate(
            user=swimmer,
            team=team,
            threshold_velocity=1.35,
        )
        session = await PracticeSession.objects.acreate(
            team=team,
            coach=coach,
            pool_course=PoolCourse.SCY_25Y,
            status=PracticeSession.SessionStatus.ACTIVE,
        )

        session_id = str(session.id)
        reset_session_jitter_buffer(session_id)
        reset_session_state_machine(session_id)

        communicator = WebsocketCommunicator(application, f"/ws/pool/{session_id}/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # 1. Swimmer pushes off from near wall (impulse at t=10.0, confirmed at t=12.1)
        p1 = {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": profile.id,
                "sequence_id": 1,
                "timestamp": 10.0,
                "x_m": 0.5,
                "y_m": 2.5,
                "speed_mps": 1.2,
                "stroke_count": 0,
                "accel": {"x": 2.2, "y": 0.0, "z": 0.98},
            },
        }
        p2 = {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": profile.id,
                "sequence_id": 2,
                "timestamp": 12.1,
                "x_m": 3.0,
                "y_m": 2.5,
                "speed_mps": 1.45,
                "stroke_count": 0,
                "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
            },
        }
        await communicator.send_json_to(p1)
        await communicator.send_json_to(p2)

        # 2. Reaches far wall, touches with soft finish at t=24.0 (speed drops to 0.12 m/s)
        p3 = {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": profile.id,
                "sequence_id": 3,
                "timestamp": 24.0,
                "x_m": 24.6,
                "y_m": 2.5,
                "speed_mps": 0.12,
                "stroke_count": 14,
                "stroke_rate_spm": 38.0,
            },
        }
        await communicator.send_json_to(p3)

        # 3. 5s idle dwell expires at t=29.0, completing the 1-lap rep
        p4 = {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": profile.id,
                "sequence_id": 4,
                "timestamp": 29.0,
                "x_m": 24.6,
                "y_m": 2.5,
                "speed_mps": 0.02,
                "stroke_count": 14,
                "stroke_rate_spm": 0.0,
            },
        }
        await communicator.send_json_to(p4)

        # Allow async DB persistence to complete
        await asyncio.sleep(0.5)

        # Verify records persisted in relational database
        rep_count = await Repetition.objects.filter(swimmer=profile).acount()
        self.assertEqual(rep_count, 1)

        saved_rep = await Repetition.objects.filter(swimmer=profile).afirst()
        self.assertEqual(saved_rep.rep_number, 1)
        # Backtracked time: 24.0 - 10.0 = 14.0s
        self.assertEqual(saved_rep.total_time_seconds, 14.0)

        split_count = await LapSplit.objects.filter(repetition=saved_rep).acount()
        self.assertEqual(split_count, 1)

        await communicator.disconnect()



class StepThreeSpecificationValidationTests(TestCase):
    """
    Formal validation test suite for Step 3:
    1. 50m swim ending in a soft-touch glide (finish matches physical touch within ±100ms).
    2. Two swimmers in the same lane pushing off on a 5-second stagger maintain independent timers.
    3. Swimmer standing on deck for 45 seconds transitions to OUTSIDE_POOL without ghost laps.
    """

    def setUp(self):
        self.manager = SessionStateMachineManager(session_id="spec_validation_pool", pool_length=25.0)

    def test_trace_1_soft_touch_glide_finish_accuracy(self):
        sm = self.manager.get_or_create("swimmer_glide")

        # Push-off from near wall at t=10.0 (confirmed at t=12.1)
        sm.update({
            "timestamp": 10.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 1.2,
            "stroke_count": 0,
            "accel": {"x": 2.2, "y": 0.0, "z": 0.98},
        })
        sm.update({
            "timestamp": 12.1,
            "x_m": 3.0,
            "y_m": 2.5,
            "speed_mps": 1.45,
            "stroke_count": 0,
            "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
        })
        self.assertEqual(sm.current_state, SwimmerState.SWIMMING)

        # Lap 1 turn at far wall (x=24.5m) at t=23.0
        sm.update({
            "timestamp": 23.0,
            "x_m": 24.5,
            "y_m": 2.5,
            "speed_mps": 1.0,
            "stroke_count": 12,
            "gyro": {"roll": 110.0, "pitch": 130.0, "yaw": 0.0},
        })
        self.assertEqual(sm.current_state, SwimmerState.TURN_TRANSITION)

        # Resumes swimming down pool towards near wall
        sm.update({
            "timestamp": 24.5,
            "x_m": 22.5,
            "y_m": 2.5,
            "speed_mps": 1.4,
            "stroke_count": 12,
        })
        self.assertEqual(sm.current_state, SwimmerState.SWIMMING)

        # Physical soft touch occurs at t=36.0 (x=0.4m, speed drops to 0.14 m/s)
        sm.update({
            "timestamp": 36.0,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.14,
            "stroke_count": 24,
        })

        # Swimmer rests at wall for 5 seconds until t=41.0
        evt_finish = sm.update({
            "timestamp": 41.0,
            "x_m": 0.4,
            "y_m": 2.5,
            "speed_mps": 0.02,
            "stroke_count": 24,
        })

        self.assertIsNotNone(evt_finish)
        self.assertEqual(evt_finish.new_state, SwimmerState.IDLE_AT_WALL)

        # Assert: backtracked timestamp matches physical touch at t=36.0 within 100ms
        finish_time = evt_finish.details["finish_timestamp"]
        self.assertAlmostEqual(finish_time, 36.0, delta=0.10)

        # Assert: total rep time is 26.0s (36.0 - 10.0) rather than 31.0s (41.0 - 10.0)
        rep = evt_finish.details["repetition_metrics"]
        self.assertAlmostEqual(rep["total_time_seconds"], 26.0, delta=0.10)
        self.assertEqual(len(rep["splits"]), 2)

    def test_trace_2_staggered_swimmers_independent_timers(self):
        sm_a = self.manager.get_or_create("swimmer_A")
        sm_b = self.manager.get_or_create("swimmer_B")

        # Swimmer A pushes off at t=10.0 (confirmed at t=12.1)
        sm_a.update({
            "timestamp": 10.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 1.2,
            "accel": {"x": 2.2, "y": 0.0, "z": 0.98},
        })
        sm_a.update({
            "timestamp": 12.1,
            "x_m": 3.0,
            "y_m": 2.5,
            "speed_mps": 1.4,
            "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
        })

        # Swimmer B pushes off 5 seconds later at t=15.0 (confirmed at t=17.1)
        sm_b.update({
            "timestamp": 15.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 1.1,
            "accel": {"x": 2.0, "y": 0.0, "z": 0.98},
        })
        sm_b.update({
            "timestamp": 17.1,
            "x_m": 2.9,
            "y_m": 2.5,
            "speed_mps": 1.35,
            "accel": {"x": 0.1, "y": 0.0, "z": 0.98},
        })

        # Both swimmers are swimming simultaneously in Lane 3
        self.assertEqual(sm_a.current_state, SwimmerState.SWIMMING)
        self.assertEqual(sm_b.current_state, SwimmerState.SWIMMING)

        # Assert: timers are strictly isolated and uncorrupted
        self.assertEqual(sm_a.current_rep_start_time, 10.0)
        self.assertEqual(sm_b.current_rep_start_time, 15.0)
        self.assertEqual(sm_a.current_rep_number, 1)
        self.assertEqual(sm_b.current_rep_number, 1)

    def test_trace_3_deck_dwell_no_ghost_laps(self):
        sm = self.manager.get_or_create("swimmer_deck")

        # 1. Swimmer steps out of the pool onto the deck at t=10.0 (x = -2.5m)
        evt_exit = sm.update({
            "timestamp": 10.0,
            "x_m": -2.5,
            "y_m": 2.5,
            "speed_mps": 0.7,
        })
        self.assertIsNotNone(evt_exit)
        self.assertEqual(evt_exit.new_state, SwimmerState.OUTSIDE_POOL)

        # 2. Swimmer stands/walks on pool deck for 45 seconds (until t=55.0)
        for t in range(15, 56, 10):
            evt_deck = sm.update({
                "timestamp": float(t),
                "x_m": -2.0,
                "y_m": 2.5,
                "speed_mps": 0.5,
            })
            self.assertIsNone(evt_deck)
            self.assertEqual(sm.current_state, SwimmerState.OUTSIDE_POOL)

        # 3. Swimmer steps back to the pool edge at t=56.0 (x = 0.5m)
        evt_enter = sm.update({
            "timestamp": 56.0,
            "x_m": 0.5,
            "y_m": 2.5,
            "speed_mps": 0.1,
        })
        self.assertIsNotNone(evt_enter)
        self.assertEqual(evt_enter.new_state, SwimmerState.IDLE_AT_WALL)

        # Assert: No ghost laps or repetitions were recorded during deck dwell
        self.assertEqual(len(sm.completed_laps), 0)
        self.assertIsNone(sm.latest_repetition_metrics)
        self.assertEqual(sm.current_rep_number, 0)