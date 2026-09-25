import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from .jitter_buffer import get_session_jitter_buffer


class PoolTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f"pool_{self.session_id}"
        self.jitter_buffer = get_session_jitter_buffer(self.session_id)

        # Join the practice session room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        # Background task to flush timed-out out-of-order packets
        self.flush_task = asyncio.create_task(self._flush_loop())

    async def disconnect(self, close_code):
        # Cancel background flush task
        if hasattr(self, 'flush_task') and not self.flush_task.done():
            self.flush_task.cancel()

        # Leave the practice session group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON format"}))
            return

        message_type = payload.get("type", "telemetry_packet")

        if message_type == "telemetry_packet":
            packet_data = payload.get("data", payload)
            ready_packets = self.jitter_buffer.push(packet_data)

            # Also release any buffered packets that expired
            ready_packets.extend(self.jitter_buffer.flush_expired())

            for packet in ready_packets:
                await self._broadcast_packet("telemetry_packet", packet)
        else:
            # Control, ping, or unsequenced messages bypass the jitter buffer
            await self._broadcast_packet(message_type, payload.get("data", payload))

    async def _broadcast_packet(self, message_type: str, data: dict):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "telemetry_broadcast",
                "message_type": message_type,
                "data": data,
            },
        )

    async def _flush_loop(self):
        """Periodically flushes packets that have exceeded max_delay in the jitter buffer."""
        try:
            while True:
                await asyncio.sleep(0.05)
                expired_packets = self.jitter_buffer.flush_expired()
                for packet in expired_packets:
                    await self._broadcast_packet("telemetry_packet", packet)
        except asyncio.CancelledError:
            pass

    async def telemetry_broadcast(self, event):
        await self.send(text_data=json.dumps({
            "type": event["message_type"],
            "data": event["data"],
        }))