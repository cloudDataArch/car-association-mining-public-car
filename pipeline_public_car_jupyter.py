"""Pipeline simples e reproduzível para mineração exploratória em dados públicos do CAR.

Uso no Jupyter:
    1. ajuste DATA_DIR;
    2. execute o arquivo ou copie as células para o notebook;
    3. chame run_pipeline().

O script não acessa Trino, Iceberg, GOLD, SNCR, SIGEF ou bases restritas.
"""

from pathlib import Path
from itertools import combinations
import math
import numpy as np
import pandas as pd

DATA_DIR = Path(r"D:\USUARIO_CELIO\Downloads")
OUTPUT_DIR = DATA_DIR / "saida_car"
MIN_SUPPORT = 0.01
MIN_CONFIDENCE = 0.60
MAX_LEN = 3

MUNICIPALITIES = {
    "PA_São Félix do Xingu": {"uf": "PA", "municipio": "São Félix do Xingu"},
    "SP_Presidente Prudente": {"uf": "SP", "municipio": "Presidente Prudente"},
}

LAYERS = {
    "APP": "APP",
    "AREA_CONSOLIDADA": "Área consolidada",
    "AREA_POUSIO": "Área de pousio",
    "HIDROGRAFIA": "Hidrografia",
    "RESERVA_LEGAL": "Reserva legal",
    "SERVIDAO_ADMINISTRATIVA": "Servidão administrativa",
    "USO_RESTRITO": "Uso restrito",
    "VEGETACAO_NATIVA": "Vegetação nativa",
}


def read_public_csv(path: Path) -> pd.DataFrame:
    """Lê CSV do portal CAR, que normalmente usa ; e vírgula decimal."""
    return pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")


def numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype("string").str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
        errors="coerce",
    )


def find_file(prefix: str, suffix: str) -> Path:
    candidates = sorted(DATA_DIR.glob(f"{prefix}_{suffix}.csv"))
    if not candidates:
        raise FileNotFoundError(f"Arquivo não encontrado: {prefix}_{suffix}.csv")
    return candidates[0]


def area_band(value):
    if pd.isna(value):
        return "desconhecida"
    if value < 4:
        return "<4 ha"
    if value < 15:
        return "4-15 ha"
    if value < 100:
        return "15-100 ha"
    if value < 1000:
        return "100-1000 ha"
    return ">=1000 ha"


def build_transactions() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_properties = []
    layer_counts = []

    for prefix, info in MUNICIPALITIES.items():
        prop = read_public_csv(find_file(prefix, "AREA_IMOVEL"))
        prop["cod_imovel"] = prop["cod_imovel"].astype("string").str.strip()
        prop = prop.drop_duplicates("cod_imovel").copy()
        prop["municipio"] = info["municipio"]
        prop["uf"] = info["uf"]
        prop["area_ha"] = numeric_series(prop.get("num_area", pd.Series(index=prop.index)))
        prop["mod_fiscal_num"] = numeric_series(prop.get("mod_fiscal", pd.Series(index=prop.index)))
        prop["area_band"] = prop["area_ha"].map(area_band)
        prop["mod_fiscal_band"] = pd.cut(
            prop["mod_fiscal_num"],
            bins=[-np.inf, 1, 4, 10, np.inf],
            labels=["<1 módulo", "1-4 módulos", "4-10 módulos", ">=10 módulos"],
        ).astype("string").fillna("desconhecida")

        base = prop[["cod_imovel", "uf", "municipio", "area_band", "mod_fiscal_band", "ind_tipo", "ind_status"]].copy()
        for key, label in LAYERS.items():
            layer = read_public_csv(find_file(prefix, key))
            layer["cod_imovel"] = layer["cod_imovel"].astype("string").str.strip()
            ids = set(layer["cod_imovel"].dropna())
            base[f"{key}_presente"] = base["cod_imovel"].isin(ids)
            layer_counts.append({
                "uf": info["uf"],
                "municipio": info["municipio"],
                "camada": label,
                "registros_arquivo": len(layer),
                "imoveis_distintos": layer["cod_imovel"].nunique(dropna=True),
            })
        all_properties.append(base)

    properties = pd.concat(all_properties, ignore_index=True)
    transactions = []
    for _, row in properties.iterrows():
        items = {
            f"UF={row['uf']}",
            f"MUNICIPIO={row['municipio']}",
            f"AREA={row['area_band']}",
            f"MOD_FISCAL={row['mod_fiscal_band']}",
            f"TIPO={row.get('ind_tipo', 'desconhecido')}",
            f"STATUS={row.get('ind_status', 'desconhecido')}",
        }
        for key in LAYERS:
            items.add(f"{key}={'sim' if bool(row[f'{key}_presente']) else 'nao'}")
        transactions.append(sorted(items))

    return properties, pd.DataFrame({"cod_imovel": properties["cod_imovel"], "items": transactions}), pd.DataFrame(layer_counts)


