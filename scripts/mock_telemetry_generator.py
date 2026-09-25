"""
Standalone Mock Telemetry Generator for Pool Deck Time Tracker.
Simulates 1 to 50 competitive swimmers streaming realistic IMU and spatial
telemetry packets to the Django Channels ASGI server over WebSockets.
"""

import argparse
import asyncio
import json
import math
import random
import time
import websockets


class SwimmerSim:
    """Simulates realistic 1D/2D pool kinematics and IMU dynamics for one swimmer."""

    def __init__(self, swimmer_id: int, lane: int, pool_length: float = 25.0):
        self.swimmer_id = swimmer_id
        self.tag_id = f"TAG_{swimmer_id:02d}"
        self.lane = lane
        self.pool_length = pool_length

        # Kinematic state
        self.x = 0.5 + random.uniform(0.0, 1.5)  # Start near wall
        self.lane_center_y = (lane - 1) * 2.5 + 1.25
        self.y = self.lane_center_y
        self.direction = 1  # +1 = swimming towards far wall, -1 = swimming back
        self.lap_number = 1
        self.stroke_count = 0
        self.sequence_id = 0

        # Baseline performance traits
        self.target_speed = random.uniform(1.30, 1.65)  # m/s
        self.current_speed = self.target_speed
        self.cadence_hz = random.uniform(0.55, 0.70)   # ~33-42 strokes/min

        # Phase tracking: 'PUSH_OFF', 'SURFACE_SWIM', 'TURN', 'REST'
        self.phase = 'SURFACE_SWIM'
        self.phase_timer = 0.0

    def update(self, dt: float) -> dict:
        self.sequence_id += 1
        now = time.time()
        self.phase_timer += dt

        # Update position along lane
        distance_step = self.direction * self.current_speed * dt
        self.x += distance_step

        # Turn / wall boundary logic
        if self.direction == 1 and self.x >= (self.pool_length - 0.8):
            # Hit far wall -> turn
            self.x = self.pool_length - 0.8
            self.direction = -1
            self.lap_number += 1
            self.phase = 'TURN'
            self.phase_timer = 0.0
            self.current_speed = 0.6
        elif self.direction == -1 and self.x <= 0.8:
            # Hit near wall -> turn
            self.x = 0.8
            self.direction = 1
            self.lap_number += 1
            self.phase = 'TURN'
            self.phase_timer = 0.0
            self.current_speed = 0.6

        # Phase transitions & IMU signal synthesis
        if self.phase == 'TURN':
            if self.phase_timer > 1.2:
                self.phase = 'PUSH_OFF'
                self.phase_timer = 0.0
                self.current_speed = self.target_speed * 1.4  # Push-off speed boost
            accel_x = random.uniform(1.8, 2.8) * self.direction
            accel_y = random.uniform(-0.4, 0.4)
            accel_z = random.uniform(0.2, 0.8)
            gyro_roll = random.uniform(80.0, 140.0)  # Flip-turn roll
            gyro_pitch = random.uniform(100.0, 160.0) # Somersault pitch
            gyro_yaw = random.uniform(-20.0, 20.0)
            stroke_rate = 0.0

        elif self.phase == 'PUSH_OFF':
            if self.phase_timer > 2.0:
                self.phase = 'SURFACE_SWIM'
                self.phase_timer = 0.0
                self.current_speed = self.target_speed
            accel_x = random.uniform(0.9, 1.5) * self.direction
            accel_y = random.uniform(-0.1, 0.1)
            accel_z = 0.98  # Normal gravity
            gyro_roll = random.uniform(-5.0, 5.0)
            gyro_pitch = random.uniform(-5.0, 5.0)
            gyro_yaw = random.uniform(-2.0, 2.0)
            stroke_rate = 0.0

        else:  # SURFACE_SWIM
            # Rolling arm pull oscillation
            roll_osc = math.sin(2 * math.pi * self.cadence_hz * now)
            gyro_roll = roll_osc * 45.0  # Body rolls +/- 45 deg per stroke
            gyro_pitch = math.cos(2 * math.pi * self.cadence_hz * now) * 12.0
            gyro_yaw = math.sin(math.pi * self.cadence_hz * now) * 8.0

            # Forward acceleration fluctuation per stroke pull
            accel_x = (0.98 + math.sin(4 * math.pi * self.cadence_hz * now) * 0.35) * self.direction
            accel_y = roll_osc * 0.25
            accel_z = 0.98 + random.uniform(-0.05, 0.05)

            stroke_rate = round(self.cadence_hz * 60.0, 1)

            # Accumulate stroke count on cycle peaks
            if math.isclose(roll_osc, 1.0, abs_tol=0.08):
                self.stroke_count += 1

            # Slight lateral sway within lane
            self.y = self.lane_center_y + math.sin(0.5 * now) * 0.2

        # Clamp x to pool bounds
        self.x = max(0.0, min(self.pool_length, self.x))

        return {
            "type": "telemetry_packet",
            "data": {
                "swimmer_id": self.swimmer_id,
                "tag_id": self.tag_id,
                "lane": self.lane,
                "sequence_id": self.sequence_id,
                "timestamp": round(now, 4),
                "phase": self.phase,
                "x_m": round(self.x, 2),
                "y_m": round(self.y, 2),
                "speed_mps": round(self.current_speed, 2),
                "lap_number": self.lap_number,
                "stroke_count": self.stroke_count,
                "stroke_rate_spm": stroke_rate,
                "accel": {
                    "x": round(accel_x, 3),
                    "y": round(accel_y, 3),
                    "z": round(accel_z, 3),
                },
                "gyro": {
                    "roll": round(gyro_roll, 2),
                    "pitch": round(gyro_pitch, 2),
                    "yaw": round(gyro_yaw, 2),
                },
            },
        }


