from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        COACH = 'COACH', 'Coach'
        SWIMMER = 'SWIMMER', 'Swimmer'
        

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.SWIMMER,
        help_text="Designates the system permissions tier for this user.",
    )

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_coach_role(self) -> bool:
        return self.role == self.Role.COACH

    @property
    def is_swimmer_role(self) -> bool:
        return self.role == self.Role.SWIMMER

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"