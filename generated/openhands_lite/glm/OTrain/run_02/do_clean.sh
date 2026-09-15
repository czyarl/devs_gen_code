#!/usr/bin/env python3
"""
Execute cleanup
"""

import subprocess
import sys

result = subprocess.run([sys.executable, 'clean.py'], capture_output=False)
sys.exit(result.returncode)
