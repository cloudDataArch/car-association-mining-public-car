"""Pipeline de mineracao com dados abertos do CAR/SICAR.

Uso previsto:
    python pipeline_dados_abertos_car.py <pasta_com_csvs_car> <pasta_saida>

O script foi escrito para os CSVs baixados no portal publico
https://consulta.car.gov.br/geoservices, filtrados por municipio.

Ele nao usa a camada GOLD, Trino ou dados internos. A unidade principal e o
imovel rural declarado no CAR, preferencialmente vindo da camada
"Perimetros dos Imoveis". As demais camadas ambientais entram como itens de
presenca ou faixas de area por imovel, quando houver coluna de identificacao
compativel.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import re
import time
import tracemalloc
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


TARGET_MUNICIPIOS = {
    ("PA", "SAO_FELIX_DO_XINGU"),
    ("SP", "PRESIDENTE_PRUDENTE"),
}

ID_CANDIDATES = [
    "cod_imovel",
    "codigo_imovel",
    "codigo_do_imovel",
    "codigo_car",
    "cod_car",
    "car",
    "id_imovel",
    "idt_imovel",
    "numero_do_car",
    "registro_car",
]

UF_CANDIDATES = ["uf", "estado", "unidade_federativa", "sg_uf"]
MUN_CANDIDATES = ["municipio", "nome_municipio", "nom_municipio", "município"]
AREA_CANDIDATES = [
    "area",
    "area_ha",
    "area_imovel",
    "area_total",
    "area_total_ha",
    "num_area",
    "hectares",
]
TYPE_CANDIDATES = ["tipo_imovel", "tipo", "categoria", "ind_tipo_imovel", "ind_tipo", "des_tipo_imovel"]
STATUS_CANDIDATES = ["status", "situacao", "situacao_imovel", "condicao", "ind_status", "des_condic"]
MODULE_CANDIDATES = ["modulos_fiscais", "modulo_fiscal", "qtd_modulos", "num_modulo_fiscal", "mod_fiscal"]


def norm_text(value: str | None) -> str:
    value = unicodedata.normalize("NFD", (value or "").strip().upper())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r"\s+", "_", value)
    return re.sub(r"[^A-Z0-9_.-]", "_", value).strip("_")


def norm_col(value: str | None) -> str:
    return norm_text(value).lower()


def parse_number(value: str | None) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return float(raw)
    except ValueError:
        return None


def find_col(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {norm_col(c): c for c in columns}
    for candidate in candidates:
        if norm_col(candidate) in normalized:
            return normalized[norm_col(candidate)]
    for c in columns:
        nc = norm_col(c)
        if any(norm_col(candidate) in nc for candidate in candidates):
            return c
    return None


def read_csv_flexible(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    delimiters = [";", ",", "\t"]
    last_error: Exception | None = None
    for encoding in encodings:
        for delimiter in delimiters:
            try:
                with path.open("r", encoding=encoding, newline="") as f:
                    sample = f.read(4096)
                    if delimiter not in sample and delimiter != ",":
                        continue
                    f.seek(0)
                    reader = csv.DictReader(f, delimiter=delimiter)
                    rows = list(reader)
                    columns = reader.fieldnames or []
                    if columns and rows:
                        return rows, columns, f"{encoding}/{delimiter}"
            except Exception as exc:  # pragma: no cover - diagnostic fallback
                last_error = exc
    raise RuntimeError(f"Nao foi possivel ler {path}: {last_error}")


def layer_name(path: Path) -> str:
    name = path.stem
    name = re.sub(r"[_-]+", " ", name)
    aliases = {
        "PERIMETROS DOS IMOVEIS": "PERIMETRO_IMOVEL",
        "PERIMETRO DOS IMOVEIS": "PERIMETRO_IMOVEL",
        # O portal público também disponibiliza a tabela tabular da área do
        # imóvel com o sufixo AREA_IMOVEL. Ela é a unidade principal, não uma
        # camada temática ambiental.
        "AREA IMOVEL": "PERIMETRO_IMOVEL",
        "AREA CONSOLIDADA": "AREA_CONSOLIDADA",
        "REMANESCENTE DE VEGETACAO NATIVA": "VEGETACAO_NATIVA",
        "RESERVA LEGAL": "RESERVA_LEGAL",
        "AREA DE PRESERVACAO PERMANENTE": "APP",
        "APP": "APP",
        "AREA DE POUSIO": "POUSIO",
        "POUSIO": "POUSIO",
        "VEGETACAO NATIVA": "VEGETACAO_NATIVA",
        "USO RESTRITO": "USO_RESTRITO",
        "SERVIDAO ADMINISTRATIVA": "SERVIDAO_ADMINISTRATIVA",
        "HIDROGRAFIA": "HIDROGRAFIA",
    }
    normalized = norm_text(name)
    for key, value in aliases.items():
        if norm_text(key) in normalized:
            return value
    return normalized[:60] or "CAMADA"


def area_band(value: float | None) -> str:
    if value is None or value < 0:
        return "NAO_INFORMADA"
    if value < 4:
        return "MENOR_4_HA"
    if value < 15:
        return "4_A_15_HA"
    if value < 100:
        return "15_A_100_HA"
    if value < 1000:
        return "100_A_1000_HA"
    return "1000_HA_OU_MAIS"


def module_band(value: float | None) -> str:
    if value is None or value < 0:
        return "NAO_INFORMADO"
    if value < 1:
        return "MENOR_1_MODULO"
    if value < 4:
        return "1_A_4_MODULOS"
    if value < 15:
        return "4_A_15_MODULOS"
    return "15_MODULOS_OU_MAIS"


def discover_files(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.rglob("*.csv")
        if p.is_file() and not p.name.startswith("transacoes")
    )


def build_dataset(input_dir: Path) -> tuple[list[dict[str, str]], dict[str, object]]:
    files = discover_files(input_dir)
    if not files:
        raise SystemExit(f"Nenhum CSV encontrado em {input_dir}")

    audit: dict[str, object] = {"arquivos": []}
    main: dict[str, dict[str, str]] = {}
    layer_presence: dict[str, set[str]] = defaultdict(set)
    layer_area: dict[tuple[str, str], float] = {}

    for path in files:
        rows, columns, fmt = read_csv_flexible(path)
        layer = layer_name(path)
        id_col = find_col(columns, ID_CANDIDATES)
        uf_col = find_col(columns, UF_CANDIDATES)
        mun_col = find_col(columns, MUN_CANDIDATES)
        area_col = find_col(columns, AREA_CANDIDATES)
        type_col = find_col(columns, TYPE_CANDIDATES)
        status_col = find_col(columns, STATUS_CANDIDATES)
        module_col = find_col(columns, MODULE_CANDIDATES)

        audit["arquivos"].append({
            "arquivo": str(path),
            "camada_detectada": layer,
            "formato_leitura": fmt,
            "linhas": len(rows),
            "colunas": columns,
            "coluna_id": id_col,
            "coluna_uf": uf_col,
            "coluna_municipio": mun_col,
            "coluna_area": area_col,
        })

        if not id_col:
            continue

        for row in rows:
            car_id = (row.get(id_col) or "").strip()
            if not car_id:
                continue
            layer_presence[layer].add(car_id)
            if area_col:
                area = parse_number(row.get(area_col))
                if area is not None:
                    layer_area[(car_id, layer)] = layer_area.get((car_id, layer), 0.0) + area

            # A unidade de análise é definida exclusivamente pela tabela
            # principal AREA_IMOVEL/PERIMETRO_IMOVEL. Uma feição que exista
            # apenas em uma camada temática não deve criar um novo imóvel no
            # dataset analítico.
            is_main = layer == "PERIMETRO_IMOVEL"
            if is_main:
                main.setdefault(car_id, {"codigo_car": car_id})
                rec = main[car_id]
                if uf_col and row.get(uf_col):
                    rec["uf"] = row.get(uf_col, "")
                if mun_col and row.get(mun_col):
                    rec["municipio"] = row.get(mun_col, "")
                if area_col and row.get(area_col):
                    rec["area_imovel_ha"] = row.get(area_col, "")
                if type_col and row.get(type_col):
                    rec["tipo_imovel"] = row.get(type_col, "")
                if status_col and row.get(status_col):
                    rec["status_imovel"] = row.get(status_col, "")
                if module_col and row.get(module_col):
                    rec["modulos_fiscais"] = row.get(module_col, "")

    records: list[dict[str, str]] = []
    all_layers = sorted(layer_presence)
    for car_id, rec in sorted(main.items()):
        uf = norm_text(rec.get("uf"))
        municipio = norm_text(rec.get("municipio"))
        if uf and municipio and (uf, municipio) not in TARGET_MUNICIPIOS:
            continue
        out = dict(rec)
        out["uf_norm"] = uf
        out["municipio_norm"] = municipio
        for layer in all_layers:
            out[f"tem_{layer}"] = "SIM" if car_id in layer_presence[layer] else "NAO"
            area = layer_area.get((car_id, layer))
            if area is not None:
                out[f"area_{layer}_ha"] = f"{area:.6f}"
        records.append(out)

    audit["total_imoveis_dataset"] = len(records)
    audit["camadas_detectadas"] = all_layers
    return records, audit


def transaction_from_record(row: dict[str, str]) -> frozenset[str]:
    items: set[str] = set()
    uf = norm_text(row.get("uf_norm") or row.get("uf")) or "NAO_INFORMADO"
    municipio = norm_text(row.get("municipio_norm") or row.get("municipio")) or "NAO_INFORMADO"
    items.add(f"UF={uf}")
    items.add(f"MUNICIPIO={municipio}")
    items.add(f"TIPO_IMOVEL={norm_text(row.get('tipo_imovel')) or 'NAO_INFORMADO'}")
    items.add(f"STATUS_CAR={norm_text(row.get('status_imovel')) or 'NAO_INFORMADO'}")
    items.add(f"FAIXA_AREA_IMOVEL={area_band(parse_number(row.get('area_imovel_ha')))}")
    items.add(f"FAIXA_MODULOS_FISCAIS={module_band(parse_number(row.get('modulos_fiscais')))}")

    thematic_count = 0
    for key, value in row.items():
        if key.startswith("tem_") and key != "tem_PERIMETRO_IMOVEL":
            layer = key[4:]
            flag = "SIM" if norm_text(value) == "SIM" else "NAO"
            if flag == "SIM":
                thematic_count += 1
            items.add(f"{layer}={flag}")
        elif (
            key.startswith("area_")
            and key.endswith("_ha")
            and key not in {"area_imovel_ha", "area_PERIMETRO_IMOVEL_ha"}
        ):
            layer = key[5:-3]
            items.add(f"FAIXA_AREA_{layer}={area_band(parse_number(value))}")

    if thematic_count == 0:
        # Com apenas a tabela AREA_IMOVEL, a ausência de temas não é uma
        # característica do imóvel; significa somente que as camadas
        # ambientais ainda não foram carregadas. Não transformar isso em item.
        pass
    elif thematic_count <= 2:
        items.add("QTD_TEMAS_AMBIENTAIS=1_A_2")
    elif thematic_count <= 5:
        items.add("QTD_TEMAS_AMBIENTAIS=3_A_5")
    else:
        items.add("QTD_TEMAS_AMBIENTAIS=6_OU_MAIS")
    return frozenset(items)


def dimension(item: str) -> str:
    return item.split("=", 1)[0]


def internally_consistent(itemset: frozenset[str]) -> bool:
    dims = [dimension(x) for x in itemset]
    return len(dims) == len(set(dims))


def count_support(transactions: list[frozenset[str]], itemset: frozenset[str]) -> int:
    return sum(itemset <= t for t in transactions)


def apriori(transactions: list[frozenset[str]], min_count: int, max_len: int) -> dict[frozenset[str], int]:
    counts = Counter(item for t in transactions for item in t)
    level = {frozenset([item]): count for item, count in counts.items() if count >= min_count}
    result = dict(level)
    for k in range(2, max_len + 1):
        prev = set(level)
        candidates = {
            a | b for a in prev for b in prev
            if len(a | b) == k and internally_consistent(a | b)
        }
        candidates = {
            c for c in candidates
            if all(frozenset(s) in prev for s in itertools.combinations(c, k - 1))
        }
        level = {c: count_support(transactions, c) for c in candidates}
        level = {c: n for c, n in level.items() if n >= min_count}
        result.update(level)
        if not level:
            break
    return result


def eclat(transactions: list[frozenset[str]], min_count: int, max_len: int) -> dict[frozenset[str], int]:
    vertical: dict[str, set[int]] = defaultdict(set)
    for tid, transaction in enumerate(transactions):
        for item in transaction:
            vertical[item].add(tid)
    result: dict[frozenset[str], int] = {}

    def visit(prefix: frozenset[str], candidates: list[tuple[str, set[int]]]) -> None:
        for i, (item, tids) in enumerate(candidates):
            current = prefix | {item}
            if len(tids) < min_count or not internally_consistent(current):
                continue
            result[current] = len(tids)
            if len(current) >= max_len:
                continue
            suffix = []
            for other, other_tids in candidates[i + 1:]:
                intersection = tids & other_tids
                if len(intersection) >= min_count:
                    suffix.append((other, intersection))
            visit(current, suffix)

    visit(frozenset(), sorted(vertical.items()))
    return result


def rule_metrics(
    counts: dict[frozenset[str], int],
    total: int,
    left: frozenset[str],
    right: frozenset[str],
) -> dict[str, float]:
    both = counts[left | right]
    left_count = counts.get(left) or count_support_from_counts(counts, left)
    right_count = counts.get(right) or count_support_from_counts(counts, right)
    support = both / total
    confidence = both / left_count if left_count else 0.0
    expected = right_count / total if total else 0.0
    lift = confidence / expected if expected else 0.0
    coverage = left_count / total if total else 0.0
    return {
        "suporte": support,
        "confianca": confidence,
        "lift": lift,
        "cobertura_antecedente": coverage,
    }


def count_support_from_counts(counts: dict[frozenset[str], int], itemset: frozenset[str]) -> int:
    if itemset in counts:
        return counts[itemset]
    return 0


def generate_rules(
    itemsets: dict[frozenset[str], int],
    total: int,
    min_confidence: float,
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    for itemset, count in itemsets.items():
        if len(itemset) < 2:
            continue
        for size in range(1, len(itemset)):
            for left_tuple in itertools.combinations(sorted(itemset), size):
                left = frozenset(left_tuple)
                right = itemset - left
                if not right:
                    continue
                metrics = rule_metrics(itemsets, total, left, right)
                if metrics["confianca"] < min_confidence:
                    continue
                rules.append({
                    "antecedente": " + ".join(sorted(left)),
                    "consequente": " + ".join(sorted(right)),
                    "contagem": count,
                    **metrics,
                })
    rules.sort(key=lambda r: (-float(r["lift"]), -float(r["confianca"]), -float(r["suporte"])))
    return rules


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # Registros de municípios/camadas diferentes podem conter campos
    # específicos (por exemplo, colunas de área derivadas do nome do arquivo).
    # A exportação precisa preservar a união dos campos, preenchendo os que
    # não existem em determinado registro com valor vazio.
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row.keys():
            if field not in seen:
                fields.append(field)
                seen.add(field)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--min-support", type=float, default=0.01)
    parser.add_argument("--min-confidence", type=float, default=0.60)
    parser.add_argument("--max-len", type=int, default=3)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records, audit = build_dataset(input_dir)
    transactions = [transaction_from_record(r) for r in records]
    total = len(transactions)
    if total == 0:
        raise SystemExit("Dataset vazio apos filtros. Confira municipio/UF ou arquivos baixados.")
    min_count = max(1, math.ceil(args.min_support * total))

    trans_rows = [
        {"codigo_car": r["codigo_car"], "itens": "|".join(sorted(t))}
        for r, t in zip(records, transactions)
    ]

    tracemalloc.start()
    start = time.perf_counter()
    apriori_sets = apriori(transactions, min_count, args.max_len)
    apriori_time = time.perf_counter() - start
    apriori_peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    tracemalloc.start()
    start = time.perf_counter()
    eclat_sets = eclat(transactions, min_count, args.max_len)
    eclat_time = time.perf_counter() - start
    eclat_peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    same_itemsets = apriori_sets == eclat_sets
    rules = generate_rules(apriori_sets, total, args.min_confidence)

    itemset_rows = [
        {"itemset": " + ".join(sorted(k)), "contagem": v, "suporte": v / total}
        for k, v in sorted(apriori_sets.items(), key=lambda x: (-len(x[0]), -x[1], sorted(x[0])))
    ]

    write_csv(output_dir / "dataset_analitico_car_aberto.csv", records)
    write_csv(output_dir / "transacoes_car_aberto.csv", trans_rows)
    write_csv(output_dir / "itemsets_frequentes_apriori.csv", itemset_rows)
    write_csv(output_dir / "regras_associacao_car_aberto.csv", rules)
    (output_dir / "auditoria_extracao_car_aberto.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "resumo_execucao_car_aberto.json").write_text(
        json.dumps({
            "total_transacoes": total,
            "min_support": args.min_support,
            "min_count": min_count,
            "min_confidence": args.min_confidence,
            "max_len": args.max_len,
            "itemsets_frequentes": len(apriori_sets),
            "regras": len(rules),
            "apriori_eclat_coincidem": same_itemsets,
            "tempo_apriori_seg": apriori_time,
            "tempo_eclat_seg": eclat_time,
            "memoria_apriori_mb": apriori_peak,
            "memoria_eclat_mb": eclat_peak,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "total_transacoes": total,
        "itemsets": len(apriori_sets),
        "regras": len(rules),
        "apriori_eclat_coincidem": same_itemsets,
        "saida": str(output_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
