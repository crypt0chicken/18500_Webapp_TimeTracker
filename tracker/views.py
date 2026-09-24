from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import PracticeSession, SwimmerProfile
from .permissions import coach_or_admin_required, verify_swimmer_metric_access


@coach_or_admin_required
def coach_session_view(request, session_id):
    session = get_object_or_404(PracticeSession, id=session_id)
    return JsonResponse({
        "session_id": session.id,
        "team": session.team.name,
        "course": session.pool_course,
        "status": session.status,
    })


def swimmer_metrics_view(request, swimmer_id):
    verify_swimmer_metric_access(request.user, swimmer_id)
    profile = get_object_or_404(SwimmerProfile, id=swimmer_id)
    return JsonResponse({
        "swimmer_id": profile.id,
        "username": profile.user.username,
        "threshold_velocity": profile.threshold_velocity,
        "reps_recorded": profile.repetitions.count(),
    })