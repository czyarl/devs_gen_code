#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Optional import (listed in allowed libs). Not required for this SimPy-based solution.
try:
    import xdevs  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None


# -----------------------------
# Utilities
# -----------------------------
def parse_time_to_ms(token: str) -> int:
    """
    Accepts:
      - HH:MM:SS
      - HH:MM:SS:mmm
    Returns integer milliseconds.
    """
    parts = token.strip().split(":")
    if len(parts) == 3:
        hh, mm, ss = parts
        mmm = "0"
    elif len(parts) == 4:
        hh, mm, ss, mmm = parts
    else:
        raise ValueError(f"Invalid time token: {token}")

    hh_i = int(hh)
    mm_i = int(mm)
    ss_i = int(ss)
    mmm_i = int(mmm)

    total_ms = ((hh_i * 3600 + mm_i * 60 + ss_i) * 1000) + mmm_i
    return total_ms


class EventLogger:
    """
    Writes required JSONL events to stdout ONLY.
    """
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, etype: str, val: dict):
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": etype,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        # flushing helps in streaming checkers; still fast enough for this workload
        sys.stdout.flush()


class Trigger:
    """
    A simple wakeup trigger: processes can yield on .event.
    Calling .fire() wakes them; a new event is created afterward.
    """
    def __init__(self, env: simpy.Environment):
        self.env = env
        self._event = env.event()

    @property
    def event(self):
        return self._event

    def fire(self):
        if not self._event.triggered:
            self._event.succeed()
        # create a fresh event for future waits
        self._event = self.env.event()


# -----------------------------
# Network Subnet (FIFO, reliable, fixed delay)
# -----------------------------
class Subnet:
    def __init__(self, env: simpy.Environment, name: str, delay_ms: int, in_store: simpy.Store, out_store: simpy.Store):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.in_store = in_store
        self.out_store = out_store
        self.proc = env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.in_store.get()
            yield self.env.timeout(self.delay_ms)
            yield self.out_store.put(msg)


# -----------------------------
# Storage Queue (server internal buffer)
# -----------------------------
class StorageQueue:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self._q = deque()
        self.changed = Trigger(env)

    def put(self, item):
        self._q.append(item)
        self.changed.fire()

    def put_left(self, item):
        self._q.appendleft(item)
        self.changed.fire()

    def empty(self) -> bool:
        return len(self._q) == 0

    def pop_left(self):
        item = self._q.popleft()
        self.changed.fire()
        return item

    def __len__(self):
        return len(self._q)


# -----------------------------
# Sender (Uploader ABP)
# -----------------------------
class Sender:
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 out_to_subnet_a1: simpy.Store, in_from_subnet_a2: simpy.Store):
        self.env = env
        self.log = logger
        self.out_a1 = out_to_subnet_a1
        self.in_a2 = in_from_subnet_a2

        self.packets_remaining = 0
        self.current_bit = 0
        self.next_seq = 1

        self._wakeup = Trigger(env)
        self._active_proc = None

        # Parameters (ms)
        self.PREPARE_MS = 10_000
        self.TIMEOUT_MS = 20_000

    def add_packets(self, n: int):
        if n <= 0:
            return
        self.packets_remaining += n
        self.log.emit("sender", "control_cmd", {"added": int(n), "total_remaining": int(self.packets_remaining)})
        self._wakeup.fire()
        if self._active_proc is None or self._active_proc.triggered:
            self._active_proc = self.env.process(self._run())

    def _wait_for_correct_ack(self, expected_bit: int, timeout_ms: int):
        start = self.env.now
        while True:
            elapsed = self.env.now - start
            remaining = timeout_ms - elapsed
            if remaining <= 0:
                return None

            ack_get = self.in_a2.get()
            timeout_ev = self.env.timeout(remaining)
            res = yield (ack_get | timeout_ev)
            if timeout_ev in res:
                return None

            ack = res[ack_get]
            if ack.get("kind") != "ack":
                continue
            if ack.get("bit") == expected_bit:
                return ack
            # wrong-bit ack (duplicate/old): ignore and continue waiting (no event required)

    def _run(self):
        # This process runs while there is work; goes idle when empty.
        while True:
            if self.packets_remaining <= 0:
                # idle until new control arrives
                yield self._wakeup.event
                continue

            # preparation step at the beginning of each active job segment (from idle to active)
            self.log.emit("sender", "preparation_started", {"duration": int(self.PREPARE_MS)})
            yield self.env.timeout(self.PREPARE_MS)

            # send until queue drained
            while self.packets_remaining > 0:
                seq = self.next_seq
                bit = self.current_bit

                is_retry = False
                while True:
                    # send DATA
                    msg = {"kind": "data", "seq": int(seq), "bit": int(bit)}
                    self.log.emit("sender", "packet_sent", {"seq": int(seq), "bit": int(bit), "is_retry": bool(is_retry)})
                    yield self.out_a1.put(msg)

                    ack = yield from self._wait_for_correct_ack(bit, self.TIMEOUT_MS)
                    if ack is None:
                        self.log.emit("sender", "timeout", {"seq": int(seq)})
                        is_retry = True
                        continue

                    self.log.emit("sender", "ack_received", {"bit": int(bit)})
                    break  # packet successfully acknowledged

                # success => next packet
                self.packets_remaining -= 1
                self.current_bit ^= 1
                self.next_seq += 1

            # loop back: if more packets were added during sending, it continues immediately
            # without extra prep (this matches "extends current job").


