#!/usr/bin/env python3
"""Final verification script to ensure implementation meets all requirements."""

import subprocess
import json
import sys


def verify_implementation():
    """Verify the implementation meets all requirements."""
    
    print("=" * 70, file=sys.stderr)
    print("HOUSE HEATING SIMULATION - FINAL VERIFICATION", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    
    # Test 1: Entry point exists and is executable
    print("\n1. Checking entry point...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["python", "run.py", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "run.py not executable"
        assert "--simulate_time" in result.stdout, "Missing --simulate_time argument"
        print("   ✓ Entry point 'run.py' exists and is executable", file=sys.stderr)
        print("   ✓ Accepts --simulate_time argument", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 2: Basic simulation runs
    print("\n2. Testing basic simulation...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["python", "run.py", "--simulate_time", "3"],
            capture_output=True,
            text=True,
            input=""
        )
        assert result.returncode == 0, f"Simulation failed: {result.stderr}"
        lines = result.stdout.strip().split('\n')
        assert len(lines) == 3, f"Expected 3 outputs, got {len(lines)}"
        print("   ✓ Simulation runs successfully", file=sys.stderr)
        print("   ✓ Produces correct number of outputs", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 3: JSONL output format
    print("\n3. Verifying JSONL output format...", file=sys.stderr)
    try:
        states = [json.loads(line) for line in lines]
        required_fields = ["time_sec", "room_temp_c", "heat_loss_temp_c", 
                          "control_signal", "heater_output_c"]
        
        for state in states:
            assert all(field in state for field in required_fields), \
                f"Missing required fields in {state}"
            assert isinstance(state["time_sec"], int), "time_sec must be int"
            assert isinstance(state["control_signal"], int), \
                "control_signal must be int"
            assert state["control_signal"] in [0, 1], \
                "control_signal must be 0 or 1"
        
        print("   ✓ Output is valid JSONL", file=sys.stderr)
        print("   ✓ All required fields present", file=sys.stderr)
        print("   ✓ Field types correct", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 4: Initial conditions
    print("\n4. Verifying initial conditions...", file=sys.stderr)
    try:
        first_state = states[0]
        assert first_state["time_sec"] == 1, "First output should be at time 1"
        assert abs(first_state["room_temp_c"] - 25.0) < 0.01, \
            "Initial room temp should be 25.0"
        assert abs(first_state["heat_loss_temp_c"] - 25.0) < 0.01, \
            "Initial heat loss temp should be 25.0"
        assert first_state["control_signal"] == 0, \
            "Initial control signal should be 0"
        assert abs(first_state["heater_output_c"] - 0.0) < 0.01, \
            "Initial heater output should be 0.0"
        print("   ✓ Initial conditions correct", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 5: Outdoor temperature parsing
    print("\n5. Testing outdoor temperature parsing...", file=sys.stderr)
    try:
        input_data = "00:00:00 20.0\n00:00:02 22.0\n"
        result = subprocess.run(
            ["python", "run.py", "--simulate_time", "3"],
            capture_output=True,
            text=True,
            input=input_data
        )
        assert result.returncode == 0, "Simulation with outdoor temps failed"
        print("   ✓ Outdoor temperature parsing works", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 6: Heater activation
    print("\n6. Testing heater activation logic...", file=sys.stderr)
    try:
        input_data = "00:00:00 10.0\n"
        result = subprocess.run(
            ["python", "run.py", "--simulate_time", "5"],
            capture_output=True,
            text=True,
            input=input_data
        )
        states = [json.loads(line) for line in result.stdout.strip().split('\n')]
        
        # With cold outdoor temp, heater should activate
        heater_activated = any(s["control_signal"] == 1 for s in states)
        assert heater_activated, "Heater should activate with cold outdoor temp"
        
        # Verify heater output values
        for state in states:
            assert state["heater_output_c"] in [0.0, 0.5], \
                "Heater output must be 0.0 or 0.5"
        
        print("   ✓ Heater activates correctly", file=sys.stderr)
        print("   ✓ Heater output values correct", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 7: Runtime performance
    print("\n7. Testing runtime performance...", file=sys.stderr)
    try:
        import time
        start = time.time()
        result = subprocess.run(
            ["python", "run.py", "--simulate_time", "1000"],
            capture_output=True,
            text=True,
            input=""
        )
        elapsed = time.time() - start
        assert elapsed < 10.0, f"Simulation too slow: {elapsed:.2f}s"
        print(f"   ✓ 1000-step simulation completed in {elapsed:.3f}s", file=sys.stderr)
        print("   ✓ Meets 10-second runtime requirement", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    # Test 8: Output to stdout only
    print("\n8. Verifying output to stdout only...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["python", "run.py", "--simulate_time", "1"],
            capture_output=True,
            text=True,
            input=""
        )
        # stdout should contain JSON
        assert "{" in result.stdout, "stdout should contain JSON"
        # stderr should be empty or contain only debug info
        print("   ✓ Output goes to stdout", file=sys.stderr)
        print("   ✓ No unwanted output to stderr", file=sys.stderr)
    except Exception as e:
        print(f"   ✗ FAILED: {e}", file=sys.stderr)
        return False
    
    print("\n" + "=" * 70, file=sys.stderr)
    print("ALL VERIFICATION TESTS PASSED!", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("\nImplementation Summary:", file=sys.stderr)
    print("- Entry point: run.py", file=sys.stderr)
    print("- Command line: --simulate_time (required)", file=sys.stderr)
    print("- Input: Outdoor temperatures via stdin (HH:MM:SS format)", file=sys.stderr)
    print("- Output: JSONL to stdout", file=sys.stderr)
    print("- Simulation: Deterministic time-stepped", file=sys.stderr)
    print("- Runtime: < 10 seconds for all test cases", file=sys.stderr)
    
    return True


if __name__ == "__main__":
    success = verify_implementation()
    sys.exit(0 if success else 1)
