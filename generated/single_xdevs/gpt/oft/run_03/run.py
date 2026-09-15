#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from dataclasses import dataclass
from collections import deque
from typing import Any, Deque, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ---------------------------
# JSONL emission (stdout only)
# ---------------------------

def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _now_int(model: Atomic, e: Optional[float] = None) -> float:
    """
    Try to retrieve current simulation time in milliseconds.
    For deltext: current time = last + e.
    For deltint/lambdaf: current time = time_next.
    """
    # deltext: absolute = time_last + e
    if e is not None:
        base = getattr(model, "time_last", getattr(model, "t_last", 0.0))
        return _safe_float(base) + _safe_float(e)

    # deltint/lambdaf: absolute = time_next
    if hasattr(model, "time_next"):
        return _safe_float(getattr(model, "time_next"))
    if hasattr(model, "t_next"):
        return _safe_float(getattr(model, "t_next"))

    # fallback
    base = getattr(model, "time_last", getattr(model, "t_last", 0.0))
    sigma = getattr(model, "sigma", 0.0)
    return _safe_float(base) + _safe_float(sigma)


def emit(timestamp_ms: float, model: str, etype: str, val: dict) -> None:
    obj = {
        "timestamp_ms": float(timestamp_ms),
        "model": model,
        "type": etype,
        "val": val,
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


# ---------------------------
# Messages
# ---------------------------

@dataclass(frozen=True)
class DataPacket:
    seq: int
    bit: int  # 0/1


@dataclass(frozen=True)
class Ack:
    bit: int  # 0/1


@dataclass(frozen=True)
class ControlCmd:
    added: int


@dataclass(frozen=True)
class RequestCmd:
    allowed: bool


# ---------------------------
# Atomic Models
# ---------------------------

class InputDriver(Atomic):
    """
    Emits ControlCmd and RequestCmd at specified timestamps.
    """
    def __init__(self, name: str, parent: Optional[Coupled], commands: List[Tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(ControlCmd, "control_out"))
        self.add_out_port(Port(RequestCmd, "request_out"))

        self.commands = sorted(commands, key=lambda x: (x[0], x[1]))
        self.idx = 0
        self._batch: List[Tuple[str, int]] = []

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.idx = 0
        self._batch = []
        if not self.commands:
            self.hold_in("PASSIVE", float("inf"))
        else:
            t0 = self.commands[0][0]
            self._prepare_batch_at(t0)
            self.hold_in("EMIT", max(0.0, t0 - 0.0))

    def _prepare_batch_at(self, t: float) -> None:
        self._batch = []
        while self.idx < len(self.commands) and self.commands[self.idx][0] == t:
            _, typ, val = self.commands[self.idx]
            self._batch.append((typ, val))
            self.idx += 1

    def lambdaf(self):
        # Output all commands scheduled at this time
        for typ, val in self._batch:
            if typ == "control":
                self.output["control_out"].add(ControlCmd(int(val)))
            elif typ == "request":
                self.output["request_out"].add(RequestCmd(bool(int(val))))

    def deltint(self):
        # Move to next scheduled time, or passive
        if self.idx >= len(self.commands):
            self._batch = []
            self.hold_in("PASSIVE", float("inf"))
            return

        next_t = self.commands[self.idx][0]
        self._prepare_batch_at(next_t)
        now = _now_int(self)
        self.hold_in("EMIT", max(0.0, next_t - now))

    def deltext(self, e):
        # No external inputs
        # Keep current schedule
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))
        sigma = getattr(self, "sigma", float("inf"))
        remaining = max(0.0, _safe_float(sigma) - _safe_float(e))
        self.hold_in(phase, remaining)

    def exit(self):
        pass


