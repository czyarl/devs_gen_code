#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


def parse_timestamp_to_ms(token: str) -> float:
    parts = token.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp format: {token}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60 + ss) * 1000) + ms)


@dataclass(frozen=True)
class DataPacket:
    seq: int
    bit: int


@dataclass(frozen=True)
class AckPacket:
    bit: int


class EventStream:
    def __init__(self, out_stream: Any):
        self._out = out_stream

    def emit(self, *, timestamp_ms: float, model: str, type_: str, val: Dict[str, Any]) -> None:
        obj = {
            "timestamp_ms": float(timestamp_ms),
            "model": model,
            "type": type_,
            "val": val,
        }
        self._out.write(json.dumps(obj) + "\n")


class Link:
    def __init__(self, env: simpy.Environment, delay_ms: float, inbox: simpy.Store, outbox: simpy.Store):
        self.env = env
        self.delay_ms = delay_ms
        self.inbox = inbox
        self.outbox = outbox
        self.proc = env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.inbox.get()
            yield self.env.timeout(self.delay_ms)
            yield self.outbox.put(msg)


class Sender:
    PREP_MS = 10_000
    TIMEOUT_MS = 20_000

    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        outbox: simpy.Store,
        inbox: simpy.Store,
    ):
        self.env = env
        self.events = events
        self.outbox = outbox
        self.inbox = inbox

        self.total_remaining = 0
        self._wakeup = env.event()

        self._seq = 1
        self._bit = 0

        self.proc = env.process(self._run())

    def add_control(self, n: int) -> None:
        if n <= 0:
            return
        self.total_remaining += int(n)
        self.events.emit(
            timestamp_ms=self.env.now,
            model="sender",
            type_="control_cmd",
            val={"added": int(n), "total_remaining": int(self.total_remaining)},
        )
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _wait_until_work(self):
        while self.total_remaining <= 0:
            self._wakeup = self.env.event()
            yield self._wakeup

    def _run(self):
        while True:
            yield from self._wait_until_work()

            self.events.emit(
                timestamp_ms=self.env.now,
                model="sender",
                type_="preparation_started",
                val={"duration": self.PREP_MS},
            )
            yield self.env.timeout(self.PREP_MS)

            while self.total_remaining > 0:
                yield from self._send_one_packet_with_retries()

    def _send_one_packet_with_retries(self):
        is_retry = False
        while True:
            yield self.outbox.put(DataPacket(seq=self._seq, bit=self._bit))
            self.events.emit(
                timestamp_ms=self.env.now,
                model="sender",
                type_="packet_sent",
                val={"seq": int(self._seq), "bit": int(self._bit), "is_retry": bool(is_retry)},
            )

            ack = yield from self._wait_for_ack(expected_bit=self._bit, timeout_ms=self.TIMEOUT_MS)
            if ack is None:
                self.events.emit(
                    timestamp_ms=self.env.now,
                    model="sender",
                    type_="timeout",
                    val={"seq": int(self._seq)},
                )
                is_retry = True
                continue

            self.events.emit(
                timestamp_ms=self.env.now,
                model="sender",
                type_="ack_received",
                val={"bit": int(ack.bit)},
            )
            self._bit ^= 1
            self._seq += 1
            self.total_remaining -= 1
            return

    def _wait_for_ack(self, *, expected_bit: int, timeout_ms: float) -> Any:
        timeout_evt = self.env.timeout(float(timeout_ms))
        while True:
            get_evt = self.inbox.get()
            res = yield get_evt | timeout_evt
            if timeout_evt in res:
                get_evt.cancel()
                return None

            ack = res[get_evt]
            if isinstance(ack, AckPacket) and int(ack.bit) == int(expected_bit):
                return ack


