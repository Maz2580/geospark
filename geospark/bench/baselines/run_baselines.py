"""
GeoSpark Bench — Baseline LLM Evaluation.

Runs benchmarks against real LLMs to measure the accuracy gap between:
  - LLM alone (no tools, raw spatial reasoning)
  - LLM + GeoSpark (with spatial tools)

This produces GeoSpark's most important evidence: the accuracy numbers
that prove spatial reasoning is broken in current LLMs.

Usage:
    .venv/Scripts/python.exe geospark/bench/baselines/run_baselines.py
    .venv/Scripts/python.exe geospark/bench/baselines/run_baselines.py --benchmark geotopo --sample 0.2
    .venv/Scripts/python.exe geospark/bench/baselines/run_baselines.py --models best fast
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from geospark.bench import (
    BenchmarkName,
    BenchmarkResult,
    BenchRunner,
    PromptMode,
    load_dataset,
    report,
)
from geospark.bench.models import ModelAdapter
from geospark.integrations.openrouter import FREE_MODELS

console = Console()
RESULTS_DIR = Path(__file__).parent / "results"

# Models confirmed working for bench evaluations
# (free tier rate limits vary — these are reliably available)
BENCH_MODELS = {
    "gemma-12b": "google/gemma-3-12b-it:free",
    "gemma-4b": "google/gemma-3-4b-it:free",
    **FREE_MODELS,
}


# ---------------------------------------------------------------------------
# LLM-Only Adapter (no tools — tests raw spatial reasoning)
# ---------------------------------------------------------------------------

class LLMOnlyAdapter:
    """
    Sends prompts directly to an LLM with NO spatial tools.

    This is the baseline: how well can the model answer spatial questions
    using only its training data and reasoning? Spoiler: not well.
    """

    def __init__(self, model_key: str = "best"):
        self._api_key = os.getenv("OPENROUTER_API_KEY", "")
        self._base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        if model_key in BENCH_MODELS:
            self._model = BENCH_MODELS[model_key]
            self._model_key = model_key
        elif model_key in FREE_MODELS:
            self._model = FREE_MODELS[model_key]
            self._model_key = model_key
        else:
            self._model = model_key
            self._model_key = model_key

        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://geospark.dev",
                "X-Title": "GeoSpark Bench",
            },
            timeout=60,
        )
        self._request_count = 0

    @property
    def model_id(self) -> str:
        return f"{self._model_key}(no-tools)"

    def complete(self, prompt: str, _retries: int = 0) -> str:
        """Send prompt to LLM without any tools."""
        self._request_count += 1

        # Proactive rate limiting — stay under free tier limits (~10 req/min)
        if self._request_count > 1:
            time.sleep(8)

        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are answering spatial reasoning questions. "
                                "Give a direct, concise answer. "
                                "For yes/no questions, start with 'Yes' or 'No'. "
                                "For distance questions, give the distance in meters. "
                                "For multiple choice, give the option name."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 200,
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and _retries < 3:
                wait = 15 * (_retries + 1)  # 15s, 30s, 45s
                console.print(f"[yellow]Rate limited, waiting {wait}s (retry {_retries + 1}/3)...[/yellow]")
                time.sleep(wait)
                return self.complete(prompt, _retries=_retries + 1)
            return f"ERROR: {e.response.status_code}"
        except Exception as e:
            return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------

def run_evaluation(
    benchmark: BenchmarkName,
    model_key: str,
    prompt_mode: PromptMode,
    sample: float | None = None,
) -> BenchmarkResult:
    """Run a single benchmark evaluation."""
    adapter = LLMOnlyAdapter(model_key=model_key)
    runner = BenchRunner(adapter=adapter)

    return runner.run(
        benchmark=benchmark,
        prompt_mode=prompt_mode,
        sample=sample,
    )


def save_result(result: BenchmarkResult, suffix: str = ""):
    """Save a result to the results directory."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{result.benchmark.value}_{result.model_id.replace('/', '_')}{suffix}.json"
    path = RESULTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.to_json(result))
    return path


