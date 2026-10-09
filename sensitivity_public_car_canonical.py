"""Run the support-sensitivity analysis for the public CAR pipeline.

The experiment uses the same public input directory, canonical pipeline,
confidence threshold, and itemset limit as the paper.  Each threshold is
written to an isolated output directory and summarized in a single CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--confidence", type=float, default=0.60)
    parser.add_argument("--max-len", type=int, default=3)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for support in (0.005, 0.01, 0.02):
        run_dir = output / f"support_{support:.3f}"
        command = [
            sys.executable,
            str(root / "pipeline_dados_abertos_car.py"),
            args.input_dir,
            str(run_dir),
            "--min-support", str(support),
            "--min-confidence", str(args.confidence),
            "--max-len", str(args.max_len),
        ]
        subprocess.run(command, check=True)
        summary = json.loads((run_dir / "resumo_execucao_car_aberto.json").read_text(encoding="utf-8"))
        rows.append({
            "min_support": support,
            "min_confidence": args.confidence,
            "max_len": args.max_len,
            "total_transactions": summary["total_transacoes"],
            "min_count": summary["min_count"],
            "frequent_itemsets": summary["itemsets_frequentes"],
            "raw_rules": summary["regras"],
            "apriori_eclat_agree": summary["apriori_eclat_coincidem"],
            "output_directory": str(run_dir),
        })
    with (output / "sensitivity_public_car.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
