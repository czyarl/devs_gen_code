#!/usr/bin/env python3
# run.py
import argparse
import sys
import json
import logging
from collections import deque
import math

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Logging helpers (JSONL stdout)
# -----------------------------
def _jsonl_emit(timestamp_ms: float, model: str, etype: str, val: dict):
    obj = {
        "timestamp_ms": float(timestamp_ms),
        "model": str(model),
        "type": str(etype),
        "val": val if isinstance(val, dict) else {"value": val},
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


class LoggingAtomic(Atomic):
    """
    Adds local time tracking for logging. This does NOT drive simulation time;
    it's only to stamp events consistently.
    """
    def __init__(self, name: str):
        super().__init__(name)
        self._t = 0.0  # last transition time for this model

    def _advance_ext(self, e: float) -> float:
        self._t += float(e)
        return self._t

    def _advance_int(self) -> float:
        # internal event occurs at current local time + sigma
        self._t += float(self.sigma)
        return self._t

    def _now_int(self) -> float:
        return float(self._t + float(self.sigma))

    def _now(self) -> float:
        return float(self._t)

    @staticmethod
    def _rem_sigma(old_sigma: float, e: float) -> float:
        if old_sigma is None:
            return float("inf")
        if math.isinf(old_sigma):
            return float("inf")
        return max(0.0, float(old_sigma) - float(e))

    def _emit(self, etype: str, val: dict, timestamp_ms: float | None = None, model: str | None = None):
        _jsonl_emit(self._now() if timestamp_ms is None else timestamp_ms,
                    self.name if model is None else model,
                    etype,
                    val)


# -----------------------------
# Messages
# -----------------------------
def make_data(seq: int, bit: int) -> dict:
    return {"kind": "DATA", "seq": int(seq), "bit": int(bit)}


def make_ack(bit: int) -> dict:
    return {"kind": "ACK", "bit": int(bit)}


# -----------------------------
# Atomic models
# -----------------------------
class InputDriver(LoggingAtomic):
    """
    Emits control/request commands at scheduled simulation times.
    """
    def __init__(self, name: str, parent: Coupled | None, schedule: list[tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "out_control"))
        self.add_out_port(Port(dict, "out_request"))

        self._schedule = list(schedule)
        self._idx = 0
        self._pending = []  # list of ("control"/"request", payload)
        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._t = 0.0
        self._idx = 0
        self._pending = []
        if self._schedule:
            self.hold_in("WAIT", max(0.0, float(self._schedule[0][0])))
        else:
            self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        # At the scheduled time, output all commands due at this exact timestamp
        for typ, payload in self._pending:
            if typ == "control":
                self.output["out_control"].add(payload)
            elif typ == "request":
                self.output["out_request"].add(payload)

    def deltint(self):
        t = self._advance_int()
        self._pending = []

        # collect all events at exactly current time t
        while self._idx < len(self._schedule) and float(self._schedule[self._idx][0]) <= t + 1e-9:
            ts, typ, val = self._schedule[self._idx]
            if typ == "control":
                self._pending.append(("control", {"added": int(val)}))
            elif typ == "request":
                self._pending.append(("request", {"allowed": bool(int(val))}))
            self._idx += 1

        # if we have pending outputs, schedule immediate SEND, else wait to next timestamp
        if self._pending:
            self.hold_in("SEND", 0.0)
            return

        if self._idx < len(self._schedule):
            next_ts = float(self._schedule[self._idx][0])
            self.hold_in("WAIT", max(0.0, next_ts - t))
        else:
            self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        # No inputs
        self._advance_ext(e)
        self.hold_in(self.phase, self._rem_sigma(self.sigma, e))

    def exit(self):
        pass


class DelayFIFO(LoggingAtomic):
    """
    Reliable, FIFO, fixed delay channel.
    """
    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

        self._q = deque()  # (deliver_time, msg)
        self._out_msg = None
        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        self._t = 0.0
        self._q.clear()
        self._out_msg = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        if self._out_msg is not None:
            self.output["out"].add(self._out_msg)

    def _reschedule(self, now: float):
        if not self._q:
            self._out_msg = None
            self.hold_in("IDLE", float("inf"))
            return
        deliver_t, msg = self._q[0]
        self._out_msg = msg
        self.hold_in("DELIVER", max(0.0, float(deliver_t) - float(now)))

    def deltint(self):
        now = self._advance_int()
        if self._q:
            self._q.popleft()
        self._reschedule(now)

    def deltext(self, e):
        now = self._advance_ext(e)
        for msg in list(self.input["in"].values):
            self._q.append((now + self.delay_ms, msg))
        self._reschedule(now)

    def exit(self):
        pass


class Sender(LoggingAtomic):
    """
    Uploader with ABP (alternating bit). Preparation delay before each new packet.
    """
    PREP_MS = 10000.0
    TIMEOUT_MS = 20000.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_control"))
        self.add_in_port(Port(dict, "in_ack"))
        self.add_out_port(Port(dict, "out_data"))

        # state
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.waiting_for_ack = False
        self._send_retry = False
        self._pending_out = None

        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        self._t = 0.0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.waiting_for_ack = False
        self._send_retry = False
        self._pending_out = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        if self.phase == "SEND" and self._pending_out is not None:
            ts = self._now_int()
            pkt = self._pending_out
            self.output["out_data"].add(pkt)
            self._emit("packet_sent",
                       {"seq": int(pkt["seq"]), "bit": int(pkt["bit"]), "is_retry": bool(self._send_retry)},
                       timestamp_ms=ts,
                       model="sender")

    def _start_prepare(self, now: float):
        self._emit("preparation_started", {"duration": int(self.PREP_MS)}, timestamp_ms=now, model="sender")
        self.hold_in("PREPARE", self.PREP_MS)

    def deltint(self):
        now = self._advance_int()
        if self.phase == "PREPARE":
            # After preparation, send packet immediately
            self._send_retry = False
            self._pending_out = make_data(self.seq, self.bit)
            self.hold_in("SEND", 0.0)
            return

        if self.phase == "SEND":
            # After sending, wait for ACK with timeout
            self.waiting_for_ack = True
            self._pending_out = None
            self.hold_in("WAIT_ACK", self.TIMEOUT_MS)
            return

        if self.phase == "WAIT_ACK":
            # Timeout
            self._emit("timeout", {"seq": int(self.seq)}, timestamp_ms=now, model="sender")
            self._send_retry = True
            self._pending_out = make_data(self.seq, self.bit)
            self.hold_in("SEND", 0.0)
            return

        # IDLE or unknown
        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._advance_ext(e)

        # process control commands
        for cmd in list(self.input["in_control"].values):
            added = int(cmd.get("added", 0))
            if added > 0:
                self.packets_remaining += added
                self._emit("control_cmd",
                           {"added": added, "total_remaining": int(self.packets_remaining)},
                           timestamp_ms=now,
                           model="sender")

        # process ACKs
        for ack in list(self.input["in_ack"].values):
            if not isinstance(ack, dict) or ack.get("kind") != "ACK":
                continue
            ack_bit = int(ack.get("bit", -1))

            if self.waiting_for_ack and self.phase == "WAIT_ACK" and ack_bit == self.bit:
                self._emit("ack_received", {"bit": int(ack_bit)}, timestamp_ms=now, model="sender")
                self.waiting_for_ack = False
                # successful packet
                if self.packets_remaining > 0:
                    self.packets_remaining -= 1
                self.seq += 1
                self.bit = 1 - self.bit

                # next action
                if self.packets_remaining > 0:
                    self._start_prepare(now)
                else:
                    self.hold_in("IDLE", float("inf"))
                return

        # if idle and got work, start preparing
        if self.phase == "IDLE" and (self.packets_remaining > 0) and (not self.waiting_for_ack):
            self._start_prepare(now)
            return

        # otherwise, continue current phase with remaining sigma
        self.hold_in(self.phase, self._rem_sigma(self.sigma, e))

    def exit(self):
        pass


class ServerReceiver(LoggingAtomic):
    """
    Ingress at server: receives DATA from sender, processes 3s, ACKs, and stores accepted packets.
    """
    PROC_MS = 3000.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_data"))
        self.add_out_port(Port(dict, "out_ack"))
        self.add_out_port(Port(dict, "out_store"))

        self.expected_bit = 0
        self._q = deque()
        self._current = None
        self._pending_ack = None
        self._pending_store = None

        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        self._t = 0.0
        self.expected_bit = 0
        self._q.clear()
        self._current = None
        self._pending_ack = None
        self._pending_store = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        ts = self._now_int()
        if self.phase == "SEND_ACK":
            if self._pending_ack is not None:
                self.output["out_ack"].add(self._pending_ack)
                self._emit("ack_sent_to_sender",
                           {"bit": int(self._pending_ack["bit"])},
                           timestamp_ms=ts,
                           model="server_receiver")
            if self._pending_store is not None:
                self.output["out_store"].add(self._pending_store)

    def _start_processing_if_idle(self, now: float):
        if self._current is None and self._q:
            self._current = self._q.popleft()
            self.hold_in("PROCESS", self.PROC_MS)
        elif self._current is None and not self._q:
            self.hold_in("IDLE", float("inf"))
        else:
            # already processing
            self.hold_in(self.phase, self._rem_sigma(self.sigma, 0.0))

    def deltint(self):
        now = self._advance_int()

        if self.phase == "PROCESS":
            pkt = self._current
            self._current = None
            self._pending_ack = None
            self._pending_store = None

            if pkt is not None and pkt.get("kind") == "DATA":
                bit = int(pkt.get("bit", -1))
                if bit == self.expected_bit:
                    # accept
                    self._pending_ack = make_ack(bit)
                    self._pending_store = pkt
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # duplicate: ack previous bit
                    prev = 1 - self.expected_bit
                    self._pending_ack = make_ack(prev)
                    self._pending_store = None

            self.hold_in("SEND_ACK", 0.0)
            return

        if self.phase == "SEND_ACK":
            self._pending_ack = None
            self._pending_store = None
            # next packet if any
            self._start_processing_if_idle(now)
            return

        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._advance_ext(e)
        for pkt in list(self.input["in_data"].values):
            if isinstance(pkt, dict) and pkt.get("kind") == "DATA":
                self._emit("packet_received",
                           {"seq": int(pkt.get("seq", -1)), "bit": int(pkt.get("bit", -1))},
                           timestamp_ms=now,
                           model="server_receiver")
            self._q.append(pkt)

        # if idle, start processing
        if self.phase == "IDLE":
            self._start_processing_if_idle(now)
            return

        self.hold_in(self.phase, self._rem_sigma(self.sigma, e))

    def exit(self):
        pass


class ServerSender(LoggingAtomic):
    """
    Egress at server: ABP loop to receiver. Sends only when request allowed and storage non-empty.
    No timeout (reliable subnet assumed).
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_store"))
        self.add_in_port(Port(dict, "in_ack"))
        self.add_in_port(Port(dict, "in_request"))
        self.add_out_port(Port(dict, "out_data"))

        self.storage = deque()
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self._pending_out = None

        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        self._t = 0.0
        self.storage.clear()
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self._pending_out = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        if self.phase == "SEND" and self._pending_out is not None:
            ts = self._now_int()
            pkt = self._pending_out
            self.output["out_data"].add(pkt)
            self._emit("packet_forwarded",
                       {"seq": int(pkt.get("seq", -1)), "bit": int(pkt.get("bit", -1))},
                       timestamp_ms=ts,
                       model="server_sender")

    def _maybe_start_send(self):
        if (not self.waiting_for_ack) and self.download_allowed and self.storage:
            self.current_packet = self.storage.popleft()
            self._pending_out = self.current_packet
            self.hold_in("SEND", 0.0)
            return True
        return False

    def deltint(self):
        self._advance_int()
        if self.phase == "SEND":
            # After sending, wait for ACK (no timeout)
            self.waiting_for_ack = True
            self._pending_out = None
            self.hold_in("WAIT_ACK", float("inf"))
            return

        # IDLE / WAIT_ACK internal shouldn't happen (WAIT_ACK sigma=inf)
        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._advance_ext(e)

        # request valve changes
        for req in list(self.input["in_request"].values):
            allowed = bool(req.get("allowed", False))
            if allowed != self.download_allowed:
                self.download_allowed = allowed
                self._emit("download_valve_change", {"allowed": bool(self.download_allowed)}, timestamp_ms=now, model="server_sender")

        # new stored packets
        for pkt in list(self.input["in_store"].values):
            if isinstance(pkt, dict) and pkt.get("kind") == "DATA":
                self.storage.append(pkt)

        # ACK from receiver
        for ack in list(self.input["in_ack"].values):
            if not isinstance(ack, dict) or ack.get("kind") != "ACK":
                continue
            bit = int(ack.get("bit", -1))
            if self.waiting_for_ack and self.phase == "WAIT_ACK" and self.current_packet is not None:
                if bit == int(self.current_packet.get("bit", -2)):
                    self._emit("ack_received_from_receiver", {"bit": int(bit)}, timestamp_ms=now, model="server_sender")
                    self.waiting_for_ack = False
                    self.current_packet = None
                    # graceful stop: if download_allowed now False, stop after finishing this cycle
                    if self._maybe_start_send():
                        return
                    self.hold_in("IDLE", float("inf"))
                    return

        # If idle, and can send, do it
        if self.phase == "IDLE" and self._maybe_start_send():
            return

        # Otherwise continue current phase
        self.hold_in(self.phase, self._rem_sigma(self.sigma, e))

    def exit(self):
        pass


class Receiver(LoggingAtomic):
    """
    Downloader: processes 10s then ACKs.
    """
    PROC_MS = 10000.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_data"))
        self.add_out_port(Port(dict, "out_ack"))

        self._q = deque()
        self._current = None
        self._pending_ack = None

        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        self._t = 0.0
        self._q.clear()
        self._current = None
        self._pending_ack = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        if self.phase == "SEND_ACK" and self._pending_ack is not None:
            ts = self._now_int()
            self.output["out_ack"].add(self._pending_ack)
            self._emit("ack_sent",
                       {"bit": int(self._pending_ack["bit"])},
                       timestamp_ms=ts,
                       model="receiver")

    def _start_next(self, now: float):
        if self._current is None and self._q:
            self._current = self._q.popleft()
            if isinstance(self._current, dict) and self._current.get("kind") == "DATA":
                self._emit("processing_started",
                           {"seq": int(self._current.get("seq", -1)), "duration": int(self.PROC_MS)},
                           timestamp_ms=now,
                           model="receiver")
            self.hold_in("PROCESS", self.PROC_MS)
        elif self._current is None and not self._q:
            self.hold_in("IDLE", float("inf"))
        else:
            self.hold_in(self.phase, self._rem_sigma(self.sigma, 0.0))

    def deltint(self):
        now = self._advance_int()
        if self.phase == "PROCESS":
            pkt = self._current
            self._current = None
            if isinstance(pkt, dict) and pkt.get("kind") == "DATA":
                self._pending_ack = make_ack(int(pkt.get("bit", -1)))
            else:
                self._pending_ack = None
            self.hold_in("SEND_ACK", 0.0)
            return

        if self.phase == "SEND_ACK":
            self._pending_ack = None
            self._start_next(now)
            return

        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._advance_ext(e)
        for pkt in list(self.input["in_data"].values):
            self._q.append(pkt)

        if self.phase == "IDLE":
            self._start_next(now)
            return

        self.hold_in(self.phase, self._rem_sigma(self.sigma, e))

    def exit(self):
        pass


# -----------------------------
# Coupled system
# -----------------------------
class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule: list[tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent

        driver = InputDriver("driver", self, schedule)
        sender = Sender("sender", self)
        srv_rcv = ServerReceiver("server_receiver", self)
        srv_snd = ServerSender("server_sender", self)
        receiver = Receiver("receiver", self)

        # Subnets (3s each direction)
        A1 = DelayFIFO("subnetA1", self, 3000.0)  # Sender -> Server
        A2 = DelayFIFO("subnetA2", self, 3000.0)  # Server -> Sender (ACK)
        B1 = DelayFIFO("subnetB1", self, 3000.0)  # Server -> Receiver
        B2 = DelayFIFO("subnetB2", self, 3000.0)  # Receiver -> Server (ACK)

        for c in (driver, sender, srv_rcv, srv_snd, receiver, A1, A2, B1, B2):
            self.add_component(c)

        # Driver to targets
        self.add_coupling(driver.output["out_control"], sender.input["in_control"])
        self.add_coupling(driver.output["out_request"], srv_snd.input["in_request"])

        # Upload loop
        self.add_coupling(sender.output["out_data"], A1.input["in"])
        self.add_coupling(A1.output["out"], srv_rcv.input["in_data"])
        self.add_coupling(srv_rcv.output["out_ack"], A2.input["in"])
        self.add_coupling(A2.output["out"], sender.input["in_ack"])

        # Server storage handoff
        self.add_coupling(srv_rcv.output["out_store"], srv_snd.input["in_store"])

        # Download loop
        self.add_coupling(srv_snd.output["out_data"], B1.input["in"])
        self.add_coupling(B1.output["out"], receiver.input["in_data"])
        self.add_coupling(receiver.output["out_ack"], B2.input["in"])
        self.add_coupling(B2.output["out"], srv_snd.input["in_ack"])


# -----------------------------
# Parsing utilities
# -----------------------------
def parse_time_to_ms(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Bad timestamp '{s}' (expected HH:MM:SS or HH:MM:SS:mmm)")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60) + ss) * 1000 + ms)


def read_schedule_from_stdin() -> list[tuple[float, str, int]]:
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Bad input line: '{line}' (expected: <time> <type> <value>)")
        t_s, typ, val_s = fields
        t_ms = parse_time_to_ms(t_s)
        typ = typ.strip().lower()
        if typ not in ("control", "request"):
            raise ValueError(f"Bad command type '{typ}' in line: '{line}'")
        val = int(val_s)
        schedule.append((t_ms, typ, val))
    schedule.sort(key=lambda x: x[0])
    return schedule


# -----------------------------
# Main
# -----------------------------
def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000_000.0,
                        help="Simulation duration in milliseconds (simulation time). Default: 10000000.0")
    args = parser.parse_args()

    try:
        schedule = read_schedule_from_stdin()
    except Exception as ex:
        print(f"ERROR parsing stdin: {ex}", file=sys.stderr, flush=True)
        raise

    root = System("system", None, schedule)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()