#!/usr/bin/env python3
"""
Check if required libraries are available
"""

import sys
import subprocess

print("Checking libraries...")

try:
    import simpy
    print("simpy is available")
except ImportError as e:
    print("simpy is NOT available:", e)

try:
    import xdevs
    print("xdevs is available")
except ImportError as e:
    print("xdevs is NOT available:", e)

print("Python version:", sys.version)

# Check if we can import the standard libraries
required_std_libs = ['argparse', 'sys', 'json', 'logging', 'collections', 'random']
for lib in required_std_libs:
    try:
        __import__(lib)
        print(f"{lib} is available")
    except ImportError as e:
        print(f"{lib} is NOT available: {e}")

# Try to run a simple test
print("\nTrying to run a simple test...")
try:
    result = subprocess.run([sys.executable, 'run.py', '--help'], 
                          capture_output=True, text=True, cwd='/SEIRD_fill2_01')
    print("Help command works:", result.returncode == 0)
    if result.stdout:
        print("Help output:", result.stdout[:100] + "...")
except Exception as e:
    print("Error running test:", e)

# Try to run a basic simulation
print("\nTrying to run a basic simulation...")
try:
    result = subprocess.run([
        sys.executable, 'run.py',
        '--test_name', 'test1',
        '--mortality', '10.0',
        '--infectivity_period', '14.0',
        '--dt', '0.1',
        '--incubation_period', '5.0',
        '--total_population', '1000',
        '--initial_infective', '10',
        '--transmission_rate', '2.5',
        '--simulation_time', '1.0'
    ], capture_output=True, text=True, cwd='/SEIRD_fill2_01')
    print("Basic simulation works:", result.returncode == 0)
    if result.stdout:
        print("Output:", result.stdout.strip())
    if result.stderr:
        print("Error output:", result.stderr.strip())
except Exception as e:
    print("Error running basic simulation:", e)