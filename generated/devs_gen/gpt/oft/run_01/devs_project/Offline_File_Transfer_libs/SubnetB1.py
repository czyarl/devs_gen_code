from __future__ import annotations

from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetB1(Atomic):
    """
    Reliable, lossless, in-order (FIFO) point-to-point link with fixed propagation delay.

    Transports download data packets from Server boundary to Receiver.
    Packets are dicts exactly of the form: {'seq': int, 'bit': int}.
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(packet: object) -> bool:
        if not isinstance(packet, dict):
            return False
        if set(packet.keys()) != {"seq", "bit"}:
            return False
        if not isinstance(packet.get("seq"), int):
            return False
        if not isinstance(packet.get("bit"), int):
            return False
        return True

    def _start_next_delivery(self) -> None:
        # Precondition: queue non-empty and no active delivery timer.
        self._in_flight = self._queue.popleft()
        self.hold_in("DELIVER", self.delay_ms)

    def deltext(self, e: float):
        # Preserve remaining time if a delivery timer is already pending.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        was_empty = len(self._queue) == 0 and self._in_flight is None

        for packet in self.input["data_in"].values:
            if self._is_valid_packet(packet):
                # Forward unchanged; store the same dict object (no modification).
                self._queue.append(packet)

        if was_delivering:
            self.hold_in("DELIVER", remaining)
        else:
            if was_empty and self._queue:
                self._start_next_delivery()
            # else remain passive (IDLE) with no scheduled event

    def lambdaf(self):
        if self.phase == "DELIVER" and self._in_flight is not None:
            self.output["data_out"].add(self._in_flight)

    def deltint(self):
        # After delivering one packet, either schedule next or go idle.
        self._in_flight = None
        if self._queue:
            self._start_next_delivery()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass