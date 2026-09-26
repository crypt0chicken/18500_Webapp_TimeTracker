import json
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import (
    HardwareTag,
    LaneAssignment,
    PoolCourse,
    PracticeSession,
    SwimmerProfile,
    Team,
    WorkoutSet,
)
from .permissions import coach_or_admin_required, verify_swimmer_metric_access


@coach_or_admin_required
def coach_session_view(request, session_id):
    """
    Renders the live coach deck dashboard with dual view support (Cards & Table).
    Supports multiple circling swimmers per lane with independent timers and metrics.
    """
    session = get_object_or_404(PracticeSession, id=session_id)
    assignments = LaneAssignment.objects.filter(session=session).select_related(
        'swimmer__user', 'tag'
    ).order_by('lane_number', 'order_in_lane', 'staged_at')

    swimmers_data = []
    assignment_by_lane = {lane: [] for lane in range(1, 9)}

    for a in assignments:
        item = {
            "swimmer_id": a.swimmer.id,
            "swimmer_name": a.swimmer.user.get_full_name() or a.swimmer.user.username,
            "lane_number": a.lane_number,
            "order_in_lane": a.order_in_lane,
            "threshold_velocity": a.swimmer.threshold_velocity,
            "tag_id": a.tag.tag_id if a.tag else None,
            "battery_percentage": a.tag.battery_percentage if a.tag else 100,
            "rssi": a.tag.rssi if a.tag else -65,
            "state": "IDLE_AT_WALL",
            "speed": 0.0,
            "stroke_rate": 0.0,
            "dps": 0.0,
            "breakout_m": 0.0,
            "turn_time": 0.0,
            "lap_number": 1,
            "rep_number": 1,
            "set_number": 1,
            "split_time": 0.0,
            "last_rep_time": 0.0,
            "effort_pct": 0.0,
            "x_m": 0.5,
            "wall_touch_time": None,
            "is_active": True,
        }
        swimmers_data.append(item)
        assignment_by_lane[a.lane_number].append(item)

    # Build backward-compatible lanes_data for the 8-lane Card Grid
    lanes_data = []
    for lane_num in range(1, 9):
        lane_swimmers = assignment_by_lane[lane_num]
        if lane_swimmers:
            lead = lane_swimmers[0]
            lanes_data.append({
                "lane_number": lane_num,
                "swimmers": lane_swimmers,
                "swimmer_id": lead["swimmer_id"],
                "swimmer_name": lead["swimmer_name"],
                "threshold_velocity": lead["threshold_velocity"],
                "tag_id": lead["tag_id"],
                "battery_percentage": lead["battery_percentage"],
                "rssi": lead["rssi"],
                "state": lead["state"],
                "speed": lead["speed"],
                "stroke_rate": lead["stroke_rate"],
                "dps": lead["dps"],
                "breakout_m": lead["breakout_m"],
                "turn_time": lead["turn_time"],
                "lap_number": lead["lap_number"],
                "rep_number": lead["rep_number"],
                "set_number": lead["set_number"],
                "split_time": lead["split_time"],
                "last_rep_time": lead["last_rep_time"],
                "effort_pct": lead["effort_pct"],
                "x_m": lead["x_m"],
                "wall_touch_time": lead["wall_touch_time"],
                "is_active": True,
            })
        else:
            lanes_data.append({
                "lane_number": lane_num,
                "swimmers": [],
                "swimmer_id": None,
                "swimmer_name": "Unassigned",
                "threshold_velocity": 0.0,
                "tag_id": None,
                "battery_percentage": None,
                "rssi": None,
                "state": "EMPTY",
                "speed": 0.0,
                "stroke_rate": 0.0,
                "dps": 0.0,
                "breakout_m": 0.0,
                "turn_time": 0.0,
                "lap_number": 0,
                "rep_number": 0,
                "set_number": 1,
                "split_time": 0.0,
                "last_rep_time": 0.0,
                "effort_pct": 0.0,
                "x_m": 0.0,
                "wall_touch_time": None,
                "is_active": False,
            })

    active_set = WorkoutSet.objects.filter(session=session).order_by('-set_order').first()

    return render(
        request,
        'tracker/dashboard.html',
        {
            'session': session,
            'lanes': list(range(1, 9)),
            'active_set': active_set,
            'lanes_json': json.dumps(lanes_data),
            'swimmers_json': json.dumps(swimmers_data),
            'pool_length': session.pool_length_meters() if hasattr(session, 'pool_length_meters') else 25.0,
        },
    )