def eclat(transactions, min_support=MIN_SUPPORT, max_len=MAX_LEN):
    n = len(transactions)
    tidsets = {}
    for tid, items in enumerate(transactions):
        for item in items:
            tidsets.setdefault(item, set()).add(tid)

    frequent = {}

    def visit(prefix, candidates):
        for i, (item, tids) in enumerate(candidates):
            support = len(tids) / n
            if support < min_support:
                continue
            itemset = tuple(sorted(prefix + [item]))
            frequent[itemset] = support
            if len(itemset) >= max_len:
                continue
            suffix = []
            for other, other_tids in candidates[i + 1:]:
                inter = tids & other_tids
                if len(inter) / n >= min_support:
                    suffix.append((other, inter))
            visit(list(itemset), suffix)

    visit([], sorted(tidsets.items()))
    return pd.DataFrame([
        {"itemsets": "; ".join(items), "support": support, "length": len(items)}
        for items, support in frequent.items()
    ]).sort_values(["support", "length"], ascending=[False, True])


def apriori_rules(transactions):
    from mlxtend.preprocessing import TransactionEncoder
    from mlxtend.frequent_patterns import apriori, association_rules

    te = TransactionEncoder()
    encoded = te.fit(transactions).transform(transactions)
    one_hot = pd.DataFrame(encoded, columns=te.columns_)
    itemsets = apriori(one_hot, min_support=MIN_SUPPORT, use_colnames=True, max_len=MAX_LEN)
    rules = association_rules(itemsets, metric="confidence", min_threshold=MIN_CONFIDENCE)
    return itemsets, rules


def run_pipeline(data_dir=None, output_dir=None):
    global DATA_DIR, OUTPUT_DIR
    if data_dir is not None:
        DATA_DIR = Path(data_dir)
    if output_dir is not None:
        OUTPUT_DIR = Path(output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    properties, tx_df, coverage = build_transactions()
    transactions = tx_df["items"].tolist()
    itemsets, rules = apriori_rules(transactions)
    eclat_itemsets = eclat(transactions)

    properties.to_csv(OUTPUT_DIR / "imoveis_integrados.csv", index=False, encoding="utf-8-sig")
    tx_df.to_csv(OUTPUT_DIR / "transacoes_car.csv", index=False, encoding="utf-8-sig")
    coverage.to_csv(OUTPUT_DIR / "cobertura_camadas.csv", index=False, encoding="utf-8-sig")
    itemsets.to_csv(OUTPUT_DIR / "itemsets_apriori.csv", index=False, encoding="utf-8-sig")
    eclat_itemsets.to_csv(OUTPUT_DIR / "itemsets_eclat.csv", index=False, encoding="utf-8-sig")
    rules.to_csv(OUTPUT_DIR / "regras_apriori.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame([{
        "imoveis_total": len(properties),
        "imoveis_PA": int((properties["uf"] == "PA").sum()),
        "imoveis_SP": int((properties["uf"] == "SP").sum()),
        "itemsets_apriori": len(itemsets),
        "itemsets_eclat": len(eclat_itemsets),
        "regras_apriori": len(rules),
        "min_support": MIN_SUPPORT,
        "min_confidence": MIN_CONFIDENCE,
        "max_len": MAX_LEN,
    }])
    summary.to_csv(OUTPUT_DIR / "resumo_execucao.csv", index=False, encoding="utf-8-sig")
    return summary, properties, itemsets, eclat_itemsets, rules


# No Jupyter, depois de ajustar DATA_DIR:
# resultado = run_pipeline()
