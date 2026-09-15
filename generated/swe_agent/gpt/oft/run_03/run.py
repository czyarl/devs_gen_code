#!/usr/bin/env python3
"""Discrete-event simulation of a Dropbox-like sync using two ABP loops.

STDOUT: JSONL event stream only.
STDERR: debug/logs only.

Time unit: milliseconds (simulation time).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

import simpy


# --- constants (ms) ---
SENDER_PREP_MS = 10_000
SENDER_TIMEOUT_MS = 20_000
SERVER_RX_PROCESS_MS = 3_000
RECEIVER_PROCESS_MS = 10_000
SUBNET_DELAY_MS = 3_000


def parse_hms_to_ms(token: str) -> float:
    """Parse timestamps like HH:MM:SS or HH:MM:SS:mmm to milliseconds."""
    parts = token.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp '{token}'")

    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= mmm < 1000 and hh >= 0):
        raise ValueError(f"Invalid timestamp '{token}'")

    return float((((hh * 60) + mm) * 60 + ss) * 1000 + mmm)


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, type_: str, val: Dict[str, Any]) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": type_,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")


class Subnet:
    """Reliable FIFO link with fixed propagation delay."""

    def __init__(self, env: simpy.Environment, delay_ms: int, out_store: simpy.Store):
        self.env = env
        self.delay_ms = delay_ms
        self._in = simpy.Store(env)
        self._out = out_store
        self.env.process(self._run())

    def send(self, msg: Dict[str, Any]):
        return self._in.put(msg)

    def _run(self):
        while True:
            msg = yield self._in.get()  # FIFO
            yield self.env.timeout(self.delay_ms)
            yield self._out.put(msg)


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_out: Subnet,
        ack_in: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in

        self.total_packets_to_send: int = 0
        self.seq: int = 1
        self.bit: int = 0

        self._wakeup: simpy.Event = env.event()
        self.env.process(self._run())

    def control(self, n: int) -> None:
        if n <= 0:
            return
        self.total_packets_to_send += int(n)
        self.emitter.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.total_packets_to_send)},
        )
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _sleep_until_wakeup(self):
        self._wakeup = self.env.event()
        return self._wakeup

    def _run(self):
        while True:
            if self.total_packets_to_send <= 0:
                yield self._sleep_until_wakeup()
                continue

            # Preparation (once per busy period)
            self.emitter.emit(
                "sender",
                "preparation_started",
                {"duration": SENDER_PREP_MS},
            )
            yield self.env.timeout(SENDER_PREP_MS)

            while self.total_packets_to_send > 0:
                yield from self._send_one()

    def _send_one(self):
        is_retry = False
        while True:
            self.emitter.emit(
                "sender",
                "packet_sent",
                {"seq": int(self.seq), "bit": int(self.bit), "is_retry": bool(is_retry)},
            )
            yield self.data_out.send({"seq": int(self.seq), "bit": int(self.bit)})

            ack_get = self.ack_in.get()
            timeout = self.env.timeout(SENDER_TIMEOUT_MS)
            res = yield simpy.events.AnyOf(self.env, [ack_get, timeout])

            if timeout in res.events:
                # Cancel the pending StoreGet to avoid leaking consumers.
                ack_get.cancel()
                self.emitter.emit("sender", "timeout", {"seq": int(self.seq)})
                is_retry = True
                continue

            # ACK arrived first.
            ack = res[ack_get]
            ack_bit = int(ack.get("bit"))

            # Only accept the expected ACK bit.
            if ack_bit != self.bit:
                is_retry = True
                continue

            self.emitter.emit("sender", "ack_received", {"bit": int(ack_bit)})
            self.bit ^= 1
            self.seq += 1
            self.total_packets_to_send -= 1
            return


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: simpy.Store,
        ack_out: Subnet,
        storage: Deque[Dict[str, Any]],
        storage_changed: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage = storage
        self.storage_changed = storage_changed
        self.expected_bit = 0
        self.env.process(self._run())

    def _poke_storage_changed(self) -> None:
        # Non-blocking notification; if nobody waits it's still fine.
        self.storage_changed.put(1)

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            seq, bit = int(pkt["seq"]), int(pkt["bit"])
            self.emitter.emit("server_receiver", "packet_received", {"seq": seq, "bit": bit})

            yield self.env.timeout(SERVER_RX_PROCESS_MS)

            if bit == self.expected_bit:
                # correct in-order
                ack_bit = bit
                self.emitter.emit(
                    "server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)}
                )
                yield self.ack_out.send({"bit": int(ack_bit)})

                self.storage.append({"seq": seq, "bit": bit})
                self._poke_storage_changed()
                self.expected_bit ^= 1
            else:
                # duplicate/out-of-order for ABP: ACK last accepted bit
                ack_bit = 1 - self.expected_bit
                self.emitter.emit(
                    "server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)}
                )
                yield self.ack_out.send({"bit": int(ack_bit)})


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: simpy.Store,
        ack_out: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self.expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            seq, bit = int(pkt["seq"]), int(pkt["bit"])

            if bit != self.expected_bit:
                # ABP duplicate: resend ACK for previous bit immediately (no processing)
                ack_bit = 1 - self.expected_bit
                self.emitter.emit("receiver", "ack_sent", {"bit": int(ack_bit)})
                yield self.ack_out.send({"bit": int(ack_bit)})
                continue

            self.emitter.emit(
                "receiver",
                "processing_started",
                {"seq": int(seq), "duration": RECEIVER_PROCESS_MS},
            )
            yield self.env.timeout(RECEIVER_PROCESS_MS)

            ack_bit = bit
            self.emitter.emit("receiver", "ack_sent", {"bit": int(ack_bit)})
            yield self.ack_out.send({"bit": int(ack_bit)})
            self.expected_bit ^= 1


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        storage: Deque[Dict[str, Any]],
        storage_changed: simpy.Store,
        data_out: Subnet,
        ack_in: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.storage = storage
        self.storage_changed = storage_changed
        self.data_out = data_out
        self.ack_in = ack_in

        self.download_allowed: bool = False
        self.bit: int = 0

        self._wakeup: simpy.Event = env.event()
        self.env.process(self._run())
        self.env.process(self._watch_storage())

    def _sleep_until_wakeup(self):
        self._wakeup = self.env.event()
        return self._wakeup

    def _poke(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _watch_storage(self):
        """Bridge storage-changed notifications into this sender's wakeup."""
        while True:
            _ = yield self.storage_changed.get()
            self._poke()

    def set_download_allowed(self, allowed: bool) -> None:
        self.download_allowed = bool(allowed)
        self.emitter.emit(
            "server_sender",
            "download_valve_change",
            {"allowed": bool(self.download_allowed)},
        )
        self._poke()

    def _run(self):
        while True:
            if not self.download_allowed or not self.storage:
                yield self._sleep_until_wakeup()
                continue

            pkt = self.storage.popleft()
            yield from self._send_abp(pkt)

    def _send_abp(self, pkt: Dict[str, Any]):
        seq = int(pkt["seq"])
        while True:
            self.emitter.emit(
                "server_sender",
                "packet_forwarded",
                {"seq": int(seq), "bit": int(self.bit)},
            )
            yield self.data_out.send({"seq": int(seq), "bit": int(self.bit)})

            ack = yield self.ack_in.get()
            ack_bit = int(ack.get("bit"))
            if ack_bit != self.bit:
                continue

            self.emitter.emit(
                "server_sender",
                "ack_received_from_receiver",
                {"bit": int(ack_bit)},
            )
            self.bit ^= 1
            return


def read_commands_from_stdin(logger: logging.Logger) -> list[Tuple[float, str, int]]:
    cmds: list[Tuple[float, str, int]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            logger.warning("Ignoring malformed line: %r", line)
            continue
        t_s, typ, val_s = parts
        try:
            t_ms = parse_hms_to_ms(t_s)
            val = int(val_s)
        except Exception as e:
            logger.warning("Ignoring line %r due to parse error: %s", line, e)
            continue
        if typ not in ("control", "request"):
            logger.warning("Ignoring unknown command type %r", typ)
            continue
        cmds.append((t_ms, typ, val))

    cmds.sort(key=lambda x: x[0])
    return cmds


def schedule_commands(
    env: simpy.Environment,
    cmds: list[Tuple[float, str, int]],
    sender: Sender,
    server_sender: ServerSender,
):
    def at(t_ms: float, fn, *args):
        def _proc():
            if t_ms > env.now:
                yield env.timeout(t_ms - env.now)
            fn(*args)

        env.process(_proc())

    for t_ms, typ, val in cmds:
        if typ == "control":
            at(t_ms, sender.control, val)
        elif typ == "request":
            at(t_ms, server_sender.set_download_allowed, bool(val))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ABP Dropbox-like sync DES")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (simulation time).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    logger = logging.getLogger("sim")

    args = build_arg_parser().parse_args(argv)
    sim_time = float(args.simulation_time)
    if sim_time < 0:
        raise SystemExit("--simulation_time must be non-negative")

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    storage: Deque[Dict[str, Any]] = deque()
    # Notification channel (server_receiver -> server_sender)
    storage_changed = simpy.Store(env)

    sender_ack_in = simpy.Store(env)
    server_rx_in = simpy.Store(env)
    receiver_in = simpy.Store(env)
    server_sender_ack_in = simpy.Store(env)

    subnet_a1 = Subnet(env, SUBNET_DELAY_MS, server_rx_in)
    subnet_a2 = Subnet(env, SUBNET_DELAY_MS, sender_ack_in)
    subnet_b1 = Subnet(env, SUBNET_DELAY_MS, receiver_in)
    subnet_b2 = Subnet(env, SUBNET_DELAY_MS, server_sender_ack_in)

    sender = Sender(env, emitter, subnet_a1, sender_ack_in)
    _server_receiver = ServerReceiver(env, emitter, server_rx_in, subnet_a2, storage, storage_changed)
    _receiver = Receiver(env, emitter, receiver_in, subnet_b2)
    server_sender = ServerSender(env, emitter, storage, storage_changed, subnet_b1, server_sender_ack_in)

    cmds = read_commands_from_stdin(logger)
    schedule_commands(env, cmds, sender, server_sender)

    env.run(until=sim_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
