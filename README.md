# DEVS-Gen

This repository contains the current DEVS-Gen implementation and the code used to evaluate it. It includes the ten DEVS simulation tasks used in our study, six comparison methods, generated programs, evaluation results, and plotting scripts. DEVS-Gen builds on HAMLET.

| Directory | Contents |
| --- | --- |
| `benchmark/<scenario>/` | Task YAML, test inputs, manifest, and executable `checker.py` |
| `src/generation/` | DEVS-Gen and six comparison methods |
| `src/third_party/xdevspy/` | Bundled xDEVS source used by the generators and evaluator |
| `src/devs_eval/` | Code that runs programs and calculates scores |
| `envs/` | Python requirements for DEVS-Gen, OpenHands, and SWE-Agent |
| `generated/<method>/<model>/<scenario>/<run>/` | Generated programs available for inspection and re-evaluation |
| `results/` | Task-level scores, summaries, and detailed scoring records |
| `figures/` | Plots and their timing data |

Use `src/generation/run_generation.py` to run any of the seven methods. DEVS-Gen's entry point is `src/generation/devs_app/run.py`. The six comparison methods are in `src/generation/devs_baseline/`.
The Markdown files under `src/generation/devs_tools/*/materials/` are prompts and templates used during generation.

## Set up and run

Run these commands from the repository root on Linux. DEVS-Gen and the single-shot methods use Python 3.10. OpenHands and SWE-Agent use Python 3.12. The commands below create environments at the paths expected by the generation runner. Docker is needed for SWE-Agent.

```bash
python3.10 -m venv .venvs/devs-gen
.venvs/devs-gen/bin/python -m pip install -r envs/devs_gen.txt
.venvs/devs-gen/bin/python -m pip install . src/third_party/xdevspy simpy==4.1.1

python3.12 -m venv .venvs/openhands
.venvs/openhands/bin/python -m pip install -r envs/openhands.txt
.venvs/openhands/bin/python -m pip install src/third_party/xdevspy

python3.12 -m venv .venvs/sweagent
.venvs/sweagent/bin/python -m pip install -r envs/sweagent.txt
docker build -f src/generation/devs_baseline/swe_agent_run/docker_construct/Dockerfile -t python-xdevs-simpy src
```

The installation commands above use the xDEVS copy included in this repository. Its own README describes the upstream project.

You can also create the environments with Conda. For example, `conda create -p "$PWD/.venvs/devs-gen" python=3.10 pip` creates the first one; use Python 3.12 for the other two. Existing environments can be selected through `DEVS_GEN_PYTHON`, `DEVS_OPENHANDS_PYTHON`, and `DEVS_SWEAGENT_PYTHON` in `.env`. Each value is the absolute path to a Python executable.

Copy `.env.example` to `.env` and enter the API key for your model provider before generating code. Re-evaluating the bundled programs needs no API key. The SWE-Agent wrapper also needs access to Docker. Optional proxy settings for its container are shown in `.env.example`.

Run the generator from `src/generation/`, which is where its modules are imported from:

```bash
cd src/generation
../../.venvs/devs-gen/bin/python run_generation.py --list-frameworks
../../.venvs/devs-gen/bin/python run_generation.py --list-benchmarks
../../.venvs/devs-gen/bin/python run_generation.py \
  --framework devs_gen --model MODEL_ID --benchmark ABP --workspace /tmp/devs_abp_generation
cd ../..
```

Replace `MODEL_ID` with a model name accepted by your configured provider. The other framework names are `openhands`, `openhands_lite`, `swe_agent`, `swe_agent_lite`, `single_simpy`, and `single_xdevs`. `--list-frameworks` shows the interpreter selected for each one.

The result tables use short model labels. These are the model IDs used for the four groups of runs in this study:

| Result label | `--model` value |
| --- | --- |
| `gpt` | `openai/gpt-5.2` |
| `glm` | `openrouter/z-ai/glm-4.7` |
| `llama` | `openrouter/meta-llama/llama-4-scout` |
| `qwen` | `openrouter/qwen/qwen3-coder-30b-a3b-instruct` |

For plotting, install the optional plotting dependency with `.venvs/devs-gen/bin/python -m pip install '.[plot]'`. The evaluator also needs `unshare`, `bwrap`, `prlimit`, and working user/network namespaces. Install xDEVS with the regular `pip install` command above: its source must be visible inside the evaluation sandbox. A generated program may need additional packages in the Python environment used for evaluation.

## Evaluate a program

```bash
.venvs/devs-gen/bin/python -m devs_eval.cli validate-manifest benchmark/ABP/manifest.json
.venvs/devs-gen/bin/python -m devs_eval.cli run-scenario \
  --manifest benchmark/ABP/manifest.json \
  --simulator-directory generated/devs_gen/gpt/ABP/run_01 \
  --output-directory /tmp/devs_abp_eval
```

Pass `--python-executable /path/to/python` if a program needs a different environment. To re-evaluate a bundled program and compare its new scores with the reported row, run:

```bash
.venvs/devs-gen/bin/python src/recheck_results.py --method devs_gen --model gpt --scenario ABP \
  --limit 1 --output /tmp/abp_recheck.csv
```

`src/recheck_results.py` reads `results/task_results.csv` and `results/single_ablations.csv`, runs the available programs again, and writes a new comparison CSV. Remove the filters and `--limit` to check every available program. IOBS and OTrain use time-based random seeds, so their behavior scores may vary across runs. This script leaves the reported tables and resource measurements unchanged.

Each `benchmark/<scenario>/` directory contains its manifest, test inputs, and `checker.py`. The evaluator runs the program under resource limits, checks its output, and applies that scenario's rules. A checker is executable Python, so use benchmark directories from a trusted source. `Score_ope` is the fraction of test cases with valid execution and output. `Score_beh` averages the available micro- and macro-requirement scores; invalid cases receive zero for applicable requirements. The evaluator reports the two scores separately.

## Read the results

`results/task_results.csv` has 600 rows: five methods × four models × ten scenarios × three runs. Of these, 502 have a generated program and 491 have a detailed score record. The 11 rows with a program but no detailed score record have zero scores in the main table. `results/single_ablations.csv` contains the complete single-shot ablation: two direct-generation methods × four models × ten scenarios × three runs, or 240 scheduled tasks. It includes 232 generated programs; the other eight scheduled generations produced no `run.py` and receive zero scores. `results/single_ablation_summary.csv` reports the corresponding model-level means and standard deviations. `results/score_details.jsonl` contains the 491 detailed records from the main comparison; single-shot programs can be inspected directly or re-evaluated with `src/recheck_results.py`.

`results/summary.csv` averages scores over all 30 scheduled tasks per method and model, including zero-valued tasks. Its mean time uses rows with a recorded time. The `run_01`–`run_03` labels identify independent attempts; matching labels across methods do not indicate shared seeds. DEVS-Gen time is calculated from recorded call durations under an eight-worker schedule; `figures/parallel_timing.csv` contains the timing inputs. In the first CDF column, generation completion means that the generation process ended normally and supplied the expected executable entry point. It does not require every evaluation case to pass. The CDF treats missing resource measurements as infinite cost. Run `.venvs/devs-gen/bin/python src/plot_figures.py` to redraw the figures after installing the plotting dependency. Raw API responses and process logs are omitted from this release.

This repository uses the [Apache License 2.0](LICENSE), except for files with their own licenses. The bundled xDEVS source retains its [GPLv3 license](src/third_party/xdevspy/LICENSE.txt).
