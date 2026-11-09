"""Rebuild the Benchmark 1 result counts from the per-question records in this folder.

Prints, for every model and condition:
  - numeric distance (distance_absolute): correct answers out of 80
  - each benchmark: correct answers and the number of questions
No model is called; the records already hold each answer and whether it was scored correct.
Usage (from the repository root, in the GeoSpark virtual environment):
    python docs/benchmarks/2026-05/tables_from_records.py
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONDITIONS = ("baseline", "cot", "augmented")


def records():
    for folder in ("open_checkpoints", "frontier_checkpoints"):
        for f in sorted((HERE / folder).glob("*.json")):
            if f.name.startswith("._"):
                continue
            model, condition, benchmark = f.stem.rsplit("__", 2)
            yield model, condition, benchmark, json.loads(f.read_text())["details"]


def main() -> None:
    distance = defaultdict(dict)
    totals = defaultdict(dict)
    for model, condition, benchmark, details in records():
        totals[(model, condition)][benchmark] = (sum(bool(q["correct"]) for q in details), len(details))
        dist = [q for q in details if q.get("category") == "distance_absolute"]
        if dist:
            distance[model][condition] = (sum(bool(q["correct"]) for q in dist), len(dist))

    print("Numeric distance (distance_absolute), correct / questions")
    print(f"{'model':45s}" + "".join(f"{c:>14s}" for c in CONDITIONS))
    for model in sorted(distance):
        cells = [distance[model].get(c) for c in CONDITIONS]
        print(f"{model:45s}" + "".join(f"{f'{k}/{n}':>14s}" if (k, n) != (None, None) and c else f"{'not run':>14s}"
                                       for c, (k, n) in zip(cells, [x or (None, None) for x in cells])))

    print("\nCorrect / questions per benchmark")
    benchmarks = sorted({b for t in totals.values() for b in t})
    print(f"{'model':45s} {'condition':10s}" + "".join(f"{b:>15s}" for b in benchmarks))
    for (model, condition) in sorted(totals, key=lambda k: (k[0], CONDITIONS.index(k[1]))):
        row = totals[(model, condition)]
        print(f"{model:45s} {condition:10s}" + "".join(f"{f'{row[b][0]}/{row[b][1]}' if b in row else '-':>15s}"
                                                       for b in benchmarks))


if __name__ == "__main__":
    main()
