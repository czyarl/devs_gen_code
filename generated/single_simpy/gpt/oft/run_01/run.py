#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import simpy

# Optional import (allowed by requirements). Simulation does not depend on it.
try:
    import xdevs  # noqa: F401
except Exception:
    xdevs = None  # noqa: F841


# ----------------------------
# Utilities
# ----------------------------

def parse_timestamp_to_ms(s: str) -> float:
    """
    Parse:
      HH:MM:SS
      HH:MM:SS:mmm
    into milliseconds (float).
    """
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp format: {s!r}")

    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0

    return float((((hh * 60 + mm) * 60 + ss) * 1000) + mmm)


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: dict):
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val
        }
        sys.stdout.write(json.dumps(obj) + "\n")


# ----------------------------
# Network / Subnet
# ----------------------------

class Subnet:
    """Reliable FIFO link with fixed delay."""
    def __init__(self, env: simpy.Environment, delay_ms: float, in_store: simpy.Store, out_store: simpy.Store, logger: logging.Logger):
        self.env = env
        self.delay_ms = float(delay_ms)
        self.in_store = in_store
        self.out_store = out_store
        self.logger = logger
        self.proc = env.process(self.run())

    def run(self):
        while True:
            msg = yield self.in_store.get()
            yield self.env.timeout(self.delay_ms)
            yield self.out_store.put(msg)


# ----------------------------
# Models
# ----------------------------

class Sender:
    PREP_MS = 10_000.0
    TIMEOUT_MS = 20_000.0

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, out_store: simpy.Store, ack_in: simpy.Store, logger: logging.Logger):
        self.env = env
        self.emitter = emitter
        self.out_store = out_store
        self.ack_in = ack_in
        self.logger = logger

        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0

        self._wake_event = env.event()
        self.proc = env.process(self.run())

    def handle_control(self, added: int):
        if added <= 0:
            return
        was_idle = (self.packets_remaining == 0)
        self.packets_remaining += int(added)
        self.emitter.emit(
            "sender",
            "control_cmd",
            {"added": int(added), "total_remaining": int(self.packets_remaining)}
        )
        if was_idle and not self._wake_event.triggered:
            self._wake_event.succeed()

    def run(self):
        while True:
            if self.packets_remaining <= 0:
                self._wake_event = self.env.event()
                yield self._wake_event

            # Preparation at the start of each "active burst"
            self.emitter.emit("sender", "preparation_started", {"duration": int(self.PREP_MS)})
            yield self.env.timeout(self.PREP_MS)

            while self.packets_remaining > 0:
                yield from self._send_one_packet()

    def _send_one_packet(self):
        current_seq = int(self.seq)
        current_bit = int(self.bit)
        is_retry = False

        while True:
            # Send (or retransmit) current packet
            self.emitter.emit(
                "sender",
                "packet_sent",
                {"seq": current_seq, "bit": current_bit, "is_retry": bool(is_retry)}
            )
            yield self.out_store.put({"kind": "data", "seq": current_seq, "bit": current_bit})

            deadline = float(self.env.now) + self.TIMEOUT_MS

            # Wait for correct ACK until deadline; ignore wrong ACKs without resetting timer
            while True:
                remaining = deadline - float(self.env.now)
                if remaining <= 0:
                    break

                ack_get = self.ack_in.get()
                to = self.env.timeout(remaining)
                res = yield simpy.AnyOf(self.env, [ack_get, to])

                if to in res:
                    # Timeout fired first; cancel pending get to avoid consuming a later ACK
                    try:
                        ack_get.cancel()
                    except Exception:
                        pass
                    break

                # ACK received first
                ack = res[ack_get]
                self.emitter.emit("sender", "ack_received", {"bit": int(ack.get("bit", -1))})

                if ack.get("kind") == "ack" and int(ack.get("bit", -1)) == current_bit:
                    # Success
                    self.bit = 1 - current_bit
                    self.seq += 1
                    self.packets_remaining -= 1
                    return
                # else: wrong/irrelevant ACK, keep waiting until the same deadline

            # Deadline reached => timeout and retransmit
            self.emitter.emit("sender", "timeout", {"seq": current_seq})
            is_retry = True