class ServerReceiver:
    PROC_MS = 3_000

    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        inbox: simpy.Store,
        ack_outbox: simpy.Store,
        storage_queue: simpy.Store,
    ):
        self.env = env
        self.events = events
        self.inbox = inbox
        self.ack_outbox = ack_outbox
        self.storage_queue = storage_queue

        self._expected_bit = 0
        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.inbox.get()
            if not isinstance(pkt, DataPacket):
                continue

            self.events.emit(
                timestamp_ms=self.env.now,
                model="server_receiver",
                type_="packet_received",
                val={"seq": int(pkt.seq), "bit": int(pkt.bit)},
            )

            yield self.env.timeout(self.PROC_MS)

            if int(pkt.bit) == int(self._expected_bit):
                ack_bit = int(pkt.bit)
                yield self.ack_outbox.put(AckPacket(bit=ack_bit))
                self.events.emit(
                    timestamp_ms=self.env.now,
                    model="server_receiver",
                    type_="ack_sent_to_sender",
                    val={"bit": int(ack_bit)},
                )
                yield self.storage_queue.put({"seq": int(pkt.seq)})
                self._expected_bit ^= 1
            else:
                ack_bit = 1 - int(self._expected_bit)
                yield self.ack_outbox.put(AckPacket(bit=ack_bit))
                self.events.emit(
                    timestamp_ms=self.env.now,
                    model="server_receiver",
                    type_="ack_sent_to_sender",
                    val={"bit": int(ack_bit)},
                )


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        storage_queue: simpy.Store,
        outbox: simpy.Store,
        inbox: simpy.Store,
    ):
        self.env = env
        self.events = events
        self.storage_queue = storage_queue
        self.outbox = outbox
        self.inbox = inbox

        self.download_allowed = False
        self._wakeup = env.event()

        self._bit = 0
        self._pending_item: Optional[Dict[str, Any]] = None
        self.proc = env.process(self._run())

    def set_download_allowed(self, allowed: bool) -> None:
        self.download_allowed = bool(allowed)
        self.events.emit(
            timestamp_ms=self.env.now,
            model="server_sender",
            type_="download_valve_change",
            val={"allowed": bool(self.download_allowed)},
        )
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _run(self):
        while True:
            if not self.download_allowed:
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            if self._pending_item is None:
                if len(self.storage_queue.items) == 0:
                    self._wakeup = self.env.event()
                    get_evt = self.storage_queue.get()
                    res = yield get_evt | self._wakeup
                    if get_evt in res:
                        self._pending_item = res[get_evt]
                    else:
                        get_evt.cancel()
                    continue
                self._pending_item = yield self.storage_queue.get()

            item = self._pending_item
            seq = int(item["seq"])
            bit = int(self._bit)

            yield self.outbox.put(DataPacket(seq=seq, bit=bit))
            self.events.emit(
                timestamp_ms=self.env.now,
                model="server_sender",
                type_="packet_forwarded",
                val={"seq": int(seq), "bit": int(bit)},
            )

            while True:
                ack = yield self.inbox.get()
                if isinstance(ack, AckPacket) and int(ack.bit) == int(bit):
                    self.events.emit(
                        timestamp_ms=self.env.now,
                        model="server_sender",
                        type_="ack_received_from_receiver",
                        val={"bit": int(ack.bit)},
                    )
                    break

            self._pending_item = None
            self._bit ^= 1

            # graceful stop: if request turned off during transfer, we stop now
            if not self.download_allowed:
                continue


class Receiver:
    PROC_MS = 10_000

    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        inbox: simpy.Store,
        ack_outbox: simpy.Store,
    ):
        self.env = env
        self.events = events
        self.inbox = inbox
        self.ack_outbox = ack_outbox
        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.inbox.get()
            if not isinstance(pkt, DataPacket):
                continue

            self.events.emit(
                timestamp_ms=self.env.now,
                model="receiver",
                type_="processing_started",
                val={"seq": int(pkt.seq), "duration": self.PROC_MS},
            )
            yield self.env.timeout(self.PROC_MS)
            yield self.ack_outbox.put(AckPacket(bit=int(pkt.bit)))
            self.events.emit(
                timestamp_ms=self.env.now,
                model="receiver",
                type_="ack_sent",
                val={"bit": int(pkt.bit)},
            )


def read_commands(stdin: Any, log: logging.Logger) -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for raw in stdin:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: {line}")
        ts_s, typ, val_s = parts
        ts_ms = parse_timestamp_to_ms(ts_s)
        val = int(val_s)
        if typ not in ("control", "request"):
            raise ValueError(f"Invalid command type: {typ}")
        cmds.append((ts_ms, typ, val))

    # stable sort: same timestamps keep stdin order
    cmds.sort(key=lambda x: x[0])
    log.info("Read %d commands", len(cmds))
    return cmds


def schedule_commands(
    env: simpy.Environment,
    commands: List[Tuple[float, str, int]],
    sender: Sender,
    server_sender: ServerSender,
    simulation_time_ms: float,
):
    def _proc():
        for ts_ms, typ, val in commands:
            if ts_ms > simulation_time_ms:
                continue
            now = env.now
            if ts_ms > now:
                yield env.timeout(ts_ms - now)
            if typ == "control":
                sender.add_control(int(val))
            elif typ == "request":
                server_sender.set_download_allowed(bool(int(val)))

    return env.process(_proc())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    log = logging.getLogger("sim")

    simulation_time_ms = float(args.simulation_time)

    env = simpy.Environment()
    events = EventStream(sys.stdout)

    # Channels (stores)
    sender_to_a1 = simpy.Store(env)
    a1_to_server = simpy.Store(env)
    server_to_a2 = simpy.Store(env)
    a2_to_sender = simpy.Store(env)

    server_to_b1 = simpy.Store(env)
    b1_to_receiver = simpy.Store(env)
    receiver_to_b2 = simpy.Store(env)
    b2_to_server = simpy.Store(env)

    storage_queue = simpy.Store(env)

    # Subnets: fixed 3s delay, FIFO
    Link(env, 3_000, sender_to_a1, a1_to_server)
    Link(env, 3_000, server_to_a2, a2_to_sender)
    Link(env, 3_000, server_to_b1, b1_to_receiver)
    Link(env, 3_000, receiver_to_b2, b2_to_server)

    sender = Sender(env, events, outbox=sender_to_a1, inbox=a2_to_sender)
    server_receiver = ServerReceiver(
        env,
        events,
        inbox=a1_to_server,
        ack_outbox=server_to_a2,
        storage_queue=storage_queue,
    )
    server_sender = ServerSender(env, events, storage_queue=storage_queue, outbox=server_to_b1, inbox=b2_to_server)
    receiver = Receiver(env, events, inbox=b1_to_receiver, ack_outbox=receiver_to_b2)

    commands = read_commands(sys.stdin, log)
    schedule_commands(env, commands, sender, server_sender, simulation_time_ms)

    env.run(until=simulation_time_ms)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