class SubnetDelay(Atomic):
    """
    Reliable FIFO with fixed delay. Supports batching multiple items at same due time.
    """
    def __init__(self, name: str, parent: Optional[Coupled], delay_ms: float, msg_type: Any):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(msg_type, "in"))
        self.add_out_port(Port(msg_type, "out"))

        self.q: Deque[Tuple[float, Any]] = deque()  # (due_time, msg)
        self._next_due: Optional[float] = None
        self._next_out: List[Any] = []

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.q.clear()
        self._next_due = None
        self._next_out = []
        self.hold_in("PASSIVE", float("inf"))

    def _schedule_next(self, now: float) -> None:
        if not self.q:
            self._next_due = None
            self._next_out = []
            self.hold_in("PASSIVE", float("inf"))
            return

        due = self.q[0][0]
        batch: List[Any] = []
        while self.q and self.q[0][0] == due:
            batch.append(self.q[0][1])
            self.q.popleft()

        self._next_due = due
        self._next_out = batch
        self.hold_in("ACTIVE", max(0.0, due - now))

    def lambdaf(self):
        for msg in self._next_out:
            self.output["out"].add(msg)

    def deltint(self):
        now = _now_int(self)
        self._next_due = None
        self._next_out = []
        self._schedule_next(now)

    def deltext(self, e):
        now = _now_int(self, e)
        # ingest all incoming
        for msg in list(self.input["in"].values):
            due = now + self.delay_ms
            self.q.append((due, msg))

        # if passive, schedule; if active, keep current schedule
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))
        if phase == "PASSIVE":
            self._schedule_next(now)
        else:
            # keep remaining time to next internal
            sigma = getattr(self, "sigma", float("inf"))
            remaining = max(0.0, _safe_float(sigma) - _safe_float(e))
            self.hold_in(phase, remaining)

    def exit(self):
        pass


class Sender(Atomic):
    """
    Upload ABP sender with preparation and timeout/retry.
    """
    PREP_MS = 10_000.0
    TIMEOUT_MS = 20_000.0

    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(ControlCmd, "control_in"))
        self.add_in_port(Port(Ack, "ack_in"))
        self.add_out_port(Port(DataPacket, "data_out"))

        # State
        self.packets_remaining: int = 0
        self.seq: int = 1
        self.bit: int = 0

        self.waiting_ack: bool = False
        self._out_packet: Optional[DataPacket] = None
        self._out_is_retry: bool = False
        self._out_timeout_seq: Optional[int] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.waiting_ack = False
        self._out_packet = None
        self._out_is_retry = False
        self._out_timeout_seq = None
        self.hold_in("IDLE", float("inf"))

    def _start_preparation(self, now: float) -> None:
        emit(now, "sender", "preparation_started", {"duration": int(self.PREP_MS)})
        self.hold_in("PREPARE", self.PREP_MS)

    def lambdaf(self):
        if self._out_packet is not None:
            self.output["data_out"].add(self._out_packet)

    def deltint(self):
        now = _now_int(self)
        phase = getattr(self, "phase", getattr(self, "_phase", "IDLE"))

        if phase == "PREPARE":
            # move to SEND immediately; prepare output packet now
            self._out_packet = DataPacket(seq=self.seq, bit=self.bit)
            self._out_is_retry = False
            self._out_timeout_seq = None
            self.hold_in("SEND", 0.0)
            return

        if phase == "SEND":
            # output just happened in lambdaf
            if self._out_packet is not None:
                emit(now, "sender", "packet_sent", {
                    "seq": int(self._out_packet.seq),
                    "bit": int(self._out_packet.bit),
                    "is_retry": bool(self._out_is_retry),
                })
            self.waiting_ack = True
            # clear output
            self._out_packet = None
            self._out_is_retry = False
            self._out_timeout_seq = None
            self.hold_in("WAIT_ACK", self.TIMEOUT_MS)
            return

        if phase == "WAIT_ACK":
            # timeout
            emit(now, "sender", "timeout", {"seq": int(self.seq)})
            # schedule retry send immediately
            self._out_packet = DataPacket(seq=self.seq, bit=self.bit)
            self._out_is_retry = True
            self._out_timeout_seq = self.seq
            self.hold_in("SEND", 0.0)
            return

        # IDLE or unknown
        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = _now_int(self, e)
        phase = getattr(self, "phase", getattr(self, "_phase", "IDLE"))
        sigma = getattr(self, "sigma", float("inf"))
        remaining = max(0.0, _safe_float(sigma) - _safe_float(e))

        # Handle control commands
        for cmd in list(self.input["control_in"].values):
            if isinstance(cmd, ControlCmd):
                added = int(cmd.added)
            else:
                added = int(cmd)
            if added > 0:
                self.packets_remaining += added
                emit(now, "sender", "control_cmd", {"added": int(added), "total_remaining": int(self.packets_remaining)})

        # Handle ACKs
        for ack in list(self.input["ack_in"].values):
            if not isinstance(ack, Ack):
                continue
            if phase == "WAIT_ACK" and self.waiting_ack and int(ack.bit) == int(self.bit):
                emit(now, "sender", "ack_received", {"bit": int(ack.bit)})
                self.waiting_ack = False
                # packet successfully delivered
                if self.packets_remaining > 0:
                    self.packets_remaining -= 1
                self.seq += 1
                self.bit = 1 - int(self.bit)

                if self.packets_remaining > 0:
                    self._start_preparation(now)
                else:
                    self.hold_in("IDLE", float("inf"))
                return
            else:
                # ignore wrong/duplicate ack; keep waiting
                pass

        # No ACK completion: decide scheduling
        if phase == "IDLE":
            if self.packets_remaining > 0 and not self.waiting_ack:
                self._start_preparation(now)
            else:
                self.hold_in("IDLE", float("inf"))
        else:
            # keep current internal schedule
            self.hold_in(phase, remaining)

    def exit(self):
        pass


