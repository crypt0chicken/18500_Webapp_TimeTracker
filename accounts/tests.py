from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_swimmer(self):
        user = User.objects.create_user(
            username='swimmer_test',
            password='securepassword123',
            role=User.Role.SWIMMER
        )
        self.assertEqual(user.role, User.Role.SWIMMER)
        self.assertTrue(user.is_swimmer_role)
        self.assertFalse(user.is_coach_role)

    def test_create_coach(self):
        user = User.objects.create_user(
            username='coach_test',
            password='securepassword123',
            role=User.Role.COACH
        )
        self.assertEqual(user.role, User.Role.COACH)
        self.assertTrue(user.is_coach_role)
        self.assertFalse(user.is_swimmer_role)

    def test_default_role_is_swimmer(self):
        user = User.objects.create_user(
            username='default_test',
            password='securepassword123'
        )
        self.assertEqual(user.role, User.Role.SWIMMER)