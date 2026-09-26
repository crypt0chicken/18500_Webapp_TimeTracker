import logging
from typing import Any, Optional
from channels.db import database_sync_to_async
from django.db import transaction
from .models import LapSplit, PracticeSession, Repetition, SwimmerProfile, WorkoutSet

logger = logging.getLogger(__name__)


def resolve_swimmer_profile(identifier: Any) -> Optional[SwimmerProfile]:
    """
    Resolves a SwimmerProfile from an ID, username, or assigned HardwareTag ID.
    """
    ident_str = str(identifier).strip()

    # 1. Lookup by primary key integer if numeric
    if ident_str.isdigit():
        profile = SwimmerProfile.objects.filter(id=int(ident_str)).first()
        if profile:
            return profile

    # 2. Lookup by username
    profile = SwimmerProfile.objects.filter(user__username=ident_str).first()
    if profile:
        return profile

    # 3. Lookup by hardware tag ID
    profile = SwimmerProfile.objects.filter(active_tag__tag_id=ident_str).first()
    if profile:
        return profile

    return None


def resolve_practice_session(session_id: Any) -> Optional[PracticeSession]:
    """
    Resolves the active PracticeSession from the session identifier.
    """
    s_str = str(session_id).strip()
    if s_str.isdigit():
        return PracticeSession.objects.filter(id=int(s_str)).first()
    return PracticeSession.objects.first()


@transaction.atomic
def save_repetition_metrics_sync(
    session_id: Any,
    swimmer_identifier: Any,
    rep_metrics: dict[str, Any],
) -> Optional[Repetition]:
    """
    Atomically writes aggregated Repetition and LapSplit records to the database.
    """
    session = resolve_practice_session(session_id)
    if not session:
        logger.error("Failed to persist metrics: PracticeSession '%s' not found.", session_id)
        return None

    swimmer = resolve_swimmer_profile(swimmer_identifier)
    if not swimmer:
        logger.error("Failed to persist metrics: Swimmer '%s' not found.", swimmer_identifier)
        return None

    set_number = rep_metrics.get("set_number", 1)
    rep_number = rep_metrics.get("rep_number", 1)
    total_time = rep_metrics.get("total_time_seconds", 0.0)
    rest_time = rep_metrics.get("rest_time_seconds", 0.0)
    effort_pct = rep_metrics.get("effort_percentage", 0.0)
    splits_data = rep_metrics.get("splits", [])

    # Ensure the parent WorkoutSet exists for this session and set number
    workout_set, _ = WorkoutSet.objects.get_or_create(
        session=session,
        set_order=set_number,
        defaults={
            "name": f"Set {set_number}",
            "target_distance": session.pool_length_meters() if hasattr(session, "pool_length_meters") else 50,
            "target_reps": max(1, rep_number),
        },
    )

    # Create the Repetition record
    repetition = Repetition.objects.create(
        workout_set=workout_set,
        swimmer=swimmer,
        rep_number=rep_number,
        total_time_seconds=total_time,
        rest_time_seconds=rest_time,
        effort_percentage=effort_pct,
    )

    # Bulk create child LapSplit records
    lap_splits = [
        LapSplit(
            repetition=repetition,
            lap_number=s.get("lap_number", idx + 1),
            split_time_seconds=s.get("split_time_seconds", 0.0),
            stroke_count=s.get("stroke_count", 0),
            stroke_rate=s.get("stroke_rate", 0.0),
            dps=s.get("dps", 0.0),
            breakout_distance_m=s.get("breakout_distance_m", 0.0),
            turn_time_seconds=s.get("turn_time_seconds"),
        )
        for idx, s in enumerate(splits_data)
    ]

    if lap_splits:
        LapSplit.objects.bulk_create(lap_splits)

    return repetition


@database_sync_to_async
def persist_completed_repetition(
    session_id: Any,
    swimmer_identifier: Any,
    rep_metrics: dict[str, Any],
) -> Optional[Repetition]:
    """Asynchronous wrapper for save_repetition_metrics_sync."""
    return save_repetition_metrics_sync(session_id, swimmer_identifier, rep_metrics)