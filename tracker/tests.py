import time
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

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