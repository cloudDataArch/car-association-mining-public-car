# Material resumido para Carlos Eduardo Castilho Leite

## Objetivo do trabalho

O estudo avalia se técnicas de mineração de regras de associação podem revelar padrões de coocorrência em dados públicos do Cadastro Ambiental Rural (CAR). A análise compara dois municípios com perfis territoriais distintos:

- São Félix do Xingu, Pará;
- Presidente Prudente, São Paulo.

A unidade de análise é o imóvel/registro identificado por `cod_imovel`. Os dados são exclusivamente públicos, obtidos no portal oficial de consulta e download do CAR. Não são utilizados dados do Trino, Iceberg, GOLD, SNCR, SIGEF ou qualquer base institucional restrita.

## Fontes e camadas

Para cada município, o pacote contém a tabela principal `AREA_IMOVEL` e camadas temáticas públicas: APP, área consolidada, área de pousio, hidrografia, reserva legal, servidão administrativa, uso restrito e vegetação nativa.

As camadas são integradas pela chave `cod_imovel`. Para cada imóvel, o script cria itens categóricos e indicadores de presença ou ausência de registros nas camadas temáticas. A ausência significa apenas ausência de registro no arquivo público baixado; não significa inexistência do fenômeno no imóvel.

## Métodos

O fluxo foi organizado segundo CRISP-DM:

1. entendimento do problema e dos dados;
2. preparação e integração das camadas;
3. transformação dos imóveis em transações;
4. mineração com Apriori e Eclat;
5. comparação descritiva entre os municípios;
6. auditoria interpretativa das regras.

O script usa suporte mínimo de 1%, confiança mínima de 60% e tamanho máximo de itemset igual a três. As regras são indícios analíticos de coocorrência. Elas não constituem diagnóstico de fraude, irregularidade, propriedade, conflito fundiário ou não conformidade ambiental.

## O que se solicita ao especialista

Solicita-se uma leitura técnica dos resultados, especialmente sobre:

- adequação das variáveis e das categorias criadas;
- interpretação das diferenças entre São Félix do Xingu e Presidente Prudente;
- possíveis efeitos da natureza declaratória do CAR;
- riscos de interpretar ausência de registro como ausência de ocorrência;
- regras que merecem ser discutidas como padrões descritivos, sem conclusão jurídica.

## Como executar

1. Coloque os 18 CSVs públicos em uma única pasta.
2. Abra `pipeline_public_car_jupyter.py` no Jupyter Notebook ou copie suas células para um notebook.
3. Altere somente `DATA_DIR` para a pasta onde os CSVs foram salvos.
4. Execute o script.
5. Examine os arquivos gerados em `saida_car/`, principalmente `resumo_execucao.csv`, `regras_apriori.csv`, `regras_eclat.csv` e `transacoes_car.csv`.

Dependências principais: `pandas`, `numpy` e `mlxtend`. No Jupyter, se necessário, execute antes:

```python
%pip install pandas numpy mlxtend
```

