from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Optional


class SwimmerState(str, Enum):
    IDLE_AT_WALL = "IDLE_AT_WALL"
    SWIMMING = "SWIMMING"
    TURN_TRANSITION = "TURN_TRANSITION"
    OUTSIDE_POOL = "OUTSIDE_POOL"


@dataclass
class TelemetryPoint:
    timestamp: float
    sequence_id: int
    x: float
    y: float
    speed: float
    stroke_rate: float
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_roll: float
    gyro_pitch: float
    gyro_yaw: float
    stroke_count: int = 0  # Added stroke_count with default 0
    phase: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TelemetryPoint":
        accel = data.get("accel") or {}
        gyro = data.get("gyro") or {}
        return cls(
            timestamp=float(data.get("timestamp", 0.0)),
            sequence_id=int(data.get("sequence_id", 0)),
            x=float(data.get("x_m", 0.0)),
            y=float(data.get("y_m", 0.0)),
            speed=float(data.get("speed_mps", 0.0)),
            stroke_rate=float(data.get("stroke_rate_spm", 0.0)),
            stroke_count=int(data.get("stroke_count", 0)),  # Safely parse stroke_count
            accel_x=float(accel.get("x", 0.0)),
            accel_y=float(accel.get("y", 0.0)),
            accel_z=float(accel.get("z", 0.0)),
            gyro_roll=float(gyro.get("roll", 0.0)),
            gyro_pitch=float(gyro.get("pitch", 0.0)),
            gyro_yaw=float(gyro.get("yaw", 0.0)),
            phase=str(data.get("phase", "")),
        )


@dataclass
class LapMetrics:
    lap_number: int
    split_time_seconds: float
    stroke_count: int
    stroke_rate: float
    dps: float
    breakout_distance_m: float
    turn_time_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepetitionMetrics:
    rep_number: int
    set_number: int
    total_time_seconds: float
    rest_time_seconds: float
    effort_percentage: float
    splits: list[LapMetrics]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["splits"] = [s.to_dict() if isinstance(s, LapMetrics) else s for s in self.splits]
        return data


def calculate_dps(clean_distance_m: float, stroke_count: int) -> float:
    """Distance Per Stroke (DPS) in meters = clean distance / stroke count."""
    if stroke_count <= 0 or clean_distance_m <= 0:
        return 0.0
    return round(clean_distance_m / stroke_count, 2)


def calculate_effort_percentage(
    total_time_seconds: float,
    distance_m: float,
    pb_time_seconds: Optional[float] = None,
    threshold_velocity_mps: float = 1.30,
) -> float:
    """
    Effort percentage:
    - If PB time is provided: (t_PB / t_current) * 100
    - If no PB time: (v_current / v_threshold) * 100
    """
    if total_time_seconds <= 0 or distance_m <= 0:
        return 0.0
    if pb_time_seconds and pb_time_seconds > 0:
        return round((pb_time_seconds / total_time_seconds) * 100.0, 2)
    current_velocity = distance_m / total_time_seconds
    return round((current_velocity / threshold_velocity_mps) * 100.0, 2)


@dataclass
class StateTransitionEvent:
    swimmer_id: str
    previous_state: SwimmerState
    new_state: SwimmerState
    timestamp: float
    telemetry_point: TelemetryPoint
    details: dict[str, Any]


