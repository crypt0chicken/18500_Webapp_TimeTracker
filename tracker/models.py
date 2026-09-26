from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class StrokeType(models.TextChoices):
    FREESTYLE = 'FREESTYLE', 'Freestyle'
    BACKSTROKE = 'BACKSTROKE', 'Backstroke'
    BREASTSTROKE = 'BREASTSTROKE', 'Breaststroke'
    BUTTERFLY = 'BUTTERFLY', 'Butterfly'
    INDIVIDUAL_MEDLEY = 'IM', 'Individual Medley'
    CHOICE = 'CHOICE', 'Choice'


class PoolCourse(models.TextChoices):
    SCY_25Y = 'SCY_25Y', 'Short Course Yards (25yd)'
    SCM_25M = 'SCM_25M', 'Short Course Meters (25m)'
    LCM_50M = 'LCM_50M', 'Long Course Meters (50m)'


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class SwimmerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='swimmer_profile',
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='swimmers',
    )
    # Baseline threshold velocity in meters per second (m/s)
    threshold_velocity = models.FloatField(
        default=1.30,
        help_text="Baseline aerobic threshold speed in m/s used for default effort scoring.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Profile)"


class PersonalBest(models.Model):
    swimmer = models.ForeignKey(
        SwimmerProfile,
        on_delete=models.CASCADE,
        related_name='personal_bests',
    )
    stroke = models.CharField(max_length=20, choices=StrokeType.choices)
    distance_units = models.CharField(max_length=10, choices=PoolCourse.choices)
    distance = models.PositiveIntegerField(help_text="Distance (e.g. 50, 100, 200)")
    time_seconds = models.FloatField(help_text="PB time recorded in seconds (e.g. 23.45)")
    achieved_at = models.DateField(auto_now=True)

    class Meta:
        unique_together = ('swimmer', 'stroke', 'distance_units', 'distance')

    def __str__(self):
        return f"{self.swimmer.user.username} - {self.distance} {self.get_stroke_display()}: {self.time_seconds:.2f}s"


class HardwareTag(models.Model):
    tag_id = models.CharField(
        max_length=32,
        unique=True,
        help_text="Hardware MAC address, UWB ID, or laser-etched ID string.",
    )
    battery_percentage = models.PositiveSmallIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    rssi = models.IntegerField(
        default=-65,
        help_text="Signal strength indicator in dBm (e.g., -60 to -90 dBm).",
    )
    firmware_version = models.CharField(max_length=32, default="1.0.0")
    active_swimmer = models.OneToOneField(
        SwimmerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_tag',
        help_text="Currently assigned swimmer for deck practice session.",
    )
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        assigned = self.active_swimmer.user.username if self.active_swimmer else "Unassigned"
        return f"Tag {self.tag_id} [{self.battery_percentage}% | {self.rssi}dBm] -> {assigned}"


class PracticeSession(models.Model):
    class PracticeMode(models.TextChoices):
        FREE_SWIM = 'FREE_SWIM', 'Free-Swim Capture'
        STRUCTURED = 'STRUCTURED', 'Pre-Programmed Sets'

    class SessionStatus(models.TextChoices):
        PLANNING = 'PLANNING', 'Planning'
        ACTIVE = 'ACTIVE', 'Active on Deck'
        COMPLETED = 'COMPLETED', 'Completed'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='sessions')
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coached_sessions',
    )
    pool_course = models.CharField(
        max_length=10,
        choices=PoolCourse.choices,
        default=PoolCourse.SCY_25Y,
    )
    mode = models.CharField(
        max_length=12,
        choices=PracticeMode.choices,
        default=PracticeMode.FREE_SWIM,
    )
    status = models.CharField(
        max_length=12,
        choices=SessionStatus.choices,
        default=SessionStatus.PLANNING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.team.name} Practice ({self.get_pool_course_display()}) - {self.created_at.strftime('%Y-%m-%d')}"


