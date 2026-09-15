#!/usr/bin/env python3
"""Final test to verify simulation works"""
import subprocess
import sys
import json

print("Testing airfreight logistics simulation...")
print("=" * 60)

# Run simulation with short duration
result = subprocess.run(
    [sys.executable, "run.py", "--duration", "200"],
    capture_output=True,
    text=True,
    timeout=15
)

if result.returncode != 0:
    print(f"✗ FAILED: Return code {result.returncode}")
    print(f"STDERR: {result.stderr}")
    sys.exit(1)

print(f"✓ Simulation completed successfully")

# Parse events
events = []
for line in result.stdout.strip().split('\n'):
    if line:
        try:
            event = json.loads(line)
            events.append(event)
        except:
            pass

print(f"✓ Generated {len(events)} events")

# Show event summary
counts = {}
for e in events:
    key = f"{e['entity']}.{e['event']}"
    counts[key] = counts.get(key, 0) + 1

print("\nEvent counts:")
for k, v in sorted(counts.items()):
    print(f"  {k}: {v}")

# Show first few events
print("\nFirst 5 events:")
for i, event in enumerate(events[:5]):
    print(f"  {i+1}. t={event['time']:.1f} | {event['entity']:12} | {event['event']:20}")

print("\n" + "=" * 60)
print("✓ Simulation verified successfully!")
print("=" * 60)