class ServerReceiver:
    PROCESS_MS = 3_000.0

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        in_store: simpy.Store,
        ack_out: simpy.Store,
        storage: simpy.Store,
        server_sender_notify_cb,
        logger: logging.Logger,
    ):
        self.env = env
        self.emitter = emitter
        self.in_store = in_store
        self.ack_out = ack_out
        self.storage = storage
        self.server_sender_notify_cb = server_sender_notify_cb
        self.logger = logger

        self.expected_bit = 0
        self.proc = env.process(self.run())

    def run(self):
        while True:
            pkt = yield self.in_store.get()
            if pkt.get("kind") != "data":
                continue

            seq = int(pkt["seq"])
            bit = int(pkt["bit"])
            self.emitter.emit("server_receiver", "packet_received", {"seq": seq, "bit": bit})

            yield self.env.timeout(self.PROCESS_MS)

            if bit == self.expected_bit:
                # Correct new packet
                ack_bit = bit
                yield self.ack_out.put({"kind": "ack", "bit": ack_bit})
                self.emitter.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})

                yield self.storage.put({"seq": seq})
                if self.server_sender_notify_cb is not None:
                    self.server_sender_notify_cb()

                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate: resend ACK of last correctly received (previous bit)
                ack_bit = 1 - self.expected_bit
                yield self.ack_out.put({"kind": "ack", "bit": ack_bit})
                self.emitter.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        storage: simpy.Store,
        out_store: simpy.Store,
        ack_in: simpy.Store,
        logger: logging.Logger,
    ):
        self.env = env
        self.emitter = emitter
        self.storage = storage
        self.out_store = out_store
        self.ack_in = ack_in
        self.logger = logger

        self.download_allowed = False
        self.bit = 0

        self._state_event = env.event()
        self.proc = env.process(self.run())

    def notify(self):
        if not self._state_event.triggered:
            self._state_event.succeed()

    def handle_request(self, val: int):
        allowed = bool(int(val))
        self.download_allowed = allowed
        self.emitter.emit("server_sender", "download_valve_change", {"allowed": bool(allowed)})
        self.notify()

    def run(self):
        while True:
            # Wait until allowed and storage has data
            while not (self.download_allowed and len(self.storage.items) > 0):
                self._state_event = self.env.event()
                yield self._state_event

            item = yield self.storage.get()
            seq = int(item["seq"])
            bit = int(self.bit)

            # Forward immediately (no processing delay)
            yield self.out_store.put({"kind": "data", "seq": seq, "bit": bit})
            self.emitter.emit("server_sender", "packet_forwarded", {"seq": seq, "bit": bit})

            # Wait for matching ACK (ignore mismatched ACKs)
            while True:
                ack = yield self.ack_in.get()
                if ack.get("kind") != "ack":
                    continue
                ack_bit = int(ack.get("bit", -1))
                self.emitter.emit("server_sender", "ack_received_from_receiver", {"bit": ack_bit})
                if ack_bit == self.bit:
                    self.bit = 1 - self.bit
                    break
                # else ignore and keep waiting (no retransmit needed in reliable subnet)


class Receiver:
    PROCESS_MS = 10_000.0

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, in_store: simpy.Store, ack_out: simpy.Store, logger: logging.Logger):
        self.env = env
        self.emitter = emitter
        self.in_store = in_store
        self.ack_out = ack_out
        self.logger = logger

        self.expected_bit = 0
        self.proc = env.process(self.run())

    def run(self):
        while True:
            pkt = yield self.in_store.get()
            if pkt.get("kind") != "data":
                continue

            seq = int(pkt["seq"])
            bit = int(pkt["bit"])

            if bit == self.expected_bit:
                self.emitter.emit("receiver", "processing_started", {"seq": seq, "duration": int(self.PROCESS_MS)})
                yield self.env.timeout(self.PROCESS_MS)
                yield self.ack_out.put({"kind": "ack", "bit": bit})
                self.emitter.emit("receiver", "ack_sent", {"bit": int(bit)})
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate: immediate ACK of last correct (previous bit)
                ack_bit = 1 - self.expected_bit
                yield self.ack_out.put({"kind": "ack", "bit": ack_bit})
                self.emitter.emit("receiver", "ack_sent", {"bit": int(ack_bit)})