# -----------------------------
# Server Receiver (Ingress ABP receiver)
# -----------------------------
class ServerReceiver:
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 in_from_subnet_a1: simpy.Store, out_to_subnet_a2: simpy.Store,
                 storage: StorageQueue):
        self.env = env
        self.log = logger
        self.in_a1 = in_from_subnet_a1
        self.out_a2 = out_to_subnet_a2
        self.storage = storage

        self.expected_bit = 0
        self.PROCESS_MS = 3_000

        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_a1.get()
            if pkt.get("kind") != "data":
                continue

            seq = int(pkt["seq"])
            bit = int(pkt["bit"])
            self.log.emit("server_receiver", "packet_received", {"seq": seq, "bit": bit})

            # processing delay
            yield self.env.timeout(self.PROCESS_MS)

            if bit == self.expected_bit:
                # correct new packet
                ack_bit = bit
                yield self.out_a2.put({"kind": "ack", "bit": int(ack_bit)})
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})

                # push into server storage queue (payload keeps original seq for observability)
                self.storage.put({"payload_seq": seq})
                self.expected_bit ^= 1
            else:
                # duplicate => resend previous ACK (standard ABP behavior)
                prev_bit = 1 - self.expected_bit
                yield self.out_a2.put({"kind": "ack", "bit": int(prev_bit)})
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(prev_bit)})


# -----------------------------
# Server Sender (Egress ABP sender)
# -----------------------------
class ServerSender:
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 storage: StorageQueue,
                 out_to_subnet_b1: simpy.Store, in_from_subnet_b2: simpy.Store):
        self.env = env
        self.log = logger
        self.storage = storage
        self.out_b1 = out_to_subnet_b1
        self.in_b2 = in_from_subnet_b2

        self.download_allowed = False
        self.current_bit = 0

        self._wakeup = Trigger(env)
        self.proc = env.process(self._run())

    def set_download_allowed(self, allowed: bool):
        self.download_allowed = bool(allowed)
        self.log.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        self._wakeup.fire()

    def _wait_for_correct_ack(self, expected_bit: int):
        while True:
            ack = yield self.in_b2.get()
            if ack.get("kind") != "ack":
                continue
            if int(ack.get("bit")) == int(expected_bit):
                return ack
            # wrong-bit ack ignored (no event required)

    def _run(self):
        while True:
            # wait for conditions: allowed AND storage not empty
            while (not self.download_allowed) or self.storage.empty():
                # wake on either storage change or download valve change
                res = yield (self._wakeup.event | self.storage.changed.event)
                # normalize: after any wake, just loop and re-check conditions
                if self._wakeup.event in res:
                    self._wakeup.fire()  # reset
                if self.storage.changed.event in res:
                    self.storage.changed.fire()  # reset

            # We may have become disallowed between wake and now; check again
            if not self.download_allowed:
                continue
            if self.storage.empty():
                continue

            # pop one payload item; if valve flips off right now, we put it back left.
            item = self.storage.pop_left()
            if not self.download_allowed:
                self.storage.put_left(item)
                continue

            payload_seq = int(item["payload_seq"])
            bit = int(self.current_bit)

            # send DATA over B1
            yield self.out_b1.put({"kind": "data", "seq": payload_seq, "bit": bit})
            self.log.emit("server_sender", "packet_forwarded", {"seq": payload_seq, "bit": bit})

            # Graceful stop requirement: if request becomes 0 during transfer, still finish this cycle.
            ack = yield from self._wait_for_correct_ack(bit)
            _ = ack
            self.log.emit("server_sender", "ack_received_from_receiver", {"bit": bit})

            self.current_bit ^= 1
            # continue; if download_allowed became False while waiting, loop will stop before next packet