def swimmer_metrics_view(request, swimmer_id):
    verify_swimmer_metric_access(request.user, swimmer_id)
    profile = get_object_or_404(SwimmerProfile, id=swimmer_id)
    return JsonResponse({
        "swimmer_id": profile.id,
        "username": profile.user.username,
        "threshold_velocity": profile.threshold_velocity,
        "reps_recorded": profile.repetitions.count(),
    })


@coach_or_admin_required
def deck_staging_view(request, session_id):
    session = get_object_or_404(PracticeSession, id=session_id)
    swimmers = SwimmerProfile.objects.filter(team=session.team).select_related('user', 'active_tag')
    tags = HardwareTag.objects.all().select_related('active_swimmer__user').order_by('tag_id')
    assignments = LaneAssignment.objects.filter(session=session).select_related('swimmer__user', 'tag')

    # Build initial JSON payloads for Alpine.js hydration
    assignment_map = {a.swimmer_id: a for a in assignments}

    swimmers_data = [
        {
            "id": s.id,
            "name": s.user.get_full_name() or s.user.username,
            "username": s.user.username,
            "threshold_velocity": s.threshold_velocity,
            "tag_id": s.active_tag.tag_id if hasattr(s, 'active_tag') and s.active_tag else None,
            "lane_number": assignment_map[s.id].lane_number if s.id in assignment_map else None,
        }
        for s in swimmers
    ]

    tags_data = [
        {
            "id": t.id,
            "tag_id": t.tag_id,
            "battery_percentage": t.battery_percentage,
            "assigned_swimmer_id": t.active_swimmer_id,
        }
        for t in tags
    ]

    assignments_data = [
        {
            "swimmer_id": a.swimmer_id,
            "swimmer_name": a.swimmer.user.get_full_name() or a.swimmer.user.username,
            "tag_id": a.tag.tag_id if a.tag else None,
            "battery_percentage": a.tag.battery_percentage if a.tag else None,
            "lane_number": a.lane_number,
        }
        for a in assignments
    ]

    return render(
        request,
        'tracker/staging.html',
        {
            'session': session,
            'lanes': list(range(1, 9)),
            'swimmers_json': json.dumps(swimmers_data),
            'tags_json': json.dumps(tags_data),
            'assignments_json': json.dumps(assignments_data),
        },
    )