# ----------------------------
# Command scheduling
# ----------------------------

def read_commands_from_stdin(logger: logging.Logger):
    commands = []
    for line_no, raw in enumerate(sys.stdin, 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line {line_no}: {raw!r}")
        ts_s, typ, val_s = parts
        t_ms = parse_timestamp_to_ms(ts_s)
        if typ not in ("control", "request"):
            raise ValueError(f"Invalid command type at line {line_no}: {typ!r}")
        try:
            val = int(val_s)
        except ValueError:
            raise ValueError(f"Invalid value at line {line_no}: {val_s!r}")
        commands.append((t_ms, typ, val))
    commands.sort(key=lambda x: x[0])
    return commands


def command_driver(env: simpy.Environment, commands, sender: Sender, server_sender: ServerSender, logger: logging.Logger):
    current = 0.0
    for t_ms, typ, val in commands:
        if t_ms < current:
            # If inputs are out-of-order, treat as immediate at current time.
            t_ms = current
        yield env.timeout(t_ms - current)
        current = t_ms

        if typ == "control":
            sender.handle_control(val)
        elif typ == "request":
            server_sender.handle_request(val)


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Dropbox-like sync simulation with two ABP loops (SimPy).")
    ap.add_argument("--simulation_time", type=float, default=10000_000.0,
                    help="Simulation duration in milliseconds (simulation time). Default: 10000_000.0")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr
    )
    logger = logging.getLogger("sim")

    try:
        commands = read_commands_from_stdin(logger)
    except Exception as e:
        logger.error("Failed to read stdin commands: %s", e)
        raise

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    # Stores (channels)
    # Sender <-> Server (Subnet A)
    sender_to_a1 = simpy.Store(env)
    a1_to_server = simpy.Store(env)

    server_to_a2 = simpy.Store(env)
    a2_to_sender = simpy.Store(env)

    # Server <-> Receiver (Subnet B)
    server_to_b1 = simpy.Store(env)
    b1_to_receiver = simpy.Store(env)

    receiver_to_b2 = simpy.Store(env)
    b2_to_server = simpy.Store(env)

    # Server storage queue (buffer between upload and download)
    storage = simpy.Store(env)

    # Models
    sender = Sender(env, emitter, out_store=sender_to_a1, ack_in=a2_to_sender, logger=logger)
    server_sender = ServerSender(env, emitter, storage=storage, out_store=server_to_b1, ack_in=b2_to_server, logger=logger)
    server_receiver = ServerReceiver(
        env, emitter,
        in_store=a1_to_server,
        ack_out=server_to_a2,
        storage=storage,
        server_sender_notify_cb=server_sender.notify,
        logger=logger
    )
    receiver = Receiver(env, emitter, in_store=b1_to_receiver, ack_out=receiver_to_b2, logger=logger)

    # Subnets: fixed 3s delay
    Subnet(env, 3_000.0, in_store=sender_to_a1, out_store=a1_to_server, logger=logger)     # A1
    Subnet(env, 3_000.0, in_store=server_to_a2, out_store=a2_to_sender, logger=logger)     # A2
    Subnet(env, 3_000.0, in_store=server_to_b1, out_store=b1_to_receiver, logger=logger)   # B1
    Subnet(env, 3_000.0, in_store=receiver_to_b2, out_store=b2_to_server, logger=logger)   # B2

    # Schedule commands
    env.process(command_driver(env, commands, sender, server_sender, logger))

    # Run
    env.run(until=float(args.simulation_time))


if __name__ == "__main__":
    main()