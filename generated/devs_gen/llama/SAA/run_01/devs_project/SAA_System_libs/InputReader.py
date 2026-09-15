"""Complete pattern: Read a timestamped request file and emit events."""

import sys
import argparse

from xdevs.models import Atomic, Coupled, Port


class InputReader(Atomic):
    """Read a timestamped request file once and emit events."""

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_fact_out"))

        self.input_file = input_file
        self.request_list = []

    def _read_schedule(self) -> None:
        try:
            with open(self.input_file, 'r') as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    fields = line.split()
                    if len(fields) != 3:
                        continue
                    try:
                        time_fields = fields[0].split(":")
                        if len(time_fields) not in (3, 4):
                            continue
                        hours, minutes, seconds = (int(part) for part in time_fields[:3])
                        fraction = float(f"0.{time_fields[3]}") if len(time_fields) == 4 else 0.0
                        event_time = hours * 3600.0 + minutes * 60.0 + seconds + fraction
                        port = int(fields[1])
                        value = int(fields[2])
                        self.request_list.append((event_time, port, value))
                    except ValueError:
                        continue
        except FileNotFoundError:
            print(f"Error: File '{self.input_file}' not found.", file=sys.stderr)
            sys.exit(1)

    def initialize(self):
        self._read_schedule()
        if not self.request_list:
            self.passivate("DONE")
            return
        self.request_list.sort(key=lambda item: item[0])
        self.hold_in("EMIT", max(0.0, self.request_list[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, port, value = self.request_list[0]
            self.output["request_out"].add({
                'input_time': event_time,
                'port': port,
                'value': value
            })
            self.output["input_fact_out"].add({
                'time': event_time,
                'component': 'input_reader',
                'message': f"{port} {value}"
            })

    def deltint(self):
        self.request_list.pop(0)
        if not self.request_list:
            self.passivate("DONE")
            return
        next_time, _, _ = self.request_list[0]
        self.hold_in("EMIT", max(0.0, next_time - self.request_list[0][0]))

    def exit(self):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_file", required=True)
    args = parser.parse_args()
    input_reader = InputReader("InputReader", None, args.input_file)
    input_reader.initialize()

if __name__ == "__main__":
    main()