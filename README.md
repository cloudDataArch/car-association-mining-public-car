# Mineração exploratória de regras de associação em dados públicos do CAR

Este repositório reúne os dados, o código e as saídas usados no estudo sobre padrões de coocorrência em registros públicos do Cadastro Ambiental Rural (CAR).

## Escopo

O estudo compara São Félix do Xingu (PA) e Presidente Prudente (SP). A unidade de análise é o registro de imóvel identificado por cod_imovel. As camadas públicas utilizadas são: área do imóvel, APP, área consolidada, área de pousio, hidrografia, reserva legal, servidão administrativa, uso restrito e vegetação nativa.

Os arquivos foram obtidos no portal oficial Consulta Pública do CAR (https://consulta.car.gov.br/geoservices), em 21 de setembro de 2026. A ausência de um registro em uma camada significa apenas ausência no arquivo público baixado; não é uma afirmação sobre a inexistência do fenômeno no imóvel.

## Conteúdo

- data/public_car/: 18 CSVs municipais públicos usados na preparação;
- pipeline_public_car_jupyter.py: script executável em Jupyter Notebook;
- exec_pipeline_public_car.ipynb: notebook de execução do script;
- exec_pipeline_public_car_executed.ipynb: notebook executado com os resultados desta versão;
- manifesto_fontes.csv: identificação das camadas e dos arquivos;
- results/: transações, itemsets, regras e resumos gerados pela execução;
- mensagem_para_Carlos_Leite.txt: resumo para leitura técnica do especialista.

## Execução

O script usa Python, pandas, numpy e mlxtend. O notebook executado usa a pasta data/public_car/ e grava novas saídas em results_runtime/. Para repetir no Jupyter:

    %pip install -r requirements.txt

Depois, abra exec_pipeline_public_car.ipynb e execute a célula. O fluxo transforma cada imóvel em uma transação e executa Apriori e Eclat com suporte mínimo de 1%, confiança mínima de 60% e tamanho máximo de itemset igual a três.

As regras resultantes são padrões descritivos de coocorrência. Não constituem diagnóstico automático de irregularidade, fraude, propriedade, conflito fundiário ou não conformidade ambiental.
