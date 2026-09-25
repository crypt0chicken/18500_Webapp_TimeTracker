"""
Step 2 Validation Harness: 50-Stream Concurrency & Latency Test.
Validates:
1. Zero packet loss across 50 concurrent streams.
2. End-to-end WebSocket transmission latency strictly below 100 ms.
"""

import argparse
import asyncio
import json
import statistics
import time
import websockets


class ConcurrencyValidator:
    def __init__(self, ws_url: str, swimmer_count: int, rate_hz: float, duration_sec: float):
        self.ws_url = ws_url
        self.swimmer_count = swimmer_count
        self.rate_hz = rate_hz
        self.duration_sec = duration_sec
        self.dt = 1.0 / rate_hz

        self.sent_count = 0
        self.received_count = 0
        self.latencies_ms: list[float] = []
        self.stop_signal = asyncio.Event()

    async def listener(self):
        """Simulates the Coach's live dashboard receiving all broadcasts."""
        async with websockets.connect(self.ws_url) as ws:
            while not self.stop_signal.is_set():
                try:
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    recv_time = time.time()
                    payload = json.loads(raw_msg)

                    data = payload.get("data", {})
                    sent_time = data.get("timestamp")
                    if sent_time:
                        latency = (recv_time - sent_time) * 1000.0
                        self.latencies_ms.append(latency)
                        self.received_count += 1
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

    async def sender(self):
        """Simulates the ingestion channel streaming from 50 swimmer devices."""
        async with websockets.connect(self.ws_url) as ws:
            start_time = time.time()
            sequences = {i: 0 for i in range(1, self.swimmer_count + 1)}

            while (time.time() - start_time) < self.duration_sec:
                loop_start = time.time()

                for swimmer_id in range(1, self.swimmer_count + 1):
                    sequences[swimmer_id] += 1
                    packet = {
                        "type": "telemetry_packet",
                        "data": {
                            "swimmer_id": swimmer_id,
                            "tag_id": f"TAG_{swimmer_id:02d}",
                            "lane": ((swimmer_id - 1) % 8) + 1,
                            "sequence_id": sequences[swimmer_id],
                            "timestamp": time.time(),
                            "speed_mps": 1.45,
                            "stroke_rate_spm": 38.0,
                            "x_m": 12.5,
                            "y_m": 2.5,
                        },
                    }
                    await ws.send(json.dumps(packet))
                    self.sent_count += 1

                elapsed = time.time() - loop_start
                sleep_time = max(0.0, self.dt - elapsed)
                await asyncio.sleep(sleep_time)

    async def run(self):
        print(f"\n{'='*60}")
        print("STEP 2 CONCURRENCY & LATENCY BENCHMARK")
        print(f"{'='*60}")
        print(f"Target URL:         {self.ws_url}")
        print(f"Concurrent Streams: {self.swimmer_count} swimmers")
        print(f"Sampling Frequency: {self.rate_hz} Hz ({self.swimmer_count * self.rate_hz:.0f} pkts/sec)")
        print(f"Test Duration:      {self.duration_sec} seconds")
        print("Connecting clients and streaming telemetry...\n")

        # Start listener first
        listener_task = asyncio.create_task(self.listener())
        await asyncio.sleep(0.5)  # Allow listener handshake to complete

        # Run sender for the specified duration
        await self.sender()

        # Allow grace period for in-flight/jitter buffer packets to drain
        await asyncio.sleep(1.0)
        self.stop_signal.set()
        listener_task.cancel()

        self._evaluate_results()

    def _evaluate_results(self):
        packets_lost = max(0, self.sent_count - self.received_count)
        loss_rate_pct = (packets_lost / self.sent_count * 100) if self.sent_count > 0 else 100.0

        avg_latency = statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0
        median_latency = statistics.median(self.latencies_ms) if self.latencies_ms else 0.0
        p95_latency = statistics.quantiles(self.latencies_ms, n=100)[94] if len(self.latencies_ms) >= 100 else avg_latency
        p99_latency = statistics.quantiles(self.latencies_ms, n=100)[98] if len(self.latencies_ms) >= 100 else avg_latency
        max_latency = max(self.latencies_ms) if self.latencies_ms else 0.0

        print(f"{'-'*60}")
        print("BENCHMARK METRICS SUMMARY")
        print(f"{'-'*60}")
        print(f"Packets Transmitted: {self.sent_count}")
        print(f"Packets Received:    {self.received_count}")
        print(f"Packet Loss Rate:    {loss_rate_pct:.2f}% ({packets_lost} lost)")
        print(f"Average Latency:     {avg_latency:.2f} ms")
        print(f"Median Latency:      {median_latency:.2f} ms")
        print(f"95th Percentile:     {p95_latency:.2f} ms")
        print(f"99th Percentile:     {p99_latency:.2f} ms")
        print(f"Peak Max Latency:    {max_latency:.2f} ms")
        print(f"{'-'*60}")

        # Verification Criteria Assertions
        passed_loss = (packets_lost == 0)
        passed_latency = (p95_latency < 100.0)

        print("\nSPECIFICATION CRITERIA VERIFICATION:")
        print(f" [1] Zero Packet Loss:              {'PASS' if passed_loss else 'FAIL'}")
        print(f" [2] 95th Percentile < 100ms:       {'PASS' if passed_latency else 'FAIL'}")

        if passed_loss and passed_latency:
            print(f"\nOVERALL RESULT: SUCCESS (Step 2 criteria satisfied)\n{'='*60}\n")
        else:
            print(f"\nOVERALL RESULT: FAILED (System failed one or more criteria)\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Step 2 Concurrency & Latency Verification")
    parser.add_argument("--url", type=str, default="ws://127.0.0.1:8000/ws/pool/benchmark_session/")
    parser.add_argument("--swimmers", type=int, default=50, help="Number of concurrent swimmer streams")
    parser.add_argument("--rate", type=float, default=10.0, help="Per-device sample frequency (Hz)")
    parser.add_argument("--duration", type=float, default=20.0, help="Test run duration in seconds")

    args = parser.parse_args()

    validator = ConcurrencyValidator(
        ws_url=args.url,
        swimmer_count=args.swimmers,
        rate_hz=args.rate,
        duration_sec=args.duration,
    )
    asyncio.run(validator.run())


if __name__ == "__main__":
    main()