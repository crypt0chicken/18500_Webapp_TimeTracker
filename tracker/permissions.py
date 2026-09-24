from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import SwimmerProfile, SystemConfiguration


def coach_or_admin_required(view_func):
    """Enforces that the user has Coach or Admin role."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required.")
        if request.user.is_coach_role or request.user.is_admin_role:
            return view_func(request, *args, **kwargs)
        raise PermissionDenied("Coach or Admin access required.")
    return _wrapped_view


def verify_swimmer_metric_access(request_user, target_swimmer_id: int):
    """
    Validates whether request_user is authorized to view target swimmer's metrics.
    - Admins and Coaches: unrestricted access.
    - Swimmers: access own data, or teammate data ONLY if team_leaderboard_visible is True.
    """
    if not request_user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if request_user.is_coach_role or request_user.is_admin_role:
        return True

    target_profile = get_object_or_404(SwimmerProfile, id=target_swimmer_id)
    user_profile = getattr(request_user, 'swimmer_profile', None)

    if not user_profile:
        raise PermissionDenied("No swimmer profile associated with user.")

    # Viewing own data is always permitted
    if user_profile.id == target_profile.id:
        return True

    # Check admin toggle for teammate visibility
    config = SystemConfiguration.get_solo()
    if config.team_leaderboard_visible:
        # Permitted only if both athletes belong to the exact same team
        if user_profile.team and user_profile.team_id == target_profile.team_id:
            return True

    raise PermissionDenied("Access to teammate performance data is restricted.")