"""
GeoSpark Bench Report Generator.

Renders benchmark results as Rich console output, Markdown, or JSON.
Supports diff mode for comparing two runs (model A vs model B).
"""

from __future__ import annotations

from geospark.bench.models import BenchmarkResult


def to_console(result: BenchmarkResult) -> str:
    """Render a benchmark result as a formatted console string (Rich-compatible)."""
    lines = []
    lines.append("")
    lines.append(f"  GeoSpark Bench — {result.benchmark.value.upper()}")
    lines.append(f"  Model: {result.model_id} | Mode: {result.prompt_mode.value} | Tools: {'Yes' if result.tool_augmented else 'No'}")
    lines.append(f"  {'=' * 60}")
    lines.append("")
    lines.append(f"  Overall: {result.correct}/{result.total} correct ({result.accuracy:.1%})")
    lines.append("")

    # Per-difficulty
    if result.by_difficulty:
        lines.append("  By Difficulty:")
        for diff_name, score in sorted(result.by_difficulty.items()):
            bar = _bar(score.accuracy)
            ci = f"[{score.ci_lower:.0%}-{score.ci_upper:.0%}]"
            lines.append(f"    {diff_name:<8} {score.correct:>3}/{score.total:<3} {score.accuracy:>6.1%} {bar} {ci}")
        lines.append("")

    # Per-category
    if result.by_category:
        lines.append("  By Category:")
        for cat_name, score in sorted(result.by_category.items()):
            bar = _bar(score.accuracy)
            ci = f"[{score.ci_lower:.0%}-{score.ci_upper:.0%}]"
            lines.append(f"    {cat_name:<16} {score.correct:>3}/{score.total:<3} {score.accuracy:>6.1%} {bar} {ci}")
        lines.append("")

    if result.avg_latency_ms > 0:
        lines.append(f"  Avg latency: {result.avg_latency_ms:.0f}ms | Total: {result.total_latency_ms / 1000:.1f}s")
        lines.append("")

    return "\n".join(lines)


def to_markdown(result: BenchmarkResult) -> str:
    """Render a benchmark result as Markdown (for README, reports)."""
    lines = []
    lines.append(f"## GeoSpark Bench — {result.benchmark.value.upper()}")
    lines.append("")
    lines.append(f"**Model**: {result.model_id} | **Mode**: {result.prompt_mode.value} | **Tools**: {'Yes' if result.tool_augmented else 'No'}")
    lines.append("")
    lines.append(f"**Overall**: {result.correct}/{result.total} ({result.accuracy:.1%})")
    lines.append("")

    if result.by_category:
        lines.append("| Category | Correct | Accuracy | 95% CI |")
        lines.append("|----------|---------|----------|--------|")
        for cat_name, score in sorted(result.by_category.items()):
            lines.append(
                f"| {cat_name} | {score.correct}/{score.total} | {score.accuracy:.1%} | {score.ci_lower:.0%}-{score.ci_upper:.0%} |"
            )
        lines.append("")

    return "\n".join(lines)


def to_json(result: BenchmarkResult) -> str:
    """Render a benchmark result as JSON."""
    return result.model_dump_json(indent=2)


def diff(result_a: BenchmarkResult, result_b: BenchmarkResult) -> str:
    """
    Compare two benchmark results side-by-side.

    Useful for: model A vs model B, or natural vs structured mode.
    """
    lines = []
    lines.append("")
    lines.append("  GeoSpark Bench — COMPARISON")
    lines.append(f"  {'=' * 60}")
    lines.append("")
    lines.append(f"  {'':>16}  {'Model A':>12}  {'Model B':>12}  {'Delta':>8}")
    lines.append(f"  {'':>16}  {result_a.model_id:>12}  {result_b.model_id:>12}")
    lines.append(f"  {'-' * 56}")

    # Overall
    delta = result_b.accuracy - result_a.accuracy
    delta_str = f"{delta:+.1%}"
    lines.append(f"  {'Overall':>16}  {result_a.accuracy:>11.1%}  {result_b.accuracy:>11.1%}  {delta_str:>8}")

    # Per-category
    all_cats = sorted(set(list(result_a.by_category.keys()) + list(result_b.by_category.keys())))
    for cat in all_cats:
        a_acc = result_a.by_category[cat].accuracy if cat in result_a.by_category else 0.0
        b_acc = result_b.by_category[cat].accuracy if cat in result_b.by_category else 0.0
        d = b_acc - a_acc
        lines.append(f"  {cat:>16}  {a_acc:>11.1%}  {b_acc:>11.1%}  {d:+.1%}")

    lines.append("")
    return "\n".join(lines)


def _bar(value: float, width: int = 20) -> str:
    """Create a simple text-based progress bar."""
    filled = int(value * width)
    return f"[{'#' * filled}{'.' * (width - filled)}]"