class ServerReceiver(Atomic):
    """
    Ingress logic: process 3s then send ACK. If expected bit, store seq into storage queue.
    """
    PROC_MS = 3_000.0

    def __init__(self, name: str, parent: Optional[Coupled], storage: Deque[int]):
        super().__init__(name)
        self.parent = parent
        self.storage = storage

        self.add_in_port(Port(DataPacket, "data_in"))
        self.add_out_port(Port(Ack, "ack_out"))

        self.expected_bit: int = 0
        self.in_q: Deque[DataPacket] = deque()

        self.current_pkt: Optional[DataPacket] = None
        self.current_ack_bit: Optional[int] = None
        self.current_accept: bool = False

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.expected_bit = 0
        self.in_q.clear()
        self.current_pkt = None
        self.current_ack_bit = None
        self.current_accept = False
        self.hold_in("PASSIVE", float("inf"))

    def _start_processing_next(self, now: float) -> None:
        if not self.in_q:
            self.current_pkt = None
            self.current_ack_bit = None
            self.current_accept = False
            self.hold_in("PASSIVE", float("inf"))
            return

        pkt = self.in_q.popleft()
        self.current_pkt = pkt
        if int(pkt.bit) == int(self.expected_bit):
            self.current_accept = True
            self.current_ack_bit = int(pkt.bit)
        else:
            self.current_accept = False
            self.current_ack_bit = 1 - int(self.expected_bit)  # previous bit
        self.hold_in("PROCESS", self.PROC_MS)

    def lambdaf(self):
        if self.current_ack_bit is not None:
            self.output["ack_out"].add(Ack(bit=int(self.current_ack_bit)))

    def deltint(self):
        now = _now_int(self)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))

        if phase == "PROCESS":
            # output ack already happened
            if self.current_ack_bit is not None:
                emit(now, "server_receiver", "ack_sent_to_sender", {"bit": int(self.current_ack_bit)})

            # commit accept/store and flip expected bit if accepted
            if self.current_pkt is not None and self.current_accept:
                self.storage.append(int(self.current_pkt.seq))
                self.expected_bit = 1 - int(self.expected_bit)

            # start next if any
            self.current_pkt = None
            self.current_ack_bit = None
            self.current_accept = False
            self._start_processing_next(now)
            return

        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        now = _now_int(self, e)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))
        sigma = getattr(self, "sigma", float("inf"))
        remaining = max(0.0, _safe_float(sigma) - _safe_float(e))

        for pkt in list(self.input["data_in"].values):
            if not isinstance(pkt, DataPacket):
                continue
            emit(now, "server_receiver", "packet_received", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            self.in_q.append(pkt)

        if phase == "PASSIVE":
            self._start_processing_next(now)
        else:
            self.hold_in(phase, remaining)

    def exit(self):
        pass


class ServerSender(Atomic):
    """
    Egress logic: ABP sender to receiver. Sends only when allowed and storage not empty and not waiting for ACK.
    """
    def __init__(self, name: str, parent: Optional[Coupled], storage: Deque[int]):
        super().__init__(name)
        self.parent = parent
        self.storage = storage

        self.add_in_port(Port(RequestCmd, "request_in"))
        self.add_in_port(Port(Ack, "ack_in"))
        self.add_out_port(Port(DataPacket, "data_out"))

        self.download_allowed: bool = False
        self.waiting_ack: bool = False
        self.bit: int = 0

        self.inflight_seq: Optional[int] = None
        self.out_pkt: Optional[DataPacket] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.download_allowed = False
        self.waiting_ack = False
        self.bit = 0
        self.inflight_seq = None
        self.out_pkt = None
        self.hold_in("PASSIVE", float("inf"))

    def _maybe_start_send(self, now: float) -> None:
        if (not self.waiting_ack) and self.download_allowed and (len(self.storage) > 0):
            seq = int(self.storage.popleft())
            self.inflight_seq = seq
            self.out_pkt = DataPacket(seq=seq, bit=int(self.bit))
            self.hold_in("SEND", 0.0)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.out_pkt is not None:
            self.output["data_out"].add(self.out_pkt)

    def deltint(self):
        now = _now_int(self)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))

        if phase == "SEND":
            if self.out_pkt is not None:
                emit(now, "server_sender", "packet_forwarded", {
                    "seq": int(self.out_pkt.seq),
                    "bit": int(self.out_pkt.bit),
                })
            self.out_pkt = None
            self.waiting_ack = True
            self.hold_in("WAIT_ACK", float("inf"))
            return

        # PASSIVE/WAIT_ACK should not have internal events unless SEND
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        now = _now_int(self, e)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))
        sigma = getattr(self, "sigma", float("inf"))
        remaining = max(0.0, _safe_float(sigma) - _safe_float(e))

        # request valve changes
        for req in list(self.input["request_in"].values):
            allowed = req.allowed if isinstance(req, RequestCmd) else bool(int(req))
            self.download_allowed = bool(allowed)
            emit(now, "server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})

        # ACK handling
        for ack in list(self.input["ack_in"].values):
            if not isinstance(ack, Ack):
                continue
            if phase == "WAIT_ACK" and self.waiting_ack and int(ack.bit) == int(self.bit):
                emit(now, "server_sender", "ack_received_from_receiver", {"bit": int(ack.bit)})
                self.waiting_ack = False
                self.inflight_seq = None
                self.bit = 1 - int(self.bit)
                # after ACK, either continue (if allowed) or stop
                self._maybe_start_send(now)
                return

        # no ack completion: if passive, maybe start send; else keep schedule
        if phase == "PASSIVE":
            self._maybe_start_send(now)
        else:
            # WAIT_ACK: keep waiting regardless of allowed flag (graceful stop)
            self.hold_in(phase, remaining)

    def exit(self):
        pass


class Receiver(Atomic):
    """
    Download receiver: process 10s then send ACK.
    Standard ABP behavior to deal with duplicates.
    """
    PROC_MS = 10_000.0

    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(DataPacket, "data_in"))
        self.add_out_port(Port(Ack, "ack_out"))

        self.expected_bit: int = 0
        self.in_q: Deque[DataPacket] = deque()

        self.current_pkt: Optional[DataPacket] = None
        self.current_ack_bit: Optional[int] = None
        self.current_accept: bool = False

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.expected_bit = 0
        self.in_q.clear()
        self.current_pkt = None
        self.current_ack_bit = None
        self.current_accept = False
        self.hold_in("PASSIVE", float("inf"))

    def _start_processing_next(self, now: float) -> None:
        if not self.in_q:
            self.current_pkt = None
            self.current_ack_bit = None
            self.current_accept = False
            self.hold_in("PASSIVE", float("inf"))
            return

        pkt = self.in_q.popleft()
        self.current_pkt = pkt
        if int(pkt.bit) == int(self.expected_bit):
            self.current_accept = True
            self.current_ack_bit = int(pkt.bit)
        else:
            self.current_accept = False
            self.current_ack_bit = 1 - int(self.expected_bit)

        emit(now, "receiver", "processing_started", {"seq": int(pkt.seq), "duration": int(self.PROC_MS)})
        self.hold_in("PROCESS", self.PROC_MS)

    def lambdaf(self):
        if self.current_ack_bit is not None:
            self.output["ack_out"].add(Ack(bit=int(self.current_ack_bit)))

    def deltint(self):
        now = _now_int(self)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))

        if phase == "PROCESS":
            if self.current_ack_bit is not None:
                emit(now, "receiver", "ack_sent", {"bit": int(self.current_ack_bit)})
            if self.current_accept:
                self.expected_bit = 1 - int(self.expected_bit)

            self.current_pkt = None
            self.current_ack_bit = None
            self.current_accept = False
            self._start_processing_next(now)
            return

        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        now = _now_int(self, e)
        phase = getattr(self, "phase", getattr(self, "_phase", "PASSIVE"))
        sigma = getattr(self, "sigma", float("inf"))
        remaining = max(0.0, _safe_float(sigma) - _safe_float(e))

        for pkt in list(self.input["data_in"].values):
            if isinstance(pkt, DataPacket):
                self.in_q.append(pkt)

        if phase == "PASSIVE":
            self._start_processing_next(now)
        else:
            self.hold_in(phase, remaining)

    def exit(self):
        pass


