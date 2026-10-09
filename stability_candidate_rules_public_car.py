"""Evaluate candidate-rule stability under stratified public-data resampling.

The check keeps the municipalities separate, samples 80% of each municipality
without replacement, and repeats the metric evaluation 30 times.  It does not
re-run the article's candidate-selection audit; it measures how often the
already selected candidate rules meet the published thresholds in resamples.
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from pipeline_dados_abertos_car import build_dataset, transaction_from_record


MIN_SUPPORT = 0.01
MIN_CONFIDENCE = 0.60
MIN_LIFT = 1.20
MIN_COVERAGE = 0.02


def parse_items(value: str) -> frozenset[str]:
    return frozenset(x.strip() for x in (value or "").split(" + ") if x.strip())


def metrics(transactions: list[frozenset[str]], left: frozenset[str], right: frozenset[str]) -> dict[str, float]:
    union = left | right
    n = len(transactions)
    left_count = sum(left <= tx for tx in transactions)
    right_count = sum(right <= tx for tx in transactions)
    union_count = sum(union <= tx for tx in transactions)
    support = union_count / n if n else 0.0
    confidence = union_count / left_count if left_count else 0.0
    right_support = right_count / n if n else 0.0
    lift = confidence / right_support if right_support else 0.0
    coverage = left_count / n if n else 0.0
    return {"support": support, "confidence": confidence, "lift": lift, "coverage": coverage}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("candidate_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--replications", type=int, default=30)
    parser.add_argument("--fraction", type=float, default=0.80)
    parser.add_argument("--seed", type=int, default=20261009)
    args = parser.parse_args()

    records, _ = build_dataset(Path(args.input_dir))
    by_municipality: dict[str, list[frozenset[str]]] = defaultdict(list)
    for record in records:
        by_municipality[record["municipio"]].append(transaction_from_record(record))
    candidates: list[dict[str, str]] = []
    with Path(args.candidate_csv).open(encoding="utf-8-sig", newline="") as handle:
        candidates = list(csv.DictReader(handle, delimiter=";"))

    result_rows: list[dict[str, object]] = []
    counts = [0] * len(candidates)
    rng = random.Random(args.seed)
    for _ in range(args.replications):
        sampled: list[frozenset[str]] = []
        for municipality in sorted(by_municipality):
            values = by_municipality[municipality]
            size = max(1, round(len(values) * args.fraction))
            sampled.extend(rng.sample(values, size))
        for index, candidate in enumerate(candidates):
            left = parse_items(candidate["antecedente"])
            right = parse_items(candidate["consequente"])
            m = metrics(sampled, left, right)
            if (
                m["support"] >= MIN_SUPPORT
                and m["confidence"] >= MIN_CONFIDENCE
                and m["lift"] >= MIN_LIFT
                and m["coverage"] >= MIN_COVERAGE
            ):
                counts[index] += 1

    for candidate, qualifying in zip(candidates, counts):
        result_rows.append({
            "antecedente": candidate["antecedente"],
            "consequente": candidate["consequente"],
            "original_classification": candidate.get("classificacao", ""),
            "replications": args.replications,
            "qualifying_replications": qualifying,
            "stability_rate": qualifying / args.replications,
            "sample_fraction": args.fraction,
            "seed": args.seed,
        })
    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result_rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(result_rows)
    print(f"candidate_rules={len(result_rows)} replications={args.replications} output={out}")


if __name__ == "__main__":
    main()
