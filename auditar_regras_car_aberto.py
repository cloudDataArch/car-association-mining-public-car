"""Auditoria e selecao de regras de associacao para o artigo.

Entrada:
  pasta de resultados do pipeline_dados_abertos_car.py
Saida:
  regras_filtradas_comparacao.csv
  regras_candidatas_artigo.csv
  resumo_auditoria_regras.json

O script preserva a saida bruta do Apriori/Eclat e apenas cria uma camada
interpretativa, removendo regras tautologicas ou equivalentes.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


MIN_SUPPORT = 0.01
MIN_CONFIDENCE = 0.60
MIN_LIFT = 1.20
MIN_COVERAGE = 0.02


def parse_items(value: str) -> frozenset[str]:
    return frozenset(x.strip() for x in (value or "").split(" + ") if x.strip())


def item_dimension(item: str) -> str:
    left = item.split("=", 1)[0]
    if left.startswith("FAIXA_AREA_"):
        return left[len("FAIXA_AREA_"):]
    return left


def same_source_pair(left: frozenset[str], right: frozenset[str]) -> bool:
    """Remove presence x faixa de area da mesma camada."""
    for a in left:
        for b in right:
            da = item_dimension(a)
            db = item_dimension(b)
            if da == db:
                return True
    return False


def municipality_uf_equivalence(all_items: frozenset[str]) -> bool:
    dims = {item_dimension(x) for x in all_items}
    return "UF" in dims and "MUNICIPIO" in dims


def parse_transactions(path: Path) -> list[tuple[str, frozenset[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    result = []
    for row in rows:
        items = frozenset(x for x in (row.get("itens") or "").split("|") if x)
        result.append((row.get("codigo_car", ""), items))
    return result


def support_count(transactions: list[frozenset[str]], itemset: frozenset[str]) -> int:
    return sum(itemset <= t for t in transactions)


def metrics(transactions: list[frozenset[str]], left: frozenset[str], right: frozenset[str]) -> dict[str, float | int]:
    total = len(transactions)
    both = support_count(transactions, left | right)
    left_count = support_count(transactions, left)
    right_count = support_count(transactions, right)
    support = both / total if total else 0.0
    confidence = both / left_count if left_count else 0.0
    right_support = right_count / total if total else 0.0
    lift = confidence / right_support if right_support else 0.0
    coverage = left_count / total if total else 0.0
    return {
        "contagem": both,
        "suporte": support,
        "confianca": confidence,
        "lift": lift,
        "cobertura_antecedente": coverage,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir")
    args = parser.parse_args()
    results = Path(args.results_dir)
    rules_path = results / "regras_associacao_car_aberto.csv"
    trans_path = results / "transacoes_car_aberto.csv"
    dataset_path = results / "dataset_analitico_car_aberto.csv"

    with rules_path.open(encoding="utf-8-sig", newline="") as f:
        raw_rules = list(csv.DictReader(f, delimiter=";"))
    with dataset_path.open(encoding="utf-8-sig", newline="") as f:
        dataset = list(csv.DictReader(f, delimiter=";"))
    transactions = parse_transactions(trans_path)

    by_municipality: dict[str, list[frozenset[str]]] = {}
    for row, (_, items) in zip(dataset, transactions):
        by_municipality.setdefault(row.get("municipio_norm", "NAO_INFORMADO"), []).append(items)

    discarded = Counter()
    candidates = []
    for raw in raw_rules:
        left = parse_items(raw.get("antecedente", ""))
        right = parse_items(raw.get("consequente", ""))
        all_items = left | right
        if same_source_pair(left, right):
            discarded["mesma_fonte_presenca_area"] += 1
            continue
        if municipality_uf_equivalence(all_items):
            discarded["equivalencia_municipio_uf"] += 1
            continue
        if any(item_dimension(item) == "QTD_TEMAS_AMBIENTAIS" for item in all_items):
            discarded["variavel_derivada_qtd_temas"] += 1
            continue
        support = float(raw.get("suporte") or 0)
        confidence = float(raw.get("confianca") or 0)
        lift = float(raw.get("lift") or 0)
        coverage = float(raw.get("cobertura_antecedente") or 0)
        if support < MIN_SUPPORT or confidence < MIN_CONFIDENCE or lift < MIN_LIFT or coverage < MIN_COVERAGE:
            discarded["limiar_estatistico"] += 1
            continue
        candidates.append({
            "antecedente": " + ".join(sorted(left)),
            "consequente": " + ".join(sorted(right)),
            "itens_uniao": " + ".join(sorted(all_items)),
            "suporte_global": support,
            "confianca_global": confidence,
            "lift_global": lift,
            "cobertura_global": coverage,
        })

    # Uma regra e mantida por conjunto de itens, evitando apresentar apenas a
    # mesma associacao invertida varias vezes na tabela do artigo.
    dedup: dict[str, dict[str, object]] = {}
    for rule in candidates:
        key = rule["itens_uniao"]
        old = dedup.get(key)
        score = (float(rule["lift_global"]), float(rule["confianca_global"]), float(rule["suporte_global"]))
        old_score = (-1.0, -1.0, -1.0) if old is None else (
            float(old["lift_global"]), float(old["confianca_global"]), float(old["suporte_global"])
        )
        if old is None or score > old_score:
            dedup[key] = rule

    filtered = []
    for rule in dedup.values():
        left = parse_items(rule["antecedente"])
        right = parse_items(rule["consequente"])
        row = dict(rule)
        municipality_classes = []
        for municipality, tx in sorted(by_municipality.items()):
            m = metrics(tx, left, right)
            prefix = "pa" if municipality == "SAO_FELIX_DO_XINGU" else "sp"
            for key, value in m.items():
                row[f"{prefix}_{key}"] = value
            if m["suporte"] >= MIN_SUPPORT and m["confianca"] >= MIN_CONFIDENCE and m["lift"] >= MIN_LIFT:
                municipality_classes.append(prefix)
        if len(municipality_classes) == 2:
            row["classificacao"] = "ESTAVEL_NOS_DOIS_MUNICIPIOS"
        elif municipality_classes == ["pa"]:
            row["classificacao"] = "ESPECIFICA_SAO_FELIX_DO_XINGU"
        elif municipality_classes == ["sp"]:
            row["classificacao"] = "ESPECIFICA_PRESIDENTE_PRUDENTE"
        else:
            row["classificacao"] = "NAO_CLASSIFICADA"
        filtered.append(row)

    filtered.sort(key=lambda r: (-float(r["lift_global"]), -float(r["suporte_global"])))
    stable = [r for r in filtered if r["classificacao"] == "ESTAVEL_NOS_DOIS_MUNICIPIOS"]
    specific = [r for r in filtered if r["classificacao"] != "NAO_CLASSIFICADA"]

    thematic_dims = {
        "APP", "HIDROGRAFIA", "POUSIO", "SERVIDAO_ADMINISTRATIVA",
        "USO_RESTRITO", "VEGETACAO_NATIVA", "RESERVA_LEGAL",
    }

    def interpretable(rule: dict[str, object]) -> bool:
        items = parse_items(rule["itens_uniao"])
        dims = {item_dimension(item) for item in items}
        # Evita regras explicadas apenas por faixas de area e evita a
        # codificacao direta do municipio/UF nas regras selecionadas.
        return bool(dims & thematic_dims) and not ({"UF", "MUNICIPIO"} & dims)

    def choose_diverse(rows: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
        chosen: list[dict[str, object]] = []
        used_signatures: set[tuple[str, ...]] = set()
        for row in rows:
            dims = {
                item_dimension(item)
                for item in parse_items(row["itens_uniao"])
                if item_dimension(item) in thematic_dims
            }
            signature = tuple(sorted(dims))
            if signature in used_signatures:
                continue
            chosen.append(row)
            used_signatures.add(signature)
            if len(chosen) >= limit:
                break
        # Se a diversidade disponível não alcançar o limite, completa pela
        # ordem estatística, sem inventar regras.
        if len(chosen) < limit:
            for row in rows:
                if row not in chosen:
                    chosen.append(row)
                    if len(chosen) >= limit:
                        break
        return chosen

    stable_interpretable = sorted(
        [r for r in stable if interpretable(r)],
        key=lambda r: (-float(r["lift_global"]), -float(r["suporte_global"])),
    )
    pa_interpretable = sorted(
        [r for r in specific if r["classificacao"] == "ESPECIFICA_SAO_FELIX_DO_XINGU" and interpretable(r)],
        key=lambda r: (-float(r["pa_lift"]), -float(r["pa_suporte"])),
    )
    sp_interpretable = sorted(
        [r for r in specific if r["classificacao"] == "ESPECIFICA_PRESIDENTE_PRUDENTE" and interpretable(r)],
        key=lambda r: (-float(r["sp_lift"]), -float(r["sp_suporte"])),
    )
    selected = (
        choose_diverse(stable_interpretable, 4)
        + choose_diverse(pa_interpretable, 4)
        + choose_diverse(sp_interpretable, 4)
    )

    def write(path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fields = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    fields.append(key)
                    seen.add(key)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

    write(results / "regras_filtradas_comparacao.csv", filtered)
    write(results / "regras_candidatas_artigo.csv", selected)
    summary = {
        "regras_brutas": len(raw_rules),
        "regras_apos_filtros": len(filtered),
        "regras_candidatas_artigo": len(selected),
        "regras_estaveis_nos_dois_municipios": len(stable),
        "classes_especificas": {
            k: sum(r["classificacao"] == k for r in filtered)
            for k in sorted({r["classificacao"] for r in filtered})
        },
        "descartes": dict(discarded),
        "limiares": {
            "suporte_minimo": MIN_SUPPORT,
            "confianca_minima": MIN_CONFIDENCE,
            "lift_minimo": MIN_LIFT,
            "cobertura_minima": MIN_COVERAGE,
        },
    }
    (results / "resumo_auditoria_regras.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
