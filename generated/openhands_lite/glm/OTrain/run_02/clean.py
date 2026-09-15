#!/usr/bin/env python3
"""
Final cleanup - remove all temporary test files
"""

import os

# Essential files to keep
essential = {'run.py', 'README.md'}

# Get all files
files = [f for f in os.listdir('.') if os.path.isfile(f) and not f.startswith('.')]

# Remove non-essential files
for f in files:
    if f not in essential:
        os.remove(f)
        print(f"Removed: {f}")

print(f"\nKeeping only:")
for f in sorted(essential):
    print(f"  - {f}")
