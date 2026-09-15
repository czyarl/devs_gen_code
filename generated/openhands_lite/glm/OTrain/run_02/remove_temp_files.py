#!/usr/bin/env python3
"""
Remove all temporary test files, keeping only run.py and README.md
"""

import os

files_to_remove = [
    'cleanup.py',
    'direct_test.py',
    'final_verify.py',
    'quick_test.py',
    'quick_verify.py',
    'run_test.sh',
    'run_verify.sh',
    'simple_test.py',
    'test_direct.py',
    'test_simulation.py',
    'verify.py'
]

for filename in files_to_remove:
    if os.path.exists(filename):
        os.remove(filename)
        print(f"Removed: {filename}")

print("\nRemaining files:")
for f in sorted(os.listdir('.')):
    if not f.startswith('.'):
        print(f"  - {f}")