def generate_readme_table(results: list[BenchmarkResult]) -> str:
    """Generate a markdown comparison table for the README."""
    lines = []
    lines.append("## Benchmark Results")
    lines.append("")
    lines.append("| Benchmark | Model | Mode | Accuracy | Correct | 95% CI |")
    lines.append("|-----------|-------|------|----------|---------|--------|")

    for r in sorted(results, key=lambda x: (x.benchmark.value, x.model_id)):
        ci_lo = min(s.ci_lower for s in r.by_difficulty.values()) if r.by_difficulty else 0
        ci_hi = max(s.ci_upper for s in r.by_difficulty.values()) if r.by_difficulty else 1
        lines.append(
            f"| {r.benchmark.value} | {r.model_id} | {r.prompt_mode.value} | "
            f"**{r.accuracy:.1%}** | {r.correct}/{r.total} | {ci_lo:.0%}–{ci_hi:.0%} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--benchmark", "-b",
    type=click.Choice([n.value for n in BenchmarkName]),
    default=None,
    help="Run specific benchmark (default: all)",
)
@click.option(
    "--models", "-m",
    multiple=True,
    default=["best"],
    help="Model keys to evaluate (default: best). Use OpenRouter FREE_MODELS keys.",
)
@click.option(
    "--sample",
    type=float,
    default=None,
    help="Fraction of questions to run (e.g., 0.2 for 20%)",
)
@click.option(
    "--mode",
    type=click.Choice(["natural", "structured", "both"]),
    default="natural",
    help="Prompt mode (default: natural)",
)
def main(benchmark, models, sample, mode):
    """Run baseline LLM evaluations for GeoSpark Bench."""

    console.print(Panel(
        "[bold]GeoSpark Bench — Baseline LLM Evaluation[/bold]\n\n"
        "Running benchmarks against LLMs WITHOUT spatial tools.\n"
        "This measures raw spatial reasoning ability.",
        title="GeoSpark Bench",
    ))

    # Determine benchmarks to run
    if benchmark:
        benchmarks = [BenchmarkName(benchmark)]
    else:
        benchmarks = [BenchmarkName.GEOTOPO, BenchmarkName.GEODISTANCE]
        # Skip geochanage for now — it's knowledge-based, not reasoning

    # Determine prompt modes
    if mode == "both":
        modes = [PromptMode.NATURAL, PromptMode.STRUCTURED]
    else:
        modes = [PromptMode(mode)]

    # Calculate total runs
    total_runs = len(benchmarks) * len(models) * len(modes)
    console.print(f"\n[cyan]Plan: {total_runs} evaluation runs[/cyan]")
    for b in benchmarks:
        qs = load_dataset(b)
        n = int(len(qs) * sample) if sample else len(qs)
        console.print(f"  {b.value}: {n} questions")
    for m in models:
        model_name = BENCH_MODELS.get(m, FREE_MODELS.get(m, m))
        console.print(f"  Model: {m} -> {model_name}")
    console.print()

    # Run evaluations
    all_results: list[BenchmarkResult] = []

    for bench_name in benchmarks:
        for model_key in models:
            for prompt_mode in modes:
                label = f"{bench_name.value} | {model_key} | {prompt_mode.value}"
                console.print(f"[bold]Running: {label}[/bold]")

                result = run_evaluation(
                    benchmark=bench_name,
                    model_key=model_key,
                    prompt_mode=prompt_mode,
                    sample=sample,
                )

                # Show result immediately
                console.print(report.to_console(result))

                # Save
                path = save_result(result, f"_{prompt_mode.value}")
                console.print(f"  [dim]Saved to {path}[/dim]\n")

                all_results.append(result)

    # Summary comparison
    if len(all_results) > 1:
        console.print(Panel("[bold]Summary — All Results[/bold]"))
        table = Table(title="Baseline Accuracy (LLM only, no GeoSpark tools)")
        table.add_column("Benchmark", style="cyan")
        table.add_column("Model", style="green")
        table.add_column("Mode", style="yellow")
        table.add_column("Accuracy", justify="right", style="bold")
        table.add_column("Correct", justify="right")

        for r in all_results:
            table.add_row(
                r.benchmark.value,
                r.model_id,
                r.prompt_mode.value,
                f"{r.accuracy:.1%}",
                f"{r.correct}/{r.total}",
            )
        console.print(table)

    # Generate README table
    readme_table = generate_readme_table(all_results)
    readme_path = RESULTS_DIR / "readme_table.md"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_table)
    console.print(f"\n[green]README table saved to {readme_path}[/green]")
    console.print(readme_table)


if __name__ == "__main__":
    main()
