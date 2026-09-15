#!/usr/bin/env python3
"""
Final verification of the SEIRD simulation
"""

import subprocess
import json
import sys

# Test the simulation with default parameters
cmd = [
    "python", "run.py",
    "--test_name", "final_verification",
    "--mortality", "10.0",
    "--infectivity_period", "14.0",
    "--dt", "0.1",
    "--incubation_period", "5.0",
    "--total_population", "1000",
    "--initial_infective", "10",
    "--transmission_rate", "2.5",
    "--simulation_time", "10.0"
]

print("Running final verification test...")
print("="*60)

result = subprocess.run(cmd, capture_output=True, text=True)

print(f"\nExit code: {result.returncode}")

if result.returncode == 0:
    print("\n✓ Simulation completed successfully")
    
    # Parse and display output
    try:
        output = json.loads(result.stdout.strip())
        print("\nFinal State:")
        print(f"  Time: {output['time']:.2f} days")
        print(f"  Susceptible: {output['susceptible']:.2f}")
        print(f"  Exposed: {output['exposed']:.2f}")
        print(f"  Infective: {output['infective']:.2f}")
        print(f"  Recovered: {output['recovered']:.2f}")
        print(f"  Deceased: {output['deceased']:.2f}")
        
        # Verify population conservation
        total = (output["susceptible"] + output["exposed"] + 
                output["infective"] + output["recovered"] + 
                output["deceased"])
        print(f"\nPopulation Conservation:")
        print(f"  Total: {total:.2f} / 1000.0")
        print(f"  Difference: {abs(total - 1000.0):.6f}")
        
        if abs(total - 1000.0) < 0.01:
            print("\n✓ Population conserved within tolerance")
        else:
            print("\n✗ WARNING: Population not conserved")
        
        # Verify all compartments are non-negative
        all_non_negative = all([
            output["susceptible"] >= 0,
            output["exposed"] >= 0,
            output["infective"] >= 0,
            output["recovered"] >= 0,
            output["deceased"] >= 0
        ])
        
        if all_non_negative:
            print("✓ All compartments are non-negative")
        else:
            print("✗ WARNING: Some compartments are negative")
        
        print("\n" + "="*60)
        print("VERIFICATION COMPLETE")
        print("="*60)
        
    except json.JSONDecodeError as e:
        print(f"\n✗ Error parsing JSON output: {e}")
        print(f"Raw output: {result.stdout}")
        sys.exit(1)
else:
    print("\n✗ Simulation failed")
    print(f"STDERR: {result.stderr}")
    sys.exit(1)