@coach_or_admin_required
@require_POST
def pair_swimmer_tag_view(request, session_id):
    """
    3-Tap Pairing API: assigns Tag -> Swimmer -> Lane in one transaction.
    """
    session = get_object_or_404(PracticeSession, id=session_id)
    try:
        body = json.loads(request.body.decode('utf-8'))
        tag_id_str = body.get("tag_id")
        swimmer_id = int(body.get("swimmer_id"))
        lane_number = int(body.get("lane_number"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request payload"}, status=400)

    if not (1 <= lane_number <= 8):
        return JsonResponse({"error": "Lane number must be between 1 and 8"}, status=400)

    swimmer = get_object_or_404(SwimmerProfile, id=swimmer_id, team=session.team)
    tag = get_object_or_404(HardwareTag, tag_id=tag_id_str)

    # 1. Clear tag if it was assigned to another swimmer
    if tag.active_swimmer and tag.active_swimmer.id != swimmer.id:
        tag.active_swimmer = None
        tag.save()

    # 2. Clear any old tag currently bound to this swimmer
    HardwareTag.objects.filter(active_swimmer=swimmer).exclude(id=tag.id).update(active_swimmer=None)

    # 3. Bind tag to swimmer
    tag.active_swimmer = swimmer
    tag.save()

    # 4. Upsert LaneAssignment
    assignment, _ = LaneAssignment.objects.update_or_create(
        session=session,
        swimmer=swimmer,
        defaults={
            "tag": tag,
            "lane_number": lane_number,
        },
    )

    return JsonResponse({
        "status": "success",
        "assignment": {
            "swimmer_id": swimmer.id,
            "swimmer_name": swimmer.user.get_full_name() or swimmer.user.username,
            "tag_id": tag.tag_id,
            "battery_percentage": tag.battery_percentage,
            "lane_number": assignment.lane_number,
        },
    })


@coach_or_admin_required
@require_POST
def unassign_swimmer_view(request, session_id):
    """
    Removes swimmer's active tag and unassigns them from their staged lane.
    """
    session = get_object_or_404(PracticeSession, id=session_id)
    try:
        body = json.loads(request.body.decode('utf-8'))
        swimmer_id = int(body.get("swimmer_id"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request payload"}, status=400)

    swimmer = get_object_or_404(SwimmerProfile, id=swimmer_id, team=session.team)

    # Unbind tag
    HardwareTag.objects.filter(active_swimmer=swimmer).update(active_swimmer=None)

    # Delete lane assignment
    LaneAssignment.objects.filter(session=session, swimmer=swimmer).delete()

    return JsonResponse({"status": "success", "swimmer_id": swimmer_id})


@coach_or_admin_required
@require_POST
def swap_tag_view(request, session_id):
  """1-Tap Swap Tag API: Rebinds an active swimmer to a replacement hardware ID mid-session

  without losing or mutating any existing repetitions, splits, or session data.
  """
  session = get_object_or_404(PracticeSession, id=session_id)
  try:
    body = json.loads(request.body.decode('utf-8'))
    swimmer_id = int(body.get('swimmer_id'))
    new_tag_id = str(body.get('new_tag_id', '')).strip()
  except (TypeError, ValueError, json.JSONDecodeError):
    return JsonResponse({'error': 'Invalid request payload'}, status=400)

  if not new_tag_id:
    return JsonResponse({'error': 'New tag ID is required'}, status=400)

  swimmer = get_object_or_404(SwimmerProfile, id=swimmer_id, team=session.team)
  new_tag = get_object_or_404(HardwareTag, tag_id=new_tag_id)

  # 1. Identify previous tag if one was bound
  old_tag = HardwareTag.objects.filter(active_swimmer=swimmer).first()
  old_tag_id = old_tag.tag_id if old_tag else None

  # 2. Release previous tag from swimmer
  if old_tag and old_tag.id != new_tag.id:
    old_tag.active_swimmer = None
    old_tag.save()

  # 3. If new tag was bound to another swimmer, release it and unstage their tag reference
  if new_tag.active_swimmer and new_tag.active_swimmer.id != swimmer.id:
    displaced_swimmer = new_tag.active_swimmer
    LaneAssignment.objects.filter(
        session=session, swimmer=displaced_swimmer, tag=new_tag
    ).update(tag=None)
    new_tag.active_swimmer = None
    new_tag.save()

  # 4. Guarantee no other tag points to this swimmer (prevents OneToOne uniqueness violations)
  HardwareTag.objects.filter(active_swimmer=swimmer).exclude(
      id=new_tag.id
  ).update(active_swimmer=None)

  # 5. Rebind replacement tag to swimmer
  new_tag.active_swimmer = swimmer
  new_tag.save()

  # 6. Update LaneAssignment for this session
  assignment, _ = LaneAssignment.objects.get_or_create(
      session=session,
      swimmer=swimmer,
      defaults={'lane_number': 1, 'tag': new_tag},
  )
  assignment.tag = new_tag
  assignment.save()

  return JsonResponse({
      'status': 'success',
      'swimmer_id': swimmer.id,
      'old_tag_id': old_tag_id,
      'new_tag_id': new_tag.tag_id,
      'battery_percentage': new_tag.battery_percentage,
      'assignment': {
          'swimmer_id': swimmer.id,
          'swimmer_name': (
              swimmer.user.get_full_name() or swimmer.user.username
          ),
          'tag_id': new_tag.tag_id,
          'battery_percentage': new_tag.battery_percentage,
          'lane_number': assignment.lane_number,
      },
  })

@coach_or_admin_required
def deck_staging_view(request, session_id):
    session = get_object_or_404(PracticeSession, id=session_id)
    swimmers = SwimmerProfile.objects.filter(team=session.team).select_related('user', 'active_tag')
    tags = HardwareTag.objects.all().select_related('active_swimmer__user').order_by('tag_id')
    assignments = LaneAssignment.objects.filter(session=session).select_related('swimmer__user', 'tag')

    assignment_map = {a.swimmer_id: a for a in assignments}
    now = timezone.now()

    swimmers_data = [
        {
            "id": s.id,
            "name": s.user.get_full_name() or s.user.username,
            "username": s.user.username,
            "threshold_velocity": s.threshold_velocity,
            "tag_id": s.active_tag.tag_id if hasattr(s, 'active_tag') and s.active_tag else None,
            "lane_number": assignment_map[s.id].lane_number if s.id in assignment_map else None,
        }
        for s in swimmers
    ]

    tags_data = []
    for t in tags:
        seconds_ago = (now - t.last_seen).total_seconds() if t.last_seen else 9999
        is_online = seconds_ago < 60  # Tag considered online if seen in past 60 seconds

        tags_data.append({
            "id": t.id,
            "tag_id": t.tag_id,
            "battery_percentage": t.battery_percentage,
            "rssi": t.rssi,
            "is_online": is_online,
            "last_seen_sec": int(seconds_ago),
            "assigned_swimmer_id": t.active_swimmer_id,
        })

    assignments_data = [
        {
            "swimmer_id": a.swimmer_id,
            "swimmer_name": a.swimmer.user.get_full_name() or a.swimmer.user.username,
            "tag_id": a.tag.tag_id if a.tag else None,
            "battery_percentage": a.tag.battery_percentage if a.tag else None,
            "rssi": a.tag.rssi if a.tag else -99,
            "lane_number": a.lane_number,
        }
        for a in assignments
    ]

    return render(
        request,
        'tracker/staging.html',
        {
            'session': session,
            'lanes': list(range(1, 9)),
            'swimmers_json': json.dumps(swimmers_data),
            'tags_json': json.dumps(tags_data),
            'assignments_json': json.dumps(assignments_data),
        },
    )


from accounts.models import User
from .models import HardwareTag, LaneAssignment, PoolCourse, PracticeSession, SwimmerProfile, Team, WorkoutSet


def index_view(request):
    """
    Root entry point: redirects authenticated coaches/admins to the active
    session staging screen, auto-seeding sample athletes and lane assignments
    for local development if none exist.
    """
    if not request.user.is_authenticated:
        return redirect('/admin/login/?next=/')

    session = PracticeSession.objects.order_by('-created_at').first()

    if not session:
        team, _ = Team.objects.get_or_create(name="CMU Aquatics")
        session = PracticeSession.objects.create(
            team=team,
            coach=request.user,
            pool_course=PoolCourse.SCY_25Y,
            status=PracticeSession.SessionStatus.ACTIVE,
        )

    # Auto-seed sample athletes and stage lanes 1 to 8 if not yet staged
    if not LaneAssignment.objects.filter(session=session).exists():
        sample_names = [
            ("Alex", "Vance", 1.45),
            ("Jordan", "Lee", 1.42),
            ("Morgan", "Smith", 1.38),
            ("Taylor", "Swift", 1.40),
            ("Casey", "Jones", 1.36),
            ("Riley", "Reid", 1.44),
            ("Sam", "Miller", 1.39),
            ("Chris", "Evans", 1.41),
        ]
        for idx, (first, last, thresh) in enumerate(sample_names, start=1):
            user, _ = User.objects.get_or_create(
                username=f"{first.lower()}_{last.lower()}",
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": User.Role.SWIMMER,
                },
            )
            profile, _ = SwimmerProfile.objects.get_or_create(
                user=user,
                team=session.team,
                defaults={"threshold_velocity": thresh},
            )
            tag, _ = HardwareTag.objects.get_or_create(
                tag_id=f"TAG_{idx:02d}",
                defaults={
                    "battery_percentage": 90 + (idx % 10),
                    "rssi": -65 - idx,
                    "active_swimmer": profile,
                },
            )
            tag.active_swimmer = profile
            tag.save()

            LaneAssignment.objects.get_or_create(
                session=session,
                swimmer=profile,
                defaults={
                    "tag": tag,
                    "lane_number": idx,
                },
            )

        WorkoutSet.objects.get_or_create(
            session=session,
            set_order=1,
            defaults={
                "name": "50m Threshold Pace",
                "target_distance": 50,
                "target_reps": 6,
            },
        )

    return redirect('tracker:coach_session', session_id=session.id)
    """
    Renders the live coach deck dashboard with an 8-lane responsive grid,
    real-time telemetry readouts, running clocks, and biometric status indicators.
    """
    session = get_object_or_404(PracticeSession, id=session_id)
    assignments = LaneAssignment.objects.filter(session=session).select_related('swimmer__user', 'tag')

    # Index assignments by lane number (1 to 8)
    assignment_by_lane = {a.lane_number: a for a in assignments}
    lanes_data = []

    for lane_num in range(1, 9):
        assign = assignment_by_lane.get(lane_num)
        if assign:
            lanes_data.append({
                "lane_number": lane_num,
                "swimmer_id": assign.swimmer.id,
                "swimmer_name": assign.swimmer.user.get_full_name() or assign.swimmer.user.username,
                "threshold_velocity": assign.swimmer.threshold_velocity,
                "tag_id": assign.tag.tag_id if assign.tag else None,
                "battery_percentage": assign.tag.battery_percentage if assign.tag else 100,
                "rssi": assign.tag.rssi if assign.tag else -65,
                "state": "IDLE_AT_WALL",
                "speed": 0.0,
                "stroke_rate": 0.0,
                "dps": 0.0,
                "breakout_m": 0.0,
                "lap_number": 1,
                "rep_number": 1,
                "set_number": 1,
                "split_time": 0.0,
                "last_rep_time": 0.0,
                "effort_pct": 0.0,
                "x_m": 0.5,
                "is_active": True,
            })
        else:
            lanes_data.append({
                "lane_number": lane_num,
                "swimmer_id": None,
                "swimmer_name": "Unassigned",
                "threshold_velocity": 0.0,
                "tag_id": None,
                "battery_percentage": None,
                "rssi": None,
                "state": "EMPTY",
                "speed": 0.0,
                "stroke_rate": 0.0,
                "dps": 0.0,
                "breakout_m": 0.0,
                "lap_number": 0,
                "rep_number": 0,
                "set_number": 1,
                "split_time": 0.0,
                "last_rep_time": 0.0,
                "effort_pct": 0.0,
                "x_m": 0.0,
                "is_active": False,
            })

    aactive_set = WorkoutSet.objects.filter(session=session).order_by('-set_order').first()

    return render(
        request,
        'tracker/dashboard.html',
        {
            'session': session,
            'lanes': list(range(1, 9)),
            'active_set': active_set,
            'lanes_json': json.dumps(lanes_data),
            'pool_length': session.pool_length_meters() if hasattr(session, 'pool_length_meters') else 25.0,
        },
    )