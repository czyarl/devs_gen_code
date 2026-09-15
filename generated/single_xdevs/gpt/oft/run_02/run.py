import argparse
import sys
import json
import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Constants (milliseconds)
# -----------------------------
INF = float("inf")

SENDER_PREP_MS = 10_000.0
SENDER_TIMEOUT_MS = 20_000.0

SERVER_RECV_PROCESS_MS = 3_000.0
SUBNET_DELAY_MS = 3_000.0

RECEIVER_PROCESS_MS = 10_000.0


# -----------------------------
# JSONL event emission (stdout)
# -----------------------------
def emit(timestamp_ms: float, model: str, type_: str, val: Dict[str, Any]) -> None:
    obj = {
        "timestamp_ms": float(timestamp_ms),
        "model": str(model),
        "type": str(type_),
        "val": val,
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


def _get_t_last(m: Any) -> float:
    for name in ("t_last", "time_last", "_t_last"):
        if hasattr(m, name):
            return float(getattr(m, name))
    return 0.0


def _get_t_next(m: Any) -> float:
    for name in ("t_next", "time_next", "_t_next"):
        if hasattr(m, name):
            return float(getattr(m, name))
    # Fallback for lambdaf/deltint; if unknown, approximate with last time.
    return _get_t_last(m)


def time_ext(m: Any, e: float) -> float:
    return _get_t_last(m) + float(e)


def time_int(m: Any) -> float:
    return _get_t_next(m)


def _remaining_sigma(m: Any, e: float) -> float:
    # Preserve time advance on external transitions.
    sigma = getattr(m, "sigma", INF)
    try:
        sigma = float(sigma)
    except Exception:
        sigma = INF
    if sigma == INF:
        return INF
    rem = sigma - float(e)
    if rem < 0:
        rem = 0.0
    return rem


# -----------------------------
# Input scheduler
# -----------------------------
class InputScheduler(Atomic):
    """
    Reads pre-parsed commands and emits them at their timestamps.

    Outputs:
      - control_out: int (added packets)
      - request_out: int (0/1)
    """

    def __init__(self, name: str, parent: Optional[Coupled], commands: List[Tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(int, "control_out"))
        self.add_out_port(Port(int, "request_out"))

        self._cmds: List[Tuple[float, str, int]] = sorted(commands, key=lambda x: x[0])
        self._idx: int = 0

        self._to_emit_control: List[int] = []
        self._to_emit_request: List[int] = []

        self.hold_in("INIT", 0.0)

    def initialize(self):
        if not self._cmds:
            self.hold_in("IDLE", INF)
            return
        first_t = self._cmds[0][0]
        self.hold_in("EMIT", max(0.0, first_t))

    def lambdaf(self):
        for v in self._to_emit_control:
            self.output["control_out"].add(int(v))
        for v in self._to_emit_request:
            self.output["request_out"].add(int(v))

    def deltint(self):
        now = time_int(self)

        self._to_emit_control = []
        self._to_emit_request = []

        # Emit all commands scheduled at 'now'
        while self._idx < len(self._cmds) and self._cmds[self._idx][0] <= now + 1e-9:
            _, typ, val = self._cmds[self._idx]
            if typ == "control":
                self._to_emit_control.append(int(val))
            elif typ == "request":
                self._to_emit_request.append(int(val))
            self._idx += 1

        if self._idx >= len(self._cmds):
            self.hold_in("IDLE", INF)
            return

        next_t = self._cmds[self._idx][0]
        self.hold_in("EMIT", max(0.0, next_t - now))

    def deltext(self, e):
        # No external inputs for scheduler
        self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# Subnet delay (reliable FIFO)
# -----------------------------
class DelaySubnet(Atomic):
    """
    Reliable FIFO fixed delay line.
    Single input -> single output.
    """

    def __init__(self, name: str, parent: Optional[Coupled], delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(object, "inp"))
        self.add_out_port(Port(object, "out"))

        self._q: Deque[Any] = deque()
        self._out_msg: Optional[Any] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self._out_msg is not None:
            self.output["out"].add(self._out_msg)

    def deltint(self):
        # An item is ready to be output
        if self._q:
            self._out_msg = self._q.popleft()
        else:
            self._out_msg = None

        # After output, schedule next item if any
        if self._q:
            self.hold_in("BUSY", self.delay_ms)
        else:
            self.hold_in("IDLE", INF)

    def deltext(self, e):
        # Append new incoming messages
        for msg in self.input["inp"].values:
            self._q.append(msg)

        if self.phase == "IDLE":
            if self._q:
                self.hold_in("BUSY", self.delay_ms)
            else:
                self.hold_in("IDLE", INF)
        else:
            self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# Sender (Uploader) with ABP
# -----------------------------
class Sender(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(int, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        self.packets_remaining: int = 0
        self.seq: int = 1
        self.bit: int = 0

        self._send_is_retry: bool = False
        self._out_packet: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self.phase == "SEND" and self._out_packet is not None:
            now = time_int(self)
            # Log at send time
            emit(now, "sender", "packet_sent", {"seq": int(self._out_packet["seq"]), "bit": int(self._out_packet["bit"]), "is_retry": bool(self._send_is_retry)})
            self.output["data_out"].add(self._out_packet)

    def deltint(self):
        now = time_int(self)

        if self.phase == "PREPARE":
            # Preparation complete -> send immediately
            self._send_is_retry = False
            self._out_packet = {"kind": "data", "seq": int(self.seq), "bit": int(self.bit)}
            self.hold_in("SEND", 0.0)
            return

        if self.phase == "SEND":
            # After sending, wait for ACK with timeout
            self._out_packet = None
            self.hold_in("WAIT_ACK", SENDER_TIMEOUT_MS)
            return

        if self.phase == "WAIT_ACK":
            # Timeout -> retransmit
            emit(now, "sender", "timeout", {"seq": int(self.seq)})
            self._send_is_retry = True
            self._out_packet = {"kind": "data", "seq": int(self.seq), "bit": int(self.bit)}
            self.hold_in("SEND", 0.0)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        now = time_ext(self, e)

        # Handle control commands
        added_total = 0
        for v in self.input["control_in"].values:
            try:
                added_total += int(v)
            except Exception:
                continue
        if added_total != 0:
            self.packets_remaining += max(0, added_total)
            emit(now, "sender", "control_cmd", {"added": int(added_total), "total_remaining": int(self.packets_remaining)})

        # Handle ACKs
        for ack in self.input["ack_in"].values:
            if not isinstance(ack, dict) or ack.get("kind") != "ack":
                continue
            ack_bit = int(ack.get("bit", -1))
            if self.phase == "WAIT_ACK" and ack_bit == self.bit:
                emit(now, "sender", "ack_received", {"bit": int(ack_bit)})
                # Successful transmission of current packet
                self.packets_remaining = max(0, self.packets_remaining - 1)
                self.seq += 1
                self.bit = 1 - self.bit
                self._send_is_retry = False
                self._out_packet = None

                if self.packets_remaining > 0:
                    emit(now, "sender", "preparation_started", {"duration": int(SENDER_PREP_MS)})
                    self.hold_in("PREPARE", SENDER_PREP_MS)
                else:
                    self.hold_in("IDLE", INF)
                return

        # If idle and work exists, start preparing
        if self.phase == "IDLE" and self.packets_remaining > 0:
            emit(now, "sender", "preparation_started", {"duration": int(SENDER_PREP_MS)})
            self.hold_in("PREPARE", SENDER_PREP_MS)
            return

        # Otherwise, keep current phase and remaining sigma
        self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# Server Receiver (Ingress ABP endpoint)
# -----------------------------
class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "store_out"))

        self.expected_bit: int = 0
        self._in_q: Deque[Dict[str, Any]] = deque()

        self._out_ack: Optional[Dict[str, Any]] = None
        self._out_store: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self.phase == "DONE":
            now = time_int(self)
            if self._out_ack is not None:
                emit(now, "server_receiver", "ack_sent_to_sender", {"bit": int(self._out_ack["bit"])})
                self.output["ack_out"].add(self._out_ack)
            if self._out_store is not None:
                self.output["store_out"].add(self._out_store)

    def deltint(self):
        if self.phase == "PROCESS":
            # Finish processing, decide ACK and whether to store
            pkt = self._in_q[0] if self._in_q else None
            self._out_ack = None
            self._out_store = None

            if pkt is not None:
                bit = int(pkt.get("bit", -1))
                seq = int(pkt.get("seq", -1))

                if bit == self.expected_bit:
                    # Correct -> ACK same bit, store seq, flip expected
                    self._out_ack = {"kind": "ack", "bit": int(bit)}
                    self._out_store = {"kind": "stored", "seq": int(seq)}
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # Duplicate -> ACK previous bit (1 - expected)
                    prev_bit = 1 - self.expected_bit
                    self._out_ack = {"kind": "ack", "bit": int(prev_bit)}
                    self._out_store = None

                # Consume packet after processing
                self._in_q.popleft()

            self.hold_in("DONE", 0.0)
            return

        if self.phase == "DONE":
            self._out_ack = None
            self._out_store = None
            if self._in_q:
                self.hold_in("PROCESS", SERVER_RECV_PROCESS_MS)
            else:
                self.hold_in("IDLE", INF)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        now = time_ext(self, e)

        # Enqueue arrivals
        for pkt in self.input["data_in"].values:
            if not isinstance(pkt, dict) or pkt.get("kind") != "data":
                continue
            seq = int(pkt.get("seq", -1))
            bit = int(pkt.get("bit", -1))
            emit(now, "server_receiver", "packet_received", {"seq": int(seq), "bit": int(bit)})
            self._in_q.append(pkt)

        if self.phase == "IDLE" and self._in_q:
            self.hold_in("PROCESS", SERVER_RECV_PROCESS_MS)
            return

        self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# Storage queue (Server buffer)
# -----------------------------
class StorageQueue(Atomic):
    """
    Simple FIFO storage queue.
    - put_in: {"kind":"stored","seq":int}
    - get_in: {"kind":"get"}
    - cancel_in: {"kind":"cancel"}
    - data_out: {"kind":"stored","seq":int}
    """

    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "put_in"))
        self.add_in_port(Port(dict, "get_in"))
        self.add_in_port(Port(dict, "cancel_in"))
        self.add_out_port(Port(dict, "data_out"))

        self._q: Deque[Dict[str, Any]] = deque()
        self._pending_get: bool = False
        self._out_item: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self.phase == "OUT" and self._out_item is not None:
            self.output["data_out"].add(self._out_item)

    def deltint(self):
        if self.phase == "OUT":
            # Serve one
            if self._q:
                self._out_item = self._q.popleft()
            else:
                self._out_item = None
            self._pending_get = False
            self.hold_in("IDLE", INF)
            return
        self.hold_in("IDLE", INF)

    def deltext(self, e):
        # Apply external events
        for msg in self.input["cancel_in"].values:
            if isinstance(msg, dict) and msg.get("kind") == "cancel":
                self._pending_get = False

        for msg in self.input["get_in"].values:
            if isinstance(msg, dict) and msg.get("kind") == "get":
                self._pending_get = True

        for item in self.input["put_in"].values:
            if isinstance(item, dict) and item.get("kind") == "stored":
                self._q.append(item)

        # Decide next
        if self._pending_get and self._q:
            self._out_item = self._q[0]
            self.hold_in("OUT", 0.0)
            return

        self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# Server Sender (Egress ABP endpoint)
