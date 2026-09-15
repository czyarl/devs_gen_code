#!/usr/bin/env python3
import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import simpy


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


class JsonlLogger:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: Dict[str, Any]) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def parse_hhmmss_to_ms(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= mmm < 1000 and hh >= 0):
        raise ValueError(f"Invalid time components: {s!r}")
    return ((hh * 60 + mm) * 60 + ss) * 1000 + mmm


@dataclass(frozen=True)
class Command:
    t_ms: int
    typ: str
    value: int


class FixedDelayLink:
    """Reliable FIFO link with fixed propagation delay."""

    def __init__(self, env: simpy.Environment, delay_ms: int, outbox: simpy.Store):
        self.env = env
        self.delay_ms = delay_ms
        self._queue: simpy.Store = simpy.Store(env)
        self._outbox = outbox
        self._proc = env.process(self._run())

    def send(self, msg: Dict[str, Any]) -> None:
        self._queue.put(msg)

    def _run(self):
        while True:
            msg = yield self._queue.get()
            yield self.env.timeout(self.delay_ms)
            yield self._outbox.put(msg)


class Sender:
    PREP_MS = 10_000
    TIMEOUT_MS = 20_000

    def __init__(
        self,
        env: simpy.Environment,
        log: JsonlLogger,
        data_link: FixedDelayLink,
        ack_inbox: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.data_link = data_link
        self.ack_inbox = ack_inbox

        self.packets_remaining = 0
        self._active = False

        self._seq = 1
        self._bit = 0

    def add_packets(self, n: int) -> None:
        if n <= 0:
            return
        self.packets_remaining += n
        self.log.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.packets_remaining)},
        )
        if not self._active:
            self._active = True
            self.env.process(self._run())

    def _send_packet(self, seq: int, bit: int, is_retry: bool) -> None:
        self.log.emit(
            "sender",
            "packet_sent",
            {"seq": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
        )
        self.data_link.send({"kind": "data", "seq": int(seq), "bit": int(bit)})

    def _wait_for_ack(self, expected_bit: int, timeout_ms: int) -> Optional[Dict[str, Any]]:
        start = float(self.env.now)
        remaining = float(timeout_ms)
        while remaining > 0:
            ack_get = self.ack_inbox.get()
            to = self.env.timeout(remaining)
            res = yield simpy.events.AnyOf(self.env, [ack_get, to])
            if ack_get not in res:
                ack_get.cancel()
                return None
            ack = res[ack_get]
            if ack.get("kind") != "ack":
                remaining = float(timeout_ms) - (float(self.env.now) - start)
                continue
            self.log.emit("sender", "ack_received", {"bit": int(ack["bit"])})
            if int(ack["bit"]) == int(expected_bit):
                return ack
            remaining = float(timeout_ms) - (float(self.env.now) - start)
        return None

    def _run(self):
        try:
            while self.packets_remaining > 0:
                self.log.emit(
                    "sender",
                    "preparation_started",
                    {"duration": int(self.PREP_MS)},
                )
                yield self.env.timeout(self.PREP_MS)

                seq = self._seq
                bit = self._bit
                is_retry = False
                while True:
                    self._send_packet(seq, bit, is_retry=is_retry)
                    ack = yield from self._wait_for_ack(bit, self.TIMEOUT_MS)
                    if ack is not None:
                        break
                    self.log.emit("sender", "timeout", {"seq": int(seq)})
                    is_retry = True

                self._bit = 1 - self._bit
                self._seq += 1
                self.packets_remaining -= 1
        finally:
            self._active = False


class ServerReceiver:
    PROC_MS = 3_000

    def __init__(
        self,
        env: simpy.Environment,
        log: JsonlLogger,
        inbox: simpy.Store,
        ack_link: FixedDelayLink,
        storage_queue: simpy.Store,
        on_storage_put,
    ):
        self.env = env
        self.log = log
        self.inbox = inbox
        self.ack_link = ack_link
        self.storage_queue = storage_queue
        self.on_storage_put = on_storage_put

        self._expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.inbox.get()
            if msg.get("kind") != "data":
                continue
            seq = int(msg["seq"])
            bit = int(msg["bit"])
            self.log.emit("server_receiver", "packet_received", {"seq": seq, "bit": bit})

            yield self.env.timeout(self.PROC_MS)

            if bit == self._expected_bit:
                ack_bit = bit
                self.ack_link.send({"kind": "ack", "bit": ack_bit})
                self.log.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(ack_bit)},
                )
                yield self.storage_queue.put({"seq": seq})
                self.on_storage_put()
                self._expected_bit = 1 - self._expected_bit
            else:
                ack_bit = 1 - self._expected_bit
                self.ack_link.send({"kind": "ack", "bit": ack_bit})
                self.log.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(ack_bit)},
                )


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        log: JsonlLogger,
        storage_queue: simpy.Store,
        data_link: FixedDelayLink,
        ack_inbox: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.storage_queue = storage_queue
        self.data_link = data_link
        self.ack_inbox = ack_inbox

        self.download_allowed = False
        self._waiting_for_ack = False
        self._bit = 0

        self._kick = env.event()
        self.env.process(self._run())

    def set_allowed(self, allowed: bool) -> None:
        self.download_allowed = bool(allowed)
        self.log.emit(
            "server_sender",
            "download_valve_change",
            {"allowed": bool(self.download_allowed)},
        )
        self._wakeup()

    def _wakeup(self) -> None:
        if not self._kick.triggered:
            self._kick.succeed()
        self._kick = self.env.event()

    def notify_storage_put(self) -> None:
        self._wakeup()

    def _run(self):
        while True:
            if (
                self.download_allowed
                and not self._waiting_for_ack
                and len(self.storage_queue.items) > 0
            ):
                item = yield self.storage_queue.get()
                seq = int(item["seq"])
                bit = int(self._bit)

                self._waiting_for_ack = True
                self.log.emit("server_sender", "packet_forwarded", {"seq": seq, "bit": bit})
                self.data_link.send({"kind": "data", "seq": seq, "bit": bit})

                while True:
                    ack = yield self.ack_inbox.get()
                    if ack.get("kind") != "ack":
                        continue
                    ack_bit = int(ack["bit"])
                    self.log.emit(
                        "server_sender",
                        "ack_received_from_receiver",
                        {"bit": ack_bit},
                    )
                    if ack_bit == bit:
                        break

                self._bit = 1 - self._bit
                self._waiting_for_ack = False
                continue

            yield self._kick


