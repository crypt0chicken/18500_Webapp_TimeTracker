from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from tracker.models import (
    Team,
    SwimmerProfile,
    PracticeSession,
    PoolCourse,
    SystemConfiguration,
    HardwareTag,
)

User = get_user_model()


class StepOneValidationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.team = Team.objects.create(name="Predators Swim Club")

        # Coach user
        self.coach_user = User.objects.create_user(
            username="coach_mike",
            password="securepassword123",
            role=User.Role.COACH,
        )

        # Swimmer 1 (User + Profile)
        self.swimmer_user_1 = User.objects.create_user(
            username="swimmer_alice",
            password="securepassword123",
            role=User.Role.SWIMMER,
        )
        self.profile_1 = SwimmerProfile.objects.create(
            user=self.swimmer_user_1,
            team=self.team,
        )

        # Swimmer 2 (Teammate)
        self.swimmer_user_2 = User.objects.create_user(
            username="swimmer_bob",
            password="securepassword123",
            role=User.Role.SWIMMER,
        )
        self.profile_2 = SwimmerProfile.objects.create(
            user=self.swimmer_user_2,
            team=self.team,
        )

        # Practice session
        self.session = PracticeSession.objects.create(
            team=self.team,
            coach=self.coach_user,
            pool_course=PoolCourse.SCY_25Y,
        )

        # System configuration baseline
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

        # 1. When team_leaderboard_visible is False -> 403 Forbidden
        response = self.client.get(target_url)
        self.assertEqual(response.status_code, 403)

        # 2. When admin enables team_leaderboard_visible -> 200 OK
        self.config.team_leaderboard_visible = True
        self.config.save()

        response = self.client.get(target_url)
        self.assertEqual(response.status_code, 200)

    def test_hardware_tag_unassign_action(self):
        tag = HardwareTag.objects.create(
            tag_id="TAG_TEST_01",
            battery_percentage=88,
            active_swimmer=self.profile_1,
        )
        self.assertEqual(tag.active_swimmer, self.profile_1)

        # Execute unassign
        HardwareTag.objects.filter(id=tag.id).update(active_swimmer=None)
        tag.refresh_from_db()
        self.assertIsNone(tag.active_swimmer)