# ---------------------------
# Coupled System
# ---------------------------

class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], commands: List[Tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent

        # Shared storage queue: holds seq ids accepted by ingress
        storage: Deque[int] = deque()

        # Components
        driver = InputDriver("driver", self, commands)
        sender = Sender("sender", self)

        a1 = SubnetDelay("subnet_a1", self, delay_ms=3_000.0, msg_type=DataPacket)  # sender -> server_receiver
        a2 = SubnetDelay("subnet_a2", self, delay_ms=3_000.0, msg_type=Ack)         # server_receiver -> sender

        server_receiver = ServerReceiver("server_receiver", self, storage=storage)
        server_sender = ServerSender("server_sender", self, storage=storage)

        b1 = SubnetDelay("subnet_b1", self, delay_ms=3_000.0, msg_type=DataPacket)  # server_sender -> receiver
        b2 = SubnetDelay("subnet_b2", self, delay_ms=3_000.0, msg_type=Ack)         # receiver -> server_sender

        receiver = Receiver("receiver", self)

        # Add components
        for c in (driver, sender, a1, a2, server_receiver, server_sender, b1, b2, receiver):
            self.add_component(c)

        # Couplings: driver -> endpoints
        self.add_coupling(driver.output["control_out"], sender.input["control_in"])
        self.add_coupling(driver.output["request_out"], server_sender.input["request_in"])

        # Upload loop: sender -> A1 -> server_receiver ; server_receiver ACK -> A2 -> sender
        self.add_coupling(sender.output["data_out"], a1.input["in"])
        self.add_coupling(a1.output["out"], server_receiver.input["data_in"])

        self.add_coupling(server_receiver.output["ack_out"], a2.input["in"])
        self.add_coupling(a2.output["out"], sender.input["ack_in"])

        # Download loop: server_sender -> B1 -> receiver ; receiver ACK -> B2 -> server_sender
        self.add_coupling(server_sender.output["data_out"], b1.input["in"])
        self.add_coupling(b1.output["out"], receiver.input["data_in"])

        self.add_coupling(receiver.output["ack_out"], b2.input["in"])
        self.add_coupling(b2.output["out"], server_sender.input["ack_in"])


# ---------------------------
# Parsing stdin commands
# ---------------------------

def parse_time_to_ms(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {s}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60 + ss) * 1000) + mmm)


def read_commands_from_stdin() -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid command line (expected 3 fields): {line}")
        t_str, typ, val_str = fields
        t_ms = parse_time_to_ms(t_str)
        if typ not in ("control", "request"):
            raise ValueError(f"Invalid command type: {typ}")
        val = int(val_str)
        cmds.append((t_ms, typ, val))
    return cmds


# ---------------------------
# Main
# ---------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10_000_000.0,
                        help="Simulation duration in milliseconds (simulation time).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        commands = read_commands_from_stdin()
    except Exception as ex:
        logging.error("Failed to read commands from stdin: %s", ex)
        sys.exit(2)

    root = System(name="system", parent=None, commands=commands)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()