class Receiver:
    PROC_MS = 10_000

    def __init__(
        self,
        env: simpy.Environment,
        log: JsonlLogger,
        inbox: simpy.Store,
        ack_link: FixedDelayLink,
    ):
        self.env = env
        self.log = log
        self.inbox = inbox
        self.ack_link = ack_link

        self._expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.inbox.get()
            if msg.get("kind") != "data":
                continue
            seq = int(msg["seq"])
            bit = int(msg["bit"])

            if bit != self._expected_bit:
                # Duplicate: re-ACK previous bit immediately (no processing).
                prev = 1 - self._expected_bit
                self.ack_link.send({"kind": "ack", "bit": prev})
                continue

            self.log.emit(
                "receiver",
                "processing_started",
                {"seq": seq, "duration": int(self.PROC_MS)},
            )
            yield self.env.timeout(self.PROC_MS)
            self.ack_link.send({"kind": "ack", "bit": bit})
            self.log.emit("receiver", "ack_sent", {"bit": int(bit)})
            self._expected_bit = 1 - self._expected_bit


def read_commands(stdin) -> List[Command]:
    cmds: List[Command] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            logging.warning("Skipping malformed input line: %r", line)
            continue
        t_s, typ, value_s = parts
        try:
            t_ms = parse_hhmmss_to_ms(t_s)
            value = int(value_s)
        except Exception:
            logging.exception("Skipping invalid input line: %r", line)
            continue
        if typ not in ("control", "request"):
            logging.warning("Skipping unknown command type %r in line: %r", typ, line)
            continue
        cmds.append(Command(t_ms=t_ms, typ=typ, value=value))

    cmds.sort(key=lambda c: c.t_ms)
    return cmds


def command_injector(
    env: simpy.Environment,
    cmds: List[Command],
    sender: Sender,
    server_sender: ServerSender,
    simulation_time_ms: float,
):
    for cmd in cmds:
        if cmd.t_ms > simulation_time_ms:
            break
        if cmd.t_ms < env.now:
            continue
        yield env.timeout(cmd.t_ms - env.now)
        if cmd.typ == "control":
            sender.add_packets(cmd.value)
        elif cmd.typ == "request":
            server_sender.set_allowed(bool(cmd.value))


def build_and_run(simulation_time_ms: float, cmds: List[Command]) -> None:
    wall_start = time.time()
    env = simpy.Environment()
    log = JsonlLogger(env)

    # Inboxes
    server_rx_inbox = simpy.Store(env)
    sender_ack_inbox = simpy.Store(env)
    receiver_inbox = simpy.Store(env)
    server_sender_ack_inbox = simpy.Store(env)

    storage_queue = simpy.Store(env)

    # Links: fixed 3s delay each
    a1 = FixedDelayLink(env, 3_000, server_rx_inbox)  # Sender -> ServerReceiver
    a2 = FixedDelayLink(env, 3_000, sender_ack_inbox)  # ServerReceiver -> Sender
    b1 = FixedDelayLink(env, 3_000, receiver_inbox)  # ServerSender -> Receiver
    b2 = FixedDelayLink(env, 3_000, server_sender_ack_inbox)  # Receiver -> ServerSender

    server_sender = ServerSender(env, log, storage_queue, b1, server_sender_ack_inbox)

    server_receiver = ServerReceiver(
        env,
        log,
        server_rx_inbox,
        a2,
        storage_queue,
        on_storage_put=server_sender.notify_storage_put,
    )
    _ = server_receiver

    sender = Sender(env, log, a1, sender_ack_inbox)
    receiver = Receiver(env, log, receiver_inbox, b2)
    _ = receiver

    env.process(command_injector(env, cmds, sender, server_sender, simulation_time_ms))

    end = float(simulation_time_ms)
    while True:
        if time.time() - wall_start > 9.5:
            logging.warning("Wall-clock limit reached; stopping simulation early")
            break
        try:
            nxt = env.peek()
        except simpy.core.EmptySchedule:
            break
        if float(nxt) > end:
            break
        env.step()


def main(argv: Optional[List[str]] = None) -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(description="Dropbox-like ABP sync simulation (SimPy)")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (simulation time).",
    )
    args = parser.parse_args(argv)

    cmds = read_commands(sys.stdin)
    build_and_run(float(args.simulation_time), cmds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
