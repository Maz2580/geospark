"""
GeoSpark Bench CLI.

Usage:
    python -m geospark.bench run --benchmark geotopo --model mock
    python -m geospark.bench run --benchmark geodistance --mode structured --sample 0.2
    python -m geospark.bench list
    python -m geospark.bench run --benchmark geotopo --dry-run
"""

from __future__ import annotations

import sys
import json

import click
from rich.console import Console

from geospark.bench.models import BenchmarkName, MockAdapter, PromptMode
from geospark.bench.runner import BenchRunner, list_benchmarks
from geospark.bench import report

console = Console()


@click.group()
def cli():
    """GeoSpark Bench — Evaluate spatial reasoning in AI models."""
    pass


@cli.command()
def list():
    """List available benchmarks."""
    benchmarks = list_benchmarks()
    if not benchmarks:
        console.print("[yellow]No benchmark datasets found. Generate them first.[/yellow]")
        return

    console.print("\n[bold]Available Benchmarks[/bold]\n")
    for b in benchmarks:
        console.print(f"  [cyan]{b['name']:<16}[/cyan] {b['total_questions']:>4} questions  v{b['version']}  {b['description']}")
    console.print()


@cli.command()
@click.option("--benchmark", "-b", required=True, type=click.Choice([n.value for n in BenchmarkName]))
@click.option("--model", "-m", default="mock", help="Model to evaluate (default: mock)")
@click.option("--mode", type=click.Choice(["natural", "structured"]), default="natural")
@click.option("--sample", type=float, default=None, help="Fraction of questions to run (0.0-1.0)")
@click.option("--difficulty", type=click.Choice(["easy", "medium", "hard"]), default=None)
@click.option("--category", default=None, help="Filter to specific category")
@click.option("--output", "-o", type=click.Choice(["console", "markdown", "json"]), default="console")
@click.option("--dry-run", is_flag=True, help="Show questions without running model")
@click.option("--save", type=click.Path(), default=None, help="Save results to file")
def run(benchmark, model, mode, sample, difficulty, category, output, dry_run, save):
    """Run a benchmark evaluation."""
    bench_name = BenchmarkName(benchmark)
    prompt_mode = PromptMode(mode)

    # Resolve model adapter
    adapter = _resolve_adapter(model)

    runner = BenchRunner(adapter=adapter)

    try:
        result = runner.run(
            benchmark=bench_name,
            prompt_mode=prompt_mode,
            sample=sample,
            difficulty=difficulty,
            category=category,
            dry_run=dry_run,
        )
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    # Render output
    if dry_run:
        console.print(f"\n[yellow]Dry run: {result.total} questions would be evaluated[/yellow]\n")
        return

    if output == "console":
        console.print(report.to_console(result))
    elif output == "markdown":
        click.echo(report.to_markdown(result))
    elif output == "json":
        click.echo(report.to_json(result))

    # Save if requested
    if save:
        with open(save, "w", encoding="utf-8") as f:
            f.write(report.to_json(result))
        console.print(f"[green]Results saved to {save}[/green]")


def _resolve_adapter(model: str):
    """Resolve a model string to an adapter instance."""
    if model == "mock":
        return MockAdapter()

    # OpenRouter free models
    if model.startswith("openrouter:") or "/" in model:
        try:
            from geospark.integrations.openrouter import OpenRouterClient
            return _OpenRouterAdapter(model.replace("openrouter:", ""))
        except ImportError:
            console.print("[red]OpenRouter integration not available. Install with: pip install geospark[llm][/red]")
            sys.exit(1)

    # Default to mock with warning
    console.print(f"[yellow]Unknown model '{model}', using mock adapter[/yellow]")
    return MockAdapter()


class _OpenRouterAdapter:
    """Adapter wrapping OpenRouter for bench use."""

    def __init__(self, model_name: str):
        from geospark.integrations.openrouter import OpenRouterClient
        self._client = OpenRouterClient()
        self._model_name = model_name

    @property
    def model_id(self) -> str:
        return self._model_name

    def complete(self, prompt: str) -> str:
        answer = self._client.ask(prompt)
        return answer.text


if __name__ == "__main__":
    cli()