# -----------------------------
# Receiver (Downloader)
# -----------------------------
class Receiver:
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 in_from_subnet_b1: simpy.Store, out_to_subnet_b2: simpy.Store):
        self.env = env
        self.log = logger
        self.in_b1 = in_from_subnet_b1
        self.out_b2 = out_to_subnet_b2

        self.PROCESS_MS = 10_000
        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_b1.get()
            if pkt.get("kind") != "data":
                continue

            seq = int(pkt["seq"])
            bit = int(pkt["bit"])
            self.log.emit("receiver", "processing_started", {"seq": seq, "duration": int(self.PROCESS_MS)})

            yield self.env.timeout(self.PROCESS_MS)

            yield self.out_b2.put({"kind": "ack", "bit": bit})
            self.log.emit("receiver", "ack_sent", {"bit": bit})


# -----------------------------
# Input scheduling
# -----------------------------
def read_commands_from_stdin():
    """
    Reads stdin line-by-line:
      HH:MM:SS type value
      HH:MM:SS:mmm type value
    Returns list of (t_ms, type, value_int).
    """
    commands = []
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid command line (expected 3 tokens): {line}")
        t_token, typ, val_token = parts
        t_ms = parse_time_to_ms(t_token)
        val = int(val_token)
        if typ not in ("control", "request"):
            raise ValueError(f"Unknown command type '{typ}' in line: {line}")
        commands.append((t_ms, typ, val))
    commands.sort(key=lambda x: x[0])
    return commands


def command_scheduler(env: simpy.Environment, commands, sender: Sender, server_sender: ServerSender, sim_end_ms: float):
    """
    A SimPy process that injects commands at scheduled simulation times.
    """
    def _proc():
        for t_ms, typ, val in commands:
            if t_ms > sim_end_ms:
                continue
            # wait until command time
            if t_ms < env.now:
                # if inputs are out-of-order / in the past, execute immediately
                pass
            else:
                yield env.timeout(t_ms - env.now)

            if typ == "control":
                sender.add_packets(val)
            elif typ == "request":
                server_sender.set_download_allowed(val == 1)
        # no further action; simulation continues until time limit
    return env.process(_proc())


# -----------------------------
# Main
# -----------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Dropbox-like sync simulation with two ABP loops (SimPy).")
    parser.add_argument("--simulation_time", type=float, default=10000_000.0,
                        help="Simulation duration in milliseconds (simulation time). Default: 10000000.0")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    sim_end_ms = float(args.simulation_time)
    if sim_end_ms < 0:
        raise ValueError("--simulation_time must be non-negative")

    env = simpy.Environment()
    logger = EventLogger(env)

    # Stores / channels
    # Loop A (Upload)
    sender_to_a1 = simpy.Store(env)
    a1_to_server = simpy.Store(env)
    server_to_a2 = simpy.Store(env)
    a2_to_sender = simpy.Store(env)

    # Loop B (Download)
    server_to_b1 = simpy.Store(env)
    b1_to_receiver = simpy.Store(env)
    receiver_to_b2 = simpy.Store(env)
    b2_to_server = simpy.Store(env)

    # Subnets: reliable FIFO 3s delay
    Subnet(env, "A1", 3_000, sender_to_a1, a1_to_server)
    Subnet(env, "A2", 3_000, server_to_a2, a2_to_sender)
    Subnet(env, "B1", 3_000, server_to_b1, b1_to_receiver)
    Subnet(env, "B2", 3_000, receiver_to_b2, b2_to_server)

    # Server storage
    storage = StorageQueue(env)

    # Entities
    sender = Sender(env, logger, out_to_subnet_a1=sender_to_a1, in_from_subnet_a2=a2_to_sender)
    server_receiver = ServerReceiver(env, logger, in_from_subnet_a1=a1_to_server, out_to_subnet_a2=server_to_a2, storage=storage)
    _ = server_receiver  # silence unused warnings

    server_sender = ServerSender(env, logger, storage=storage, out_to_subnet_b1=server_to_b1, in_from_subnet_b2=b2_to_server)
    receiver = Receiver(env, logger, in_from_subnet_b1=b1_to_receiver, out_to_subnet_b2=receiver_to_b2)
    _ = receiver

    # Read and schedule commands
    try:
        commands = read_commands_from_stdin()
    except Exception as e:
        logging.error("Failed to parse stdin commands: %s", e)
        raise

    command_scheduler(env, commands, sender, server_sender, sim_end_ms)

    # Run simulation (discrete-event, no real time)
    env.run(until=sim_end_ms)


if __name__ == "__main__":
    main()