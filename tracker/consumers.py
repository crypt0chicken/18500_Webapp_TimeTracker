import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from .jitter_buffer import get_session_jitter_buffer
from .persistence import persist_completed_repetition
from .state_machine import get_session_state_machine


class PoolTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f"pool_{self.session_id}"
        self.jitter_buffer = get_session_jitter_buffer(self.session_id)
        self.state_machine = get_session_state_machine(self.session_id)

        # Join the practice session room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        # Background task to flush timed-out out-of-order packets
        self.flush_task = asyncio.create_task(self._flush_loop())

    async def disconnect(self, close_code):
        if hasattr(self, 'flush_task') and not self.flush_task.done():
            self.flush_task.cancel()

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
            ready_packets.extend(self.jitter_buffer.flush_expired())

            for packet in ready_packets:
                # 1. Broadcast live high-frequency packet (in Redis/Channels only)
                await self._broadcast_packet("telemetry_packet", packet)

                # 2. Evaluate state transitions and metric extraction
                event = self.state_machine.process_packet(packet)
                if event:
                    await self._handle_state_transition_event(event)
        else:
            await self._broadcast_packet(message_type, payload.get("data", payload))

    async def _handle_state_transition_event(self, event):
        """Processes state transitions, broadcasts notifications, and triggers persistence."""
        event_payload = {
            "swimmer_id": event.swimmer_id,
            "previous_state": event.previous_state.value,
            "new_state": event.new_state.value,
            "timestamp": event.timestamp,
            "details": event.details,
        }
        await self._broadcast_packet("state_transition", event_payload)

        # Event-driven database persistence for completed repetitions
        rep_metrics = event.details.get("repetition_metrics")
        if rep_metrics:
            saved_rep = await persist_completed_repetition(
                session_id=self.session_id,
                swimmer_identifier=event.swimmer_id,
                rep_metrics=rep_metrics,
            )
            if saved_rep:
                await self._broadcast_packet("repetition_persisted", {
                    "swimmer_id": event.swimmer_id,
                    "repetition_id": saved_rep.id,
                    "rep_number": saved_rep.rep_number,
                    "total_time_seconds": saved_rep.total_time_seconds,
                    "splits_saved": len(rep_metrics.get("splits", [])),
                })

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
        try:
            while True:
                await asyncio.sleep(0.05)
                expired_packets = self.jitter_buffer.flush_expired()
                for packet in expired_packets:
                    await self._broadcast_packet("telemetry_packet", packet)
                    event = self.state_machine.process_packet(packet)
                    if event:
                        await self._handle_state_transition_event(event)
        except asyncio.CancelledError:
            pass

    async def telemetry_broadcast(self, event):
        await self.send(text_data=json.dumps({
            "type": event["message_type"],
            "data": event["data"],
        }))