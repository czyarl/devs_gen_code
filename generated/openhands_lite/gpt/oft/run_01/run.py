#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from collections import namedtuple

import simpy


MS_3S = 3000
MS_10S = 10000
MS_20S = 20000


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: dict) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


class Subnet:
    def __init__(self, env: simpy.Environment, delay_ms: int):
        self.env = env
        self.delay_ms = delay_ms
        self.inp: simpy.Store = simpy.Store(env)
        self.out: simpy.Store = simpy.Store(env)
        env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.inp.get()
            yield self.env.timeout(self.delay_ms)
            yield self.out.put(msg)


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_out: simpy.Store,
        ack_in: simpy.FilterStore,
    ):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in

        self.total_remaining = 0
        self.seq = 1
        self.bit = 0

        self._active = False
        self._wakeup = env.event()
        self._needs_preparation = True
        env.process(self._run())

    def add_control(self, n: int) -> None:
        if n <= 0:
            return
        was_idle = self.total_remaining <= 0
        self.total_remaining += n
        self.emitter.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.total_remaining)},
        )
        if was_idle:
            self._needs_preparation = True

        if not self._active:
            self._active = True
            if not self._wakeup.triggered:
                self._wakeup.succeed()

    def _run(self):
        while True:
            if self.total_remaining <= 0:
                self._active = False
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            if self._needs_preparation:
                self.emitter.emit(
                    "sender",
                    "preparation_started",
                    {"duration": MS_10S},
                )
                yield self.env.timeout(MS_10S)
                self._needs_preparation = False

            while self.total_remaining > 0:
                yield from self._send_one_packet()

    def _send_one_packet(self):
        is_retry = False
        while True:
            self.emitter.emit(
                "sender",
                "packet_sent",
                {"seq": int(self.seq), "bit": int(self.bit), "is_retry": bool(is_retry)},
            )
            yield self.data_out.put({"kind": "data", "seq": int(self.seq), "bit": int(self.bit)})

            expected_bit = int(self.bit)
            ack_ev = self.ack_in.get(
                lambda m, b=expected_bit: m.get("kind") == "ack" and m.get("bit") == b
            )
            timeout_ev = self.env.timeout(MS_20S)

            res = yield ack_ev | timeout_ev
            if ack_ev in res:
                self.emitter.emit("sender", "ack_received", {"bit": int(expected_bit)})
                self.bit ^= 1
                self.seq += 1
                self.total_remaining -= 1
                return

            ack_ev.cancel()
            self.emitter.emit("sender", "timeout", {"seq": int(self.seq)})
            is_retry = True


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: simpy.Store,
        ack_out: simpy.Store,
        storage_queue: simpy.Store,
        notify_storage_put,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage_queue = storage_queue
        self.expected_bit = 0
        self._notify_storage_put = notify_storage_put
        env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if pkt.get("kind") != "data":
                continue

            self.emitter.emit(
                "server_receiver",
                "packet_received",
                {"seq": int(pkt["seq"]), "bit": int(pkt["bit"])},
            )
            yield self.env.timeout(MS_3S)

            bit = int(pkt["bit"])
            if bit == int(self.expected_bit):
                yield self.ack_out.put({"kind": "ack", "bit": bit})
                self.emitter.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(bit)},
                )
                yield self.storage_queue.put({"seq": int(pkt["seq"])})
                self._notify_storage_put()
                self.expected_bit ^= 1
            else:
                prev_bit = 1 - int(self.expected_bit)
                yield self.ack_out.put({"kind": "ack", "bit": int(prev_bit)})
                self.emitter.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(prev_bit)},
                )


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        storage_queue: simpy.Store,
        data_out: simpy.Store,
        ack_in: simpy.FilterStore,
    ):
        self.env = env
        self.emitter = emitter
        self.storage_queue = storage_queue
        self.data_out = data_out
        self.ack_in = ack_in

        self.download_allowed = False
        self._waiting_for_ack = False
        self._wakeup = env.event()

        self.seq_expected_bit = 0
        self.bit = 0

        env.process(self._run())

    def notify(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def set_download_allowed(self, allowed: bool) -> None:
        self.download_allowed = bool(allowed)
        self.emitter.emit(
            "server_sender",
            "download_valve_change",
            {"allowed": bool(self.download_allowed)},
        )
        self.notify()

    def _run(self):
        while True:
            if (not self.download_allowed) or self._waiting_for_ack or (len(self.storage_queue.items) == 0):
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            item = yield self.storage_queue.get()
            seq = int(item["seq"])
            bit = int(self.bit)

            self._waiting_for_ack = True
            self.emitter.emit(
                "server_sender",
                "packet_forwarded",
                {"seq": int(seq), "bit": int(bit)},
            )
            yield self.data_out.put({"kind": "data", "seq": int(seq), "bit": int(bit)})

            ack_msg = yield self.ack_in.get(
                lambda m, b=bit: m.get("kind") == "ack" and m.get("bit") == b
            )
            _ = ack_msg
            self.emitter.emit(
                "server_sender",
                "ack_received_from_receiver",
                {"bit": int(bit)},
            )

            self.bit ^= 1
            self._waiting_for_ack = False
            self.notify()


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: simpy.Store,
        ack_out: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if pkt.get("kind") != "data":
                continue

            self.emitter.emit(
                "receiver",
                "processing_started",
                {"seq": int(pkt["seq"]), "duration": MS_10S},
            )
            yield self.env.timeout(MS_10S)

            bit = int(pkt["bit"])
            yield self.ack_out.put({"kind": "ack", "bit": bit})
            self.emitter.emit("receiver", "ack_sent", {"bit": int(bit)})


Command = namedtuple("Command", ["timestamp_ms", "typ", "value"])
Command.__new__.__defaults__ = (0, "", 0)

def parse_timestamp_ms(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"invalid timestamp: {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return ((hh * 3600 + mm * 60 + ss) * 1000) + ms


def read_commands(stdin, logger: logging.Logger):
    cmds = []
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            logger.warning("Ignoring malformed line: %r", line)
            continue

        ts_s, typ, val_s = parts
        try:
            ts_ms = parse_timestamp_ms(ts_s)
            val = int(val_s)
        except Exception as e:
            logger.warning("Ignoring line (%s): %r", e, line)
            continue

        if typ not in {"control", "request"}:
            logger.warning("Ignoring unknown command type: %r", typ)
            continue

        cmds.append(Command(timestamp_ms=ts_ms, typ=typ, value=val))

    cmds.sort(key=lambda c: c.timestamp_ms)
    return cmds


def schedule_commands(env, cmds, sender, server_sender):
    def do_at(delay_ms, fn):
        yield env.timeout(int(delay_ms))
        fn()

    now0 = int(env.now)
    for c in cmds:
        delay = max(0, int(c.timestamp_ms) - now0)
        if c.typ == "control":
            env.process(do_at(delay, lambda n=c.value: sender.add_control(n)))
        else:
            env.process(do_at(delay, lambda v=c.value: server_sender.set_download_allowed(bool(int(v)))))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SimPy DES model: Dropbox-like sync with two ABP loops")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (default: 10000_000.0)",
    )
    p.add_argument(
        "--log_level",
        type=str,
        default="WARNING",
        help="Logging level to stderr (DEBUG, INFO, WARNING, ERROR)",
    )
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    level_name = str(args.log_level).upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=level, format="%(levelname)s: %(message)s")
    log = logging.getLogger("sim")
    simulation_time_ms = float(args.simulation_time)
    if simulation_time_ms < 0:
        log.error("--simulation_time must be non-negative")
        return 2

    max_simulation_ms = 10000_000.0
    if simulation_time_ms > max_simulation_ms:
        simulation_time_ms = max_simulation_ms

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    # Subnets (reliable FIFO with fixed 3s delay)
    subnet_a1 = Subnet(env, MS_3S)  # Sender -> Server
    subnet_a2 = Subnet(env, MS_3S)  # Server -> Sender
    subnet_b1 = Subnet(env, MS_3S)  # Server -> Receiver
    subnet_b2 = Subnet(env, MS_3S)  # Receiver -> Server

    # Server storage queue
    storage_queue: simpy.Store = simpy.Store(env)

    # Endpoints
    sender_ack_in: simpy.FilterStore = simpy.FilterStore(env)
    server_ack_in: simpy.FilterStore = simpy.FilterStore(env)

    server_sender = ServerSender(
        env=env,
        emitter=emitter,
        storage_queue=storage_queue,
        data_out=subnet_b1.inp,
        ack_in=server_ack_in,
    )

    sender = Sender(
        env=env,
        emitter=emitter,
        data_out=subnet_a1.inp,
        ack_in=sender_ack_in,
    )

    _ = ServerReceiver(
        env=env,
        emitter=emitter,
        data_in=subnet_a1.out,
        ack_out=subnet_a2.inp,
        storage_queue=storage_queue,
        notify_storage_put=server_sender.notify,
    )

    _ = Receiver(
        env=env,
        emitter=emitter,
        data_in=subnet_b1.out,
        ack_out=subnet_b2.inp,
    )

    # Deliver ACKs from subnets into FilterStores
    def forward_store(src: simpy.Store, dst: simpy.Store):
        while True:
            msg = yield src.get()
            yield dst.put(msg)

    env.process(forward_store(subnet_a2.out, sender_ack_in))
    env.process(forward_store(subnet_b2.out, server_ack_in))

    cmds = read_commands(sys.stdin, log)
    schedule_commands(env, cmds, sender, server_sender)

    env.run(until=simulation_time_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