class SwimmerStateMachine:
    """
    State machine tracking an individual swimmer through practice sessions.
    Maintains a rolling 10-second history buffer for kinematic analysis,
    tracks multi-lap repetitions, extracts biomechanical metrics,
    and detects automatic set breaks (> 90 seconds wall dwell).
    """

    def __init__(
        self,
        swimmer_id: str,
        pool_length: float = 25.0,
        lane_width: float = 2.5,
        total_lanes: int = 8,
        history_window_sec: float = 10.0,
        initial_state: SwimmerState = SwimmerState.IDLE_AT_WALL,
        pb_time_seconds: Optional[float] = None,
        threshold_velocity_mps: float = 1.30,
        set_break_dwell_threshold_sec: float = 90.0,
    ):
        self.swimmer_id = str(swimmer_id)
        self.pool_length = pool_length
        self.lane_width = lane_width
        self.pool_width = total_lanes * lane_width
        self.history_window_sec = history_window_sec
        self.pb_time_seconds = pb_time_seconds
        self.threshold_velocity_mps = threshold_velocity_mps
        self.set_break_dwell_threshold_sec = set_break_dwell_threshold_sec

        self.current_state = initial_state
        self.state_entered_time: float = 0.0
        self.last_update_time: float = 0.0

        # Rolling history buffer bounded by time
        self.history: deque[TelemetryPoint] = deque()

        # Spatial thresholds with hysteresis
        self.wall_zone_enter_m = 1.0
        self.wall_zone_exit_m = 1.8
        self.outside_pool_x_margin = 1.5
        self.outside_pool_y_margin = 1.2

        # Push-off detection state (Step 3.2)
        self.candidate_push_off_time: Optional[float] = None
        self.candidate_push_off_point: Optional[TelemetryPoint] = None
        self.confirmed_push_off_time: Optional[float] = None

        # Backtracking & finish state (Step 3.3)
        self.wall_idle_start_time: Optional[float] = None
        self.confirmed_finish_time: Optional[float] = None
        self.idle_confirmation_threshold_sec: float = 5.0
        self.finish_speed_threshold_mps: float = 0.20

        # Metric tracking & set management state (Step 3.4)
        self.current_set_number: int = 1
        self.current_rep_number: int = 0
        self.current_lap_number: int = 1
        self.current_rep_start_time: Optional[float] = None
        self.current_lap_start_time: Optional[float] = None
        self.last_rep_finish_time: Optional[float] = None
        self.last_rest_duration: float = 0.0
        self.lap_stroke_count_start: int = 0
        self.lap_breakout_distance: Optional[float] = None
        self.push_off_wall_x: float = 0.0
        self.completed_laps: list[LapMetrics] = []
        self.latest_repetition_metrics: Optional[RepetitionMetrics] = None
        self.set_break_emitted: bool = False

    def is_in_wall_zone(self, x: float, enter: bool = True) -> bool:
        threshold = self.wall_zone_enter_m if enter else self.wall_zone_exit_m
        near_wall = x <= threshold
        far_wall = x >= (self.pool_length - threshold)
        return near_wall or far_wall

    def is_outside_pool_boundary(self, x: float, y: float) -> bool:
        outside_x = (x < -self.outside_pool_x_margin) or (x > self.pool_length + self.outside_pool_x_margin)
        outside_y = (y < -self.outside_pool_y_margin) or (y > self.pool_width + self.outside_pool_y_margin)
        return outside_x or outside_y

    def is_push_off_impulse(self, point: TelemetryPoint) -> bool:
        is_near_wall = point.x <= (self.pool_length / 2.0)
        accel_mag = math.sqrt(point.accel_x**2 + point.accel_y**2)

        if is_near_wall:
            return (point.accel_x > 1.5) or (accel_mag > 1.5 and point.speed > 0.2)
        else:
            return (point.accel_x < -1.5) or (accel_mag > 1.5 and point.speed > 0.2)

    def backtrack_finish_timestamp(self) -> float:
        if not self.history:
            return self.last_update_time - self.idle_confirmation_threshold_sec

        earliest_stopped_point: Optional[TelemetryPoint] = None

        for pt in reversed(self.history):
            in_wall = self.is_in_wall_zone(pt.x, enter=True)
            if in_wall and pt.speed <= self.finish_speed_threshold_mps:
                earliest_stopped_point = pt
            elif in_wall and pt.speed > self.finish_speed_threshold_mps:
                break
            elif not in_wall:
                break

        if earliest_stopped_point is not None:
            return earliest_stopped_point.timestamp

        wall_points = [p for p in self.history if self.is_in_wall_zone(p.x, enter=True)]
        if wall_points:
            min_speed_pt = min(wall_points, key=lambda p: p.speed)
            return min_speed_pt.timestamp

        return self.last_update_time - self.idle_confirmation_threshold_sec

    def update(self, packet_data: dict[str, Any]) -> Optional[StateTransitionEvent]:
        point = TelemetryPoint.from_dict(packet_data)
        now = point.timestamp

        if self.state_entered_time == 0.0:
            self.state_entered_time = now
        self.last_update_time = now

        # Append to rolling buffer and evict points older than history window
        self.history.append(point)
        cutoff_time = now - self.history_window_sec
        while self.history and self.history[0].timestamp < cutoff_time:
            self.history.popleft()

        # Step 3.4: Breakout distance detection during swimming or glide
        if self.current_state in (SwimmerState.SWIMMING, SwimmerState.TURN_TRANSITION):
            if self.lap_breakout_distance is None:
                is_breaking_out = (
                    point.phase == "SURFACE_SWIM"
                    or (point.stroke_count > self.lap_stroke_count_start)
                    or (point.stroke_rate > 0.0 and point.speed > 0.8)
                )
                if is_breaking_out:
                    if self.push_off_wall_x == 0.0:
                        self.lap_breakout_distance = round(max(0.0, min(self.pool_length, point.x)), 2)
                    else:
                        self.lap_breakout_distance = round(max(0.0, min(self.pool_length, self.pool_length - point.x)), 2)

        # Step 3.4: Auto Set-Break Detection (> 90s dwell at wall)
        if self.current_state == SwimmerState.IDLE_AT_WALL:
            ref_time = self.last_rep_finish_time if self.last_rep_finish_time is not None else self.state_entered_time
            dwell = now - ref_time
            if dwell >= self.set_break_dwell_threshold_sec and not self.set_break_emitted:
                self.set_break_emitted = True
                return StateTransitionEvent(
                    swimmer_id=self.swimmer_id,
                    previous_state=self.current_state,
                    new_state=self.current_state,
                    timestamp=now,
                    telemetry_point=point,
                    details={
                        "event_type": "SET_BREAK",
                        "dwell_duration_sec": round(dwell, 2),
                        "completed_set_number": self.current_set_number,
                        "next_set_number": self.current_set_number + 1,
                    },
                )

        # Evaluate state boundary transitions
        new_state = self._evaluate_next_state(point)
        if new_state != self.current_state:
            push_time = self.confirmed_push_off_time or now
            finish_time = self.confirmed_finish_time or now

            details: dict[str, Any] = {
                "dwell_in_previous_state_sec": round(now - self.state_entered_time, 3),
                "x": point.x,
                "y": point.y,
                "speed": point.speed,
                "push_off_timestamp": push_time,
                "finish_timestamp": finish_time,
            }
            if self.confirmed_finish_time is not None:
                details["backtrack_delta_sec"] = round(now - self.confirmed_finish_time, 3)

            # Transition: IDLE_AT_WALL -> SWIMMING (Push-off initiated)
            if self.current_state == SwimmerState.IDLE_AT_WALL and new_state == SwimmerState.SWIMMING:
                if self.set_break_emitted:
                    self.current_set_number += 1
                    self.current_rep_number = 1
                    self.set_break_emitted = False
                else:
                    self.current_rep_number += 1

                if self.last_rep_finish_time is not None:
                    self.last_rest_duration = round(max(0.0, push_time - self.last_rep_finish_time), 2)
                else:
                    self.last_rest_duration = 0.0

                self.current_lap_number = 1
                self.current_rep_start_time = push_time
                self.current_lap_start_time = push_time
                self.lap_stroke_count_start = point.stroke_count
                self.lap_breakout_distance = None
                self.push_off_wall_x = 0.0 if point.x <= (self.pool_length / 2.0) else self.pool_length
                self.completed_laps = []

                details["rep_number"] = self.current_rep_number
                details["set_number"] = self.current_set_number
                details["rest_time_seconds"] = self.last_rest_duration

            # Transition: SWIMMING -> TURN_TRANSITION (Lap completed at turn wall)
            elif self.current_state == SwimmerState.SWIMMING and new_state == SwimmerState.TURN_TRANSITION:
                lap_start = self.current_lap_start_time or self.state_entered_time
                split_time = round(max(0.1, now - lap_start), 2)
                strokes = max(0, point.stroke_count - self.lap_stroke_count_start)
                breakout = self.lap_breakout_distance if self.lap_breakout_distance is not None else 5.0
                clean_dist = max(1.0, self.pool_length - breakout)
                dps = calculate_dps(clean_dist, strokes)

                lap_metrics = LapMetrics(
                    lap_number=self.current_lap_number,
                    split_time_seconds=split_time,
                    stroke_count=strokes,
                    stroke_rate=point.stroke_rate,
                    dps=dps,
                    breakout_distance_m=breakout,
                    turn_time_seconds=None,
                )
                self.completed_laps.append(lap_metrics)
                details["completed_lap"] = lap_metrics.to_dict()

                # Prep next lap
                self.current_lap_number += 1
                self.current_lap_start_time = now
                self.lap_stroke_count_start = point.stroke_count
                self.lap_breakout_distance = None
                self.push_off_wall_x = self.pool_length if self.push_off_wall_x == 0.0 else 0.0

            # Transition: SWIMMING/TURN_TRANSITION -> IDLE_AT_WALL (Rep completed)
            elif self.current_state in (SwimmerState.SWIMMING, SwimmerState.TURN_TRANSITION) and new_state == SwimmerState.IDLE_AT_WALL:
                lap_start = self.current_lap_start_time or self.state_entered_time
                split_time = round(max(0.1, finish_time - lap_start), 2)
                strokes = max(0, point.stroke_count - self.lap_stroke_count_start)
                breakout = self.lap_breakout_distance if self.lap_breakout_distance is not None else 5.0
                clean_dist = max(1.0, self.pool_length - breakout)
                dps = calculate_dps(clean_dist, strokes)

                final_lap = LapMetrics(
                    lap_number=self.current_lap_number,
                    split_time_seconds=split_time,
                    stroke_count=strokes,
                    stroke_rate=point.stroke_rate,
                    dps=dps,
                    breakout_distance_m=breakout,
                )
                self.completed_laps.append(final_lap)

                rep_start = self.current_rep_start_time or self.state_entered_time
                total_rep_time = round(max(0.1, finish_time - rep_start), 2)
                total_distance = self.pool_length * len(self.completed_laps)
                effort_pct = calculate_effort_percentage(
                    total_rep_time,
                    total_distance,
                    self.pb_time_seconds,
                    self.threshold_velocity_mps,
                )

                rep_metrics = RepetitionMetrics(
                    rep_number=self.current_rep_number,
                    set_number=self.current_set_number,
                    total_time_seconds=total_rep_time,
                    rest_time_seconds=self.last_rest_duration,
                    effort_percentage=effort_pct,
                    splits=list(self.completed_laps),
                )
                self.latest_repetition_metrics = rep_metrics
                self.last_rep_finish_time = finish_time
                details["repetition_metrics"] = rep_metrics.to_dict()

            event = StateTransitionEvent(
                swimmer_id=self.swimmer_id,
                previous_state=self.current_state,
                new_state=new_state,
                timestamp=now,
                telemetry_point=point,
                details=details,
            )
            self.current_state = new_state
            self.state_entered_time = now
            self.confirmed_push_off_time = None
            self.confirmed_finish_time = None
            return event

        return None

    def _evaluate_next_state(self, point: TelemetryPoint) -> SwimmerState:
        if self.is_outside_pool_boundary(point.x, point.y):
            self.candidate_push_off_time = None
            self.candidate_push_off_point = None
            self.wall_idle_start_time = None
            return SwimmerState.OUTSIDE_POOL

        if self.current_state == SwimmerState.OUTSIDE_POOL:
            if not self.is_outside_pool_boundary(point.x, point.y):
                if self.is_in_wall_zone(point.x, enter=True):
                    return SwimmerState.IDLE_AT_WALL
                return SwimmerState.SWIMMING

        elif self.current_state == SwimmerState.IDLE_AT_WALL:
            if self.candidate_push_off_time is None:
                if self.is_in_wall_zone(point.x, enter=False):
                    if self.is_push_off_impulse(point):
                        self.candidate_push_off_time = point.timestamp
                        self.candidate_push_off_point = point
                else:
                    if point.speed > 0.8:
                        return SwimmerState.SWIMMING
            else:
                if point.speed <= 0.8:
                    self.candidate_push_off_time = None
                    self.candidate_push_off_point = None
                else:
                    duration = point.timestamp - self.candidate_push_off_time
                    if duration >= 2.0:
                        self.confirmed_push_off_time = self.candidate_push_off_time
                        self.candidate_push_off_time = None
                        self.candidate_push_off_point = None
                        return SwimmerState.SWIMMING

        elif self.current_state == SwimmerState.SWIMMING:
            approaching_wall = self.is_in_wall_zone(point.x, enter=True)
            high_rotation = abs(point.gyro_pitch) > 60.0 or abs(point.gyro_roll) > 60.0

            if approaching_wall and (high_rotation or point.phase == "TURN"):
                self.wall_idle_start_time = None
                return SwimmerState.TURN_TRANSITION

            if approaching_wall and point.speed <= (self.finish_speed_threshold_mps + 0.15):
                if self.wall_idle_start_time is None:
                    self.wall_idle_start_time = point.timestamp
                else:
                    dwell = point.timestamp - self.wall_idle_start_time
                    if dwell >= self.idle_confirmation_threshold_sec:
                        self.confirmed_finish_time = self.backtrack_finish_timestamp()
                        self.wall_idle_start_time = None
                        return SwimmerState.IDLE_AT_WALL
            else:
                if point.speed > 0.6 or not approaching_wall:
                    self.wall_idle_start_time = None

        elif self.current_state == SwimmerState.TURN_TRANSITION:
            if not self.is_in_wall_zone(point.x, enter=False) and point.speed > 0.8:
                return SwimmerState.SWIMMING

            if self.is_in_wall_zone(point.x, enter=True) and point.speed < 0.2:
                dwell = point.timestamp - self.state_entered_time
                if dwell > 2.5:
                    self.confirmed_finish_time = self.backtrack_finish_timestamp()
                    return SwimmerState.IDLE_AT_WALL

        return self.current_state