class WorkoutSet(models.Model):
    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name='sets',
    )
    set_order = models.PositiveSmallIntegerField(default=1)
    name = models.CharField(max_length=120, default="Main Set")
    stroke = models.CharField(
        max_length=20,
        choices=StrokeType.choices,
        default=StrokeType.FREESTYLE,
    )
    target_distance = models.PositiveIntegerField(default=100, help_text="Target distance in pool units (e.g. 50, 100)")
    target_interval_sec = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Send-off interval in seconds (e.g. 90 for 1:30)",
    )
    target_reps = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['set_order']

    def __str__(self):
        return f"Set {self.set_order}: {self.target_reps}x{self.target_distance} {self.get_stroke_display()}"


class Repetition(models.Model):
    workout_set = models.ForeignKey(
        WorkoutSet,
        on_delete=models.CASCADE,
        related_name='repetitions',
    )
    swimmer = models.ForeignKey(
        SwimmerProfile,
        on_delete=models.CASCADE,
        related_name='repetitions',
    )
    rep_number = models.PositiveSmallIntegerField(default=1)
    total_time_seconds = models.FloatField(default=0.0)
    rest_time_seconds = models.FloatField(default=0.0)
    effort_percentage = models.FloatField(
        default=0.0,
        help_text="Ratio of measured swim speed vs personal best speed (or baseline).",
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.swimmer.user.username} - Rep {self.rep_number}: {self.total_time_seconds:.2f}s ({self.effort_percentage:.1f}%)"


class LapSplit(models.Model):
    repetition = models.ForeignKey(
        Repetition,
        on_delete=models.CASCADE,
        related_name='splits',
    )
    lap_number = models.PositiveSmallIntegerField(default=1)
    split_time_seconds = models.FloatField(help_text="Duration of this specific lap split.")
    stroke_count = models.PositiveSmallIntegerField(default=0)
    stroke_rate = models.FloatField(default=0.0, help_text="Stroke cadence in strokes per minute.")
    dps = models.FloatField(default=0.0, help_text="Distance per stroke in meters.")
    breakout_distance_m = models.FloatField(default=0.0, help_text="Distance from wall at breakout in meters.")
    turn_time_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Turn window time (e.g., 5m in to 5m out).",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['lap_number']

    def __str__(self):
        return f"Lap {self.lap_number}: {self.split_time_seconds:.2f}s | DPS: {self.dps:.2f}m"


class SystemConfiguration(models.Model):
    allow_self_registration = models.BooleanField(
        default=True,
        help_text="Allow swimmers to self-register accounts.",
    )
    team_leaderboard_visible = models.BooleanField(
        default=False,
        help_text="Allow swimmers to view teammates' metrics and historical leaderboards.",
    )
    default_pool_course = models.CharField(
        max_length=10,
        choices=PoolCourse.choices,
        default=PoolCourse.SCY_25Y,
        help_text="Default pool standard for new practice sessions.",
    )

    class Meta:
        verbose_name = "System Configuration"
        verbose_name_plural = "System Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1  # Enforce singleton pattern
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Global System Configuration"


class LaneAssignment(models.Model):
    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name='lane_assignments',
    )
    swimmer = models.ForeignKey(
        SwimmerProfile,
        on_delete=models.CASCADE,
        related_name='lane_assignments',
    )
    tag = models.ForeignKey(
        HardwareTag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lane_assignments',
    )
    lane_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(8)],
        help_text="Assigned pool lane number (1 to 8)",
    )
    order_in_lane = models.PositiveSmallIntegerField(
        default=1,
        help_text="Position order in lane (1 = lead-off swimmer, 2 = second, etc.)",
    )
    staged_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'swimmer')
        ordering = ['lane_number', 'order_in_lane', 'staged_at']

    def __str__(self):
        tag_str = self.tag.tag_id if self.tag else "No Tag"
        return f"Lane {self.lane_number} (#{self.order_in_lane}): {self.swimmer.user.username} ({tag_str})"
