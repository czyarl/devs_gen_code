#!/usr/bin/env python3
"""
Final verification script for O-Train simulation
"""

import subprocess
import sys
import json

def verify_simulation():
    """Run comprehensive verification of the simulation."""
    print("=" * 70, file=sys.stderr)
    print("O-TRAIN SIMULATION - FINAL VERIFICATION", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    
    # Test 1: Run simulation for 30 seconds
    print("\n[TEST 1] Running simulation for 30 seconds...", file=sys.stderr)
    result = subprocess.run(
        [sys.executable, 'run.py', '--simulate_time', '00:00:30:000'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"✗ FAILED: Simulation exited with code {result.returncode}", file=sys.stderr)
        print(f"Stderr: {result.stderr}", file=sys.stderr)
        return False
    print("✓ PASSED: Simulation completed successfully", file=sys.stderr)
    
    # Test 2: Parse JSONL output
    print("\n[TEST 2] Parsing JSONL output...", file=sys.stderr)
    events = []
    for line in result.stdout.strip().split('\n'):
        if line:
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError as e:
                print(f"✗ FAILED: Invalid JSON: {e}", file=sys.stderr)
                return False
    print(f"✓ PASSED: Parsed {len(events)} events", file=sys.stderr)
    
    # Test 3: Validate event structure
    print("\n[TEST 3] Validating event structure...", file=sys.stderr)
    required_fields = ['time', 'event', 'entity_type', 'station_id', 'station', 'payload']
    valid_count = 0
    for event in events:
        if all(field in event for field in required_fields):
            valid_count += 1
    if valid_count == len(events):
        print(f"✓ PASSED: All {len(events)} events have valid structure", file=sys.stderr)
    else:
        print(f"✗ FAILED: Only {valid_count}/{len(events)} events have valid structure", file=sys.stderr)
        return False
    
    # Test 4: Check event types
    print("\n[TEST 4] Checking event types...", file=sys.stderr)
    event_types = set(e['event'] for e in events)
    expected_types = {'passenger_generated', 'train_arrival', 'passenger_boarding', 'passenger_exiting'}
    if event_types == expected_types:
        print(f"✓ PASSED: All required event types present: {event_types}", file=sys.stderr)
    else:
        print(f"✗ FAILED: Event types mismatch", file=sys.stderr)
        print(f"  Expected: {expected_types}", file=sys.stderr)
        print(f"  Got: {event_types}", file=sys.stderr)
        return False
    
    # Test 5: Check initial passengers
    print("\n[TEST 5] Checking initial passengers at t=0.5...", file=sys.stderr)
    initial_passengers = [e for e in events if e['event'] == 'passenger_generated' and e['time'] == 0.5]
    if len(initial_passengers) == 5:
        print(f"✓ PASSED: Found 5 initial passengers at t=0.5", file=sys.stderr)
        for p in initial_passengers:
            print(f"  - {p['station']}: passenger_id={p['payload']['passenger_id']}", file=sys.stderr)
    else:
        print(f"✗ FAILED: Expected 5 initial passengers, found {len(initial_passengers)}", file=sys.stderr)
        return False
    
    # Test 6: Check train arrival at t=0
    print("\n[TEST 6] Checking train arrival at t=0...", file=sys.stderr)
    train_arrivals = [e for e in events if e['event'] == 'train_arrival' and e['time'] == 0.0]
    if len(train_arrivals) == 1 and train_arrivals[0]['station'] == 'Bayview':
        print(f"✓ PASSED: Train arrived at Bayview at t=0", file=sys.stderr)
    else:
        print(f"✗ FAILED: Expected train arrival at Bayview at t=0", file=sys.stderr)
        return False
    
    # Test 7: Check station coverage
    print("\n[TEST 7] Checking station coverage...", file=sys.stderr)
    stations = set(e['station'] for e in events)
    expected_stations = {'Bayview', 'Carling', 'Carleton', 'Confed', 'Greenboro'}
    if stations == expected_stations:
        print(f"✓ PASSED: All 5 stations present in events", file=sys.stderr)
    else:
        print(f"✗ FAILED: Station coverage incomplete", file=sys.stderr)
        return False
    
    # Test 8: Check entity types
    print("\n[TEST 8] Checking entity types...", file=sys.stderr)
    entity_types = set(e['entity_type'] for e in events)
    expected_entities = {'passenger_generator', 'train', 'station_queue', 'train_queue'}
    if entity_types == expected_entities:
        print(f"✓ PASSED: All required entity types present: {entity_types}", file=sys.stderr)
    else:
        print(f"✗ FAILED: Entity types mismatch", file=sys.stderr)
        return False
    
    # Test 9: Check passenger IDs
    print("\n[TEST 9] Checking passenger IDs...", file=sys.stderr)
    initial_ids = [p['payload']['passenger_id'] for p in initial_passengers]
    if all(pid == 0 for pid in initial_ids):
        print(f"✓ PASSED: All initial passengers have ID=0", file=sys.stderr)
    else:
        print(f"✗ FAILED: Initial passengers should have ID=0", file=sys.stderr)
        return False
    
    # Test 10: Check time ordering
    print("\n[TEST 10] Checking time ordering...", file=sys.stderr)
    times = [e['time'] for e in events]
    if times == sorted(times):
        print(f"✓ PASSED: Events are in chronological order", file=sys.stderr)
    else:
        print(f"✗ FAILED: Events are not in chronological order", file=sys.stderr)
        return False
    
    # Summary
    print("\n" + "=" * 70, file=sys.stderr)
    print("VERIFICATION SUMMARY", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"✓ All 10 tests PASSED", file=sys.stderr)
    print(f"✓ Total events generated: {len(events)}", file=sys.stderr)
    print(f"✓ Event types: {len(event_types)}", file=sys.stderr)
    print(f"✓ Stations covered: {len(stations)}", file=sys.stderr)
    print(f"✓ Entity types: {len(entity_types)}", file=sys.stderr)
    print("\nSample events (first 5):", file=sys.stderr)
    for i, event in enumerate(events[:5]):
        print(f"  {i+1}. {event['event']:20s} at t={event['time']:7.3f} - {event['station']:10s}", file=sys.stderr)
    
    print("\n" + "=" * 70, file=sys.stderr)
    print("✓ O-TRAIN SIMULATION IS READY FOR USE", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    
    return True

if __name__ == '__main__':
    success = verify_simulation()
    sys.exit(0 if success else 1)