class SessionStateMachineManager:
    """Manages independent SwimmerStateMachine instances for all active swimmers in a session."""

    def __init__(
        self,
        session_id: str,
        pool_length: float = 25.0,
        pb_map: Optional[dict[str, float]] = None,
        threshold_velocity_mps: float = 1.30,
    ):
        self.session_id = session_id
        self.pool_length = pool_length
        self.pb_map = pb_map or {}
        self.threshold_velocity_mps = threshold_velocity_mps
        self.swimmers: dict[str, SwimmerStateMachine] = {}

    def get_or_create(self, swimmer_id: str) -> SwimmerStateMachine:
        sid = str(swimmer_id)
        if sid not in self.swimmers:
            pb = self.pb_map.get(sid)
            self.swimmers[sid] = SwimmerStateMachine(
                swimmer_id=sid,
                pool_length=self.pool_length,
                pb_time_seconds=pb,
                threshold_velocity_mps=self.threshold_velocity_mps,
            )
        return self.swimmers[sid]

    def process_packet(self, packet_data: dict[str, Any]) -> Optional[StateTransitionEvent]:
        sid = str(packet_data.get("swimmer_id") or packet_data.get("tag_id") or "1")
        sm = self.get_or_create(sid)
        return sm.update(packet_data)

    def reset(self):
        self.swimmers.clear()


_SESSION_STATE_MACHINES: dict[str, SessionStateMachineManager] = {}


def get_session_state_machine(session_id: str, pool_length: float = 25.0) -> SessionStateMachineManager:
    if session_id not in _SESSION_STATE_MACHINES:
        _SESSION_STATE_MACHINES[session_id] = SessionStateMachineManager(
            session_id=session_id,
            pool_length=pool_length,
        )
    return _SESSION_STATE_MACHINES[session_id]


def reset_session_state_machine(session_id: str):
    _SESSION_STATE_MACHINES.pop(session_id, None)