async def run_simulation(url: str, swimmer_count: int, rate_hz: float, duration_sec: float, pool_length: float):
    dt = 1.0 / rate_hz
    print(f"[Sim] Connecting to WebSocket endpoint: {url}")
    print(f"[Sim] Simulating {swimmer_count} active swimmers at {rate_hz} Hz ({swimmer_count * rate_hz:.0f} packets/sec)")

    swimmers = []
    for i in range(1, swimmer_count + 1):
        lane = ((i - 1) % 8) + 1  # Distribute evenly across 8 pool lanes
        swimmers.append(SwimmerSim(swimmer_id=i, lane=lane, pool_length=pool_length))

    async with websockets.connect(url) as ws:
        print("[Sim] Connected successfully. Streaming telemetry packets...")
        start_time = time.time()
        packets_sent = 0

        try:
            while True:
                loop_start = time.time()

                for swimmer in swimmers:
                    packet = swimmer.update(dt)
                    await ws.send(json.dumps(packet))
                    packets_sent += 1

                elapsed = time.time() - start_time
                if duration_sec > 0 and elapsed >= duration_sec:
                    print(f"[Sim] Completed scheduled duration of {duration_sec}s.")
                    break

                # Sleep to maintain requested tick rate
                computation_time = time.time() - loop_start
                sleep_time = max(0.0, dt - computation_time)
                await asyncio.sleep(sleep_time)

        except (asyncio.CancelledError, KeyboardInterrupt):
            print("\n[Sim] Simulation interrupted by user.")
        finally:
            total_elapsed = time.time() - start_time
            print(f"[Sim] Transmitted {packets_sent} packets over {total_elapsed:.1f}s ({packets_sent / total_elapsed:.1f} packets/sec).")


def main():
    parser = argparse.ArgumentParser(description="Mock Swimmer Telemetry Generator")
    parser.add_argument("--url", type=str, default="ws://127.0.0.1:8000/ws/pool/1/", help="Target WebSocket URL")
    parser.add_argument("--swimmers", type=int, default=4, help="Number of swimmers to simulate (1 to 50)")
    parser.add_argument("--rate", type=float, default=10.0, help="Sampling rate in Hz per swimmer (default: 10.0)")
    parser.add_argument("--duration", type=float, default=30.0, help="Test run duration in seconds (0 = infinite)")
    parser.add_argument("--pool-length", type=float, default=25.0, help="Pool length in meters (default: 25.0)")

    args = parser.parse_args()

    asyncio.run(
        run_simulation(
            url=args.url,
            swimmer_count=args.swimmers,
            rate_hz=args.rate,
            duration_sec=args.duration,
            pool_length=args.pool_length,
        )
    )


if __name__ == "__main__":
    main()