# Generated DEVS simulation

This directory contains a simulation built from the requirements below. Run the commands from this directory unless a command says otherwise.

## Setup

Install xDEVS in the Python environment used to run this model. The DEVS-Gen repository includes the tested source at `src/third_party/xdevspy`. From the repository root:

```bash
python -m pip install src/third_party/xdevspy
```

## Run

```bash
python run.py [options] > output.txt
```

If the task reads standard input, add `< input.txt` before `> output.txt`. Choose option values and input content from the requirements below. The generated runner recognizes these option names:

```text
{sim_args}
```

## Files

- Simulation module: `{sim_paths}`
- Root model: `{root_model_path}`
- Model description: `{system_info_path}`
- Generation logs: `{log_dir_path}`

## Requirements

{requirements}
