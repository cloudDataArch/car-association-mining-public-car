# Exploratory Association Rule Mining in Public CAR Data

This repository contains the reproducibility package for the paper **Exploratory Association Rule Mining in Public CAR Data: A Comparison of Two Brazilian Municipalities**.

The study uses public municipal extracts from the official [Consulta Pública do Cadastro Ambiental Rural](https://consulta.car.gov.br/geoservices). The comparison covers São Félix do Xingu, Pará, and Presidente Prudente, São Paulo. The unit of analysis is the CAR rural-property record identified by `cod_imovel`.

## Repository contents

- `artigo_car_publico_execucao.ipynb`: canonical execution notebook cited in the paper;
- `pipeline_dados_abertos_car.py`: canonical public-data preparation and Apriori/Eclat pipeline;
- `auditar_regras_car_aberto.py`: canonical rule-audit and candidate-selection script;
- `sensitivity_public_car_canonical.py`: support-threshold sensitivity experiment;
- `stability_candidate_rules_public_car.py`: stratified candidate-rule stability experiment;
- `data/public_car/`: the 18 public municipal CSV extracts used in the execution;
- `manifesto_fontes_publicas.csv`: source files, SHA-256 checksums, row counts, and distinct identifiers;
- `results/`: canonical public execution outputs used in the paper;
- `analysis/`: sensitivity and stability outputs;
- `article/`: article source and the contextual municipal figure.

## Canonical execution

The scripts use Python's standard library only. From the repository root:

```text
python pipeline_dados_abertos_car.py data/public_car results_reproduced --min-support 0.01 --min-confidence 0.60 --max-len 3
python auditar_regras_car_aberto.py results_reproduced
```

The first command creates the analytical dataset, transaction list, frequent itemsets, and raw rules. The second command applies the interpretive audit and writes the comparison and candidate-rule files.

## Sensitivity and stability checks

The sensitivity analysis repeats the canonical pipeline with minimum support values of 0.005, 0.010, and 0.020 while retaining confidence 0.60 and maximum itemset length 3:

```text
python sensitivity_public_car_canonical.py data/public_car analysis/sensitivity_public_car
```

The stability analysis evaluates the 12 candidate rules selected by the canonical audit in 30 stratified resamples. Each resample retains 80% of the records from each municipality:

```text
python stability_candidate_rules_public_car.py data/public_car results/regras_candidatas_artigo.csv analysis/stability_candidate_rules.csv --replications 30 --fraction 0.80 --seed 20261009
```

These checks are reported as computational robustness analyses. They do not establish legal validity, environmental compliance, ownership, fraud, or irregularity.

## Reproducibility record

The canonical article execution used 11,340 property transactions, 11,574 frequent itemsets, and 17,997 raw rules with minimum support 0.01, minimum confidence 0.60, and maximum itemset length 3. Apriori and Eclat produced the same frequent-itemset collection in that execution. The audit and interpretation files in `results/` preserve the subsequent filtering and comparison steps.

The public CSV extracts were downloaded on 21 September 2026. The manifest records their checksums so that a future download can be compared with the exact inputs used here.

## Interpretation boundary

The mined rules describe co-occurrence patterns in public CAR records. They are exploratory evidence for comparing the two municipal samples and are not automatic diagnoses of land-tenure status, environmental compliance, fraud, or illegality.