# -----------------------------
class ServerSender(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(int, "request_in"))
        self.add_in_port(Port(dict, "from_storage_in"))
        self.add_in_port(Port(dict, "ack_in"))

        self.add_out_port(Port(dict, "to_storage_get_out"))
        self.add_out_port(Port(dict, "to_storage_cancel_out"))
        self.add_out_port(Port(dict, "data_out"))

        self.download_allowed: bool = False
        self.waiting_ack: bool = False
        self.waiting_storage: bool = False

        self.seq_pending: Optional[int] = None
        self.bit: int = 0

        self._out_get: bool = False
        self._out_cancel: bool = False
        self._out_data: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        now = time_int(self)

        if self.phase == "DO_GET" and self._out_get:
            self.output["to_storage_get_out"].add({"kind": "get"})

        if self.phase == "DO_CANCEL" and self._out_cancel:
            self.output["to_storage_cancel_out"].add({"kind": "cancel"})

        if self.phase == "SEND" and self._out_data is not None:
            emit(now, "server_sender", "packet_forwarded", {"seq": int(self._out_data["seq"]), "bit": int(self._out_data["bit"])})
            self.output["data_out"].add(self._out_data)

    def _schedule_next(self, now: float, rem: Optional[float] = None) -> None:
        # Determine next action given current flags/state.
        if self.waiting_ack:
            self._out_get = False
            self._out_cancel = False
            self._out_data = None
            self.hold_in("WAIT_ACK", INF)
            return

        if self.seq_pending is not None and self.download_allowed:
            self._out_data = {"kind": "data", "seq": int(self.seq_pending), "bit": int(self.bit)}
            self._out_get = False
            self._out_cancel = False
            self.hold_in("SEND", 0.0)
            return

        if self.download_allowed:
            if not self.waiting_storage:
                self._out_get = True
                self._out_cancel = False
                self._out_data = None
                self.hold_in("DO_GET", 0.0)
                return
            # waiting_storage == True: just wait
            self._out_get = False
            self._out_cancel = False
            self._out_data = None
            self.hold_in("IDLE", INF)
            return

        # download not allowed
        if self.waiting_storage and self.seq_pending is None:
            self._out_cancel = True
            self._out_get = False
            self._out_data = None
            self.hold_in("DO_CANCEL", 0.0)
            return

        self._out_get = False
        self._out_cancel = False
        self._out_data = None
        self.hold_in("IDLE", INF)

    def deltint(self):
        now = time_int(self)

        if self.phase == "DO_GET":
            self._out_get = False
            self.waiting_storage = True
            self._schedule_next(now)
            return

        if self.phase == "DO_CANCEL":
            self._out_cancel = False
            self.waiting_storage = False
            self._schedule_next(now)
            return

        if self.phase == "SEND":
            self._out_data = None
            self.waiting_ack = True
            self.hold_in("WAIT_ACK", INF)
            return

        self._schedule_next(now)

    def deltext(self, e):
        now = time_ext(self, e)

        # request valve changes
        for v in self.input["request_in"].values:
            try:
                vv = int(v)
            except Exception:
                continue
            allowed = (vv == 1)
            if allowed != self.download_allowed:
                self.download_allowed = allowed
                emit(now, "server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})

        # receive data from storage
        for item in self.input["from_storage_in"].values:
            if isinstance(item, dict) and item.get("kind") == "stored":
                self.seq_pending = int(item.get("seq", -1))
                self.waiting_storage = False

        # receive ack from receiver
        for ack in self.input["ack_in"].values:
            if not isinstance(ack, dict) or ack.get("kind") != "ack":
                continue
            ack_bit = int(ack.get("bit", -1))
            if self.waiting_ack and ack_bit == self.bit:
                emit(now, "server_sender", "ack_received_from_receiver", {"bit": int(ack_bit)})
                self.waiting_ack = False
                self.bit = 1 - self.bit
                self.seq_pending = None

        # Keep remaining sigma if needed; then reschedule according to logic
        _ = _remaining_sigma(self, e)
        self._schedule_next(now)

    def exit(self):
        pass


# -----------------------------
# Receiver (Downloader)
# -----------------------------
class Receiver(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        self._in_q: Deque[Dict[str, Any]] = deque()
        self._out_ack: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self.phase == "DONE" and self._out_ack is not None:
            now = time_int(self)
            emit(now, "receiver", "ack_sent", {"bit": int(self._out_ack["bit"])})
            self.output["ack_out"].add(self._out_ack)

    def deltint(self):
        if self.phase == "PROCESS":
            pkt = self._in_q[0] if self._in_q else None
            self._out_ack = None
            if pkt is not None:
                bit = int(pkt.get("bit", -1))
                self._out_ack = {"kind": "ack", "bit": int(bit)}
                self._in_q.popleft()
            self.hold_in("DONE", 0.0)
            return

        if self.phase == "DONE":
            self._out_ack = None
            if self._in_q:
                self.hold_in("PROCESS", RECEIVER_PROCESS_MS)
            else:
                self.hold_in("IDLE", INF)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        now = time_ext(self, e)

        for pkt in self.input["data_in"].values:
            if not isinstance(pkt, dict) or pkt.get("kind") != "data":
                continue
            seq = int(pkt.get("seq", -1))
            emit(now, "receiver", "processing_started", {"seq": int(seq), "duration": int(RECEIVER_PROCESS_MS)})
            self._in_q.append(pkt)

        if self.phase == "IDLE" and self._in_q:
            self.hold_in("PROCESS", RECEIVER_PROCESS_MS)
            return

        self.hold_in(self.phase, _remaining_sigma(self, e))

    def exit(self):
        pass


# -----------------------------
# System coupled model
# -----------------------------
class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], commands: List[Tuple[float, str, int]]):
        super().__init__(name)
        self.parent = parent

        # Components
        scheduler = InputScheduler("scheduler", self, commands)
        sender = Sender("sender", self)

        subnet_a1 = DelaySubnet("subnet_a1", self, SUBNET_DELAY_MS)  # sender -> server
        subnet_a2 = DelaySubnet("subnet_a2", self, SUBNET_DELAY_MS)  # server -> sender

        server_receiver = ServerReceiver("server_receiver", self)
        storage = StorageQueue("storage", self)
        server_sender = ServerSender("server_sender", self)

        subnet_b1 = DelaySubnet("subnet_b1", self, SUBNET_DELAY_MS)  # server -> receiver
        subnet_b2 = DelaySubnet("subnet_b2", self, SUBNET_DELAY_MS)  # receiver -> server

        receiver = Receiver("receiver", self)

        # Add components
        for c in (scheduler, sender, subnet_a1, subnet_a2, server_receiver, storage, server_sender, subnet_b1, subnet_b2, receiver):
            self.add_component(c)

        # Couplings
        # Scheduler -> Sender/ServerSender
        self.add_coupling(scheduler.output["control_out"], sender.input["control_in"])
        self.add_coupling(scheduler.output["request_out"], server_sender.input["request_in"])

        # Upload ABP loop
        self.add_coupling(sender.output["data_out"], subnet_a1.input["inp"])
        self.add_coupling(subnet_a1.output["out"], server_receiver.input["data_in"])

        self.add_coupling(server_receiver.output["ack_out"], subnet_a2.input["inp"])
        self.add_coupling(subnet_a2.output["out"], sender.input["ack_in"])

        # Ingress store to storage queue
        self.add_coupling(server_receiver.output["store_out"], storage.input["put_in"])

        # Download path: ServerSender <-> Storage
        self.add_coupling(server_sender.output["to_storage_get_out"], storage.input["get_in"])
        self.add_coupling(server_sender.output["to_storage_cancel_out"], storage.input["cancel_in"])
        self.add_coupling(storage.output["data_out"], server_sender.input["from_storage_in"])

        # Download ABP loop
        self.add_coupling(server_sender.output["data_out"], subnet_b1.input["inp"])
        self.add_coupling(subnet_b1.output["out"], receiver.input["data_in"])

        self.add_coupling(receiver.output["ack_out"], subnet_b2.input["inp"])
        self.add_coupling(subnet_b2.output["out"], server_sender.input["ack_in"])


# -----------------------------
# CLI + stdin parsing
# -----------------------------
def parse_time_to_ms(s: str) -> float:
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60 + ss) * 1000) + ms)


def read_commands_from_stdin() -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            logging.warning("Skipping invalid command line: %r", line)
            continue
        ts_s, typ, val_s = fields
        try:
            t_ms = parse_time_to_ms(ts_s)
            val = int(val_s)
        except Exception as ex:
            logging.warning("Skipping invalid command line: %r (%s)", line, ex)
            continue
        if typ not in ("control", "request"):
            logging.warning("Skipping unknown command type: %r", typ)
            continue
        cmds.append((t_ms, typ, val))
    return cmds


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10_000_000.0, help="Simulation duration in milliseconds.")
    args = parser.parse_args()

    commands = read_commands_from_stdin()

    root = System("system", None, commands)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()