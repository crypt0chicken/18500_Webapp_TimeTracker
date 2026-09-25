import time
from typing import Any, Optional


class StreamJitterBuffer:
    """
    Manages packet sequencing and out-of-order reassembly for a single telemetry stream.
    - In-order packets are emitted with zero latency.
    - Out-of-order packets are buffered until missing sequences arrive or max_delay expires.
    - Duplicate or stale packets are discarded.
    """

    def __init__(self, stream_id: str, max_delay: float = 0.15, max_buffer_size: int = 128):
        self.stream_id = stream_id
        self.max_delay = max_delay
        self.max_buffer_size = max_buffer_size

        self.expected_seq: Optional[int] = None
        self.last_emitted_seq: Optional[int] = None
        # buffer maps sequence_id -> (packet_data, arrival_time)
        self.buffer: dict[int, tuple[dict[str, Any], float]] = {}

    def push(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Ingest a packet and return any packets ready for immediate in-order release.
        """
        # Look for sequence_id in packet or nested data dict
        seq = packet.get("sequence_id")
        if seq is None and "data" in packet and isinstance(packet["data"], dict):
            seq = packet["data"].get("sequence_id")

        if seq is None:
            # Unsequenced packet: release immediately
            return [packet]

        now = time.time()

        # Handle stream initialization
        if self.expected_seq is None:
            self.expected_seq = seq + 1
            self.last_emitted_seq = seq
            return [packet]

        # Handle counter reboot/reset (e.g. microcontroller restarted sequence at 1)
        if (self.expected_seq - seq) > 1000:
            self.buffer.clear()
            self.expected_seq = seq + 1
            self.last_emitted_seq = seq
            return [packet]

        # Duplicate or stale packet: discard
        if seq < self.expected_seq:
            return []

        # In-order packet arrived
        if seq == self.expected_seq:
            ready = [packet]
            self.last_emitted_seq = seq
            self.expected_seq = seq + 1

            # Drain contiguous subsequent sequences already waiting in buffer
            while self.expected_seq in self.buffer:
                next_pkt, _ = self.buffer.pop(self.expected_seq)
                ready.append(next_pkt)
                self.last_emitted_seq = self.expected_seq
                self.expected_seq += 1

            return ready

        # Out-of-order packet (seq > expected_seq): buffer it
        if seq not in self.buffer:
            # Enforce max buffer size to prevent memory leaks
            if len(self.buffer) >= self.max_buffer_size:
                # Force release oldest buffered packet
                oldest_seq = min(self.buffer.keys())
                oldest_pkt, _ = self.buffer.pop(oldest_seq)
                self.expected_seq = oldest_seq + 1
                self.last_emitted_seq = oldest_seq
                self.buffer[seq] = (packet, now)
                return [oldest_pkt]

            self.buffer[seq] = (packet, now)

        return []

    def flush_expired(self, now: Optional[float] = None) -> list[dict[str, Any]]:
        """
        Check for buffered packets whose wait window has exceeded max_delay.
        Advances expected_seq past dropped packets and drains contiguous ready packets.
        """
        if not self.buffer:
            return []

        if now is None:
            now = time.time()

        ready: list[dict[str, Any]] = []

        while self.buffer:
            min_seq = min(self.buffer.keys())
            pkt, arrival_time = self.buffer[min_seq]

            if (now - arrival_time) >= self.max_delay:
                # Timeout expired waiting for missing sequences before min_seq
                self.buffer.pop(min_seq)
                ready.append(pkt)
                self.last_emitted_seq = min_seq
                self.expected_seq = min_seq + 1

                # Drain contiguous packets that followed
                while self.expected_seq in self.buffer:
                    next_pkt, _ = self.buffer.pop(self.expected_seq)
                    ready.append(next_pkt)
                    self.last_emitted_seq = self.expected_seq
                    self.expected_seq += 1
            else:
                # Oldest buffered packet hasn't timed out yet
                break

        return ready


class SessionJitterBuffer:
    """
    Coordinates jitter buffers across multiple concurrent swimmer streams within a practice session.
    """

    def __init__(self, max_delay: float = 0.15, max_buffer_per_stream: int = 128):
        self.max_delay = max_delay
        self.max_buffer_per_stream = max_buffer_per_stream
        self.streams: dict[str, StreamJitterBuffer] = {}

    def _get_stream_id(self, packet: dict[str, Any]) -> str:
        data = packet.get("data", packet) if isinstance(packet.get("data"), dict) else packet
        stream_id = data.get("swimmer_id") or data.get("tag_id") or "default"
        return str(stream_id)

    def push(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        stream_id = self._get_stream_id(packet)
        if stream_id not in self.streams:
            self.streams[stream_id] = StreamJitterBuffer(
                stream_id=stream_id,
                max_delay=self.max_delay,
                max_buffer_size=self.max_buffer_per_stream,
            )
        return self.streams[stream_id].push(packet)

    def flush_expired(self, now: Optional[float] = None) -> list[dict[str, Any]]:
        if now is None:
            now = time.time()
        ready = []
        for stream in self.streams.values():
            ready.extend(stream.flush_expired(now))
        return ready

    def clear(self):
        self.streams.clear()


_SESSION_BUFFERS: dict[str, SessionJitterBuffer] = {}


def get_session_jitter_buffer(session_id: str, max_delay: float = 0.15) -> SessionJitterBuffer:
    if session_id not in _SESSION_BUFFERS:
        _SESSION_BUFFERS[session_id] = SessionJitterBuffer(max_delay=max_delay)
    return _SESSION_BUFFERS[session_id]


def reset_session_jitter_buffer(session_id: str):
    _SESSION_BUFFERS.pop(session_id, None)