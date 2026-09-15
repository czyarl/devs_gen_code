#!/usr/bin/env python3
"""Draw publication figures from the normalized task matrix."""

from __future__ import annotations

import csv
import statistics
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

ROOT = Path(__file__).resolve().parents[1]
STYLES = {
    "devs_gen": ("DEVS-Gen (8-worker estimate)", "#C73E1D", "-"),
    "openhands": ("OpenHands", "#2E86AB", "--"),
    "openhands_lite": ("OpenHands-Lite", "#6A4C93", ":"),
    "swe_agent": ("SWE-Agent", "#009988", "-."),
    "swe_agent_lite": ("SWE-Agent-Lite", "#EE7733", (0, (3, 1, 1, 1, 1))),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def format_cost(value: float, _pos: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if value >= 1_000:
        return f"{value / 1_000:g}K"
    return f"{value:g}"


def save(fig, stem: str) -> None:
    folder = ROOT / "figures"
    folder.mkdir(exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(folder / f"{stem}.{suffix}", dpi=450, bbox_inches="tight")
    plt.close(fig)


def resource_cdf(rows: list[dict[str, str]]) -> None:
    metrics = (("Full completion", "fully_operational", "Cumulative completion"),
               ("Operational score", "score_ope", "Cumulative operational score"),
               ("Behavioral score", "score_beh", "Cumulative behavioral score"))
    resources = (("generation_time_sec", 10, 5000, "Generation time (s, log scale)"),
                 ("generation_tokens", 5000, 5_000_000, "Tokens (log scale)"))
    fig, axes = plt.subplots(2, 3, figsize=(8.1, 5.1), sharex=True)
    for col, (title, score_key, xlabel) in enumerate(metrics):
        for ri, (cost_key, lower, upper, ylabel) in enumerate(resources):
            ax = axes[ri, col]
            for method, (label, color, linestyle) in STYLES.items():
                known = sorted((float(row[cost_key]), float(row[score_key]))
                               for row in rows
                               if row["method"] == method and row[cost_key] != "")
                x_values, y_values, cumulative = [0.0], [float(lower)], 0.0
                for cost, score in known:
                    if score <= 0:
                        continue
                    cumulative += score / 120
                    x_values.append(cumulative)
                    y_values.append(cost)
                # A score increment is reached at that run's cost, not at the
                # artificial lower plotting bound preceding the first run.
                ax.step(x_values, y_values, where="pre", color=color,
                        linestyle=linestyle, label=label, lw=1.7)
            ax.set_yscale("log")
            ax.set_ylim(lower, upper)
            ax.set_xlim(0, 1)
            ax.xaxis.set_major_locator(mtick.MultipleLocator(0.2))
            ax.xaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=0))
            ax.yaxis.set_major_formatter(mtick.FuncFormatter(format_cost))
            ax.yaxis.set_minor_formatter(mtick.NullFormatter())
            ax.grid(alpha=0.22, linewidth=0.5)
            if ri == 0:
                ax.set_title(title)
            else:
                ax.set_xlabel(xlabel)
            if col == 0:
                ax.set_ylabel(ylabel)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, -0.012), frameon=False)
    fig.subplots_adjust(left=0.085, right=0.99, top=0.92, bottom=0.2,
                        wspace=0.26, hspace=0.28)
    save(fig, "resource_cdf_six_panel")


def stage_comparison(rows: list[dict[str, str]]) -> None:
    if len(rows) != 2 or {r["stage"] for r in rows} != {"1", "2"}:
        raise ValueError("Expected two generation stages")
    rows.sort(key=lambda r: int(r["stage"]))
    x = [0, 1]
    observed = [float(r["observed_serial_mean_sec"]) for r in rows]
    estimated = [float(r["modeled_parallel8_mean_sec"]) for r in rows]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.bar([v - 0.19 for v in x], observed, width=0.38, label="Observed serial",
           color="#2E86AB")
    ax.bar([v + 0.19 for v in x], estimated, width=0.38,
           label="8-worker estimate", color="#C73E1D")
    ax.set_xticks(x, [f"Stage {r['stage']}" for r in rows])
    ax.set_ylabel("Mean generation time (s)")
    ax.set_title("GPT runs only (n=30)")
    ax.set_ylim(0, max(observed + estimated) * 1.28)
    ax.grid(axis="y", alpha=0.22, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "stage_serial_vs_parallel8")


def main() -> None:
    plt.rcParams.update({"font.family": "serif", "font.size": 8,
                         "axes.labelsize": 8, "axes.titlesize": 9,
                         "legend.fontsize": 7, "xtick.labelsize": 7,
                         "ytick.labelsize": 7, "axes.spines.top": False,
                         "axes.spines.right": False, "pdf.fonttype": 42,
                         "ps.fonttype": 42})
    tasks = read_csv(ROOT / "results/task_results.csv")
    if len(tasks) != 600 or Counter(r["method"] for r in tasks) != {
        method: 120 for method in STYLES
    }:
        raise ValueError("Expected 600 task cells, 120 per method")
    resource_cdf(tasks)
    timing = read_csv(ROOT / "figures/parallel_timing.csv")
    stage_rows = []
    for stage in ("1", "2"):
        selected = [row for row in timing
                    if row["task_id"].startswith("devs_gen-gpt-")
                    and row["worker_cap"] == "8" and row["stage"] == stage]
        if len(selected) != 30:
            raise ValueError(f"Expected 30 GPT timing records for stage {stage}")
        stage_rows.append({
            "stage": stage,
            "observed_serial_mean_sec": statistics.mean(
                float(row["observed_sec"]) for row in selected),
            "modeled_parallel8_mean_sec": statistics.mean(
                float(row["estimated_sec"]) for row in selected),
        })
    stage_comparison(stage_rows)
    print("Wrote two figures (PNG, PDF)")


if __name__ == "__main__":
    main()
