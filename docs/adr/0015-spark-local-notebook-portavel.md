# ADR-0015: Ambiente Spark: local dockerizado + notebook portável (não Databricks/Colab)

**Status.** Aceito.

## Contexto

O enunciado recomenda Databricks Community Edition ou Google Colab para rodar Spark, mas deixa
livre ("você pode utilizar o ambiente da sua preferência"). Preciso decidir onde rodar e,
sobretudo, o que entregar como `notebook.ipynb` no repositório público.

## Decisão

Entregar o Spark como **PySpark local dockerizado** (roda com um comando, sem conta externa) e
escrever o notebook em **PySpark "vanilla"**, sem APIs exclusivas do Databricks (`display`,
`dbutils`, sessão pré-provida, Delta). Assim o mesmo notebook também roda em Colab e Databricks.
Opcional: CI executando o notebook de ponta a ponta (papermill) como prova de reprodutibilidade.

## Alternativas

- *Databricks Community Edition (o recomendado):* zero setup de Spark, mas prende o notebook ao
  ambiente deles (`display`/`dbutils`) e ele não roda na máquina do avaliador, risco de
  reprodutibilidade.
- *Google Colab:* portável com células de `pip install pyspark`, mas "o notebook instala o
  próprio Spark" é frágil e não tem grau de container.

## Consequências

- (+) Reprodutível de verdade: `docker compose up`, sem conta; e o notebook ainda roda em
  Colab/Databricks.
- (+) Sinal de engenharia forte e coerente com o resto do repo (run local garantido, Docker em
  tudo).
- (−) Dockerizar Spark dá algum trabalho vs clicar "Create Notebook" no Databricks, baixo risco
  para quem usa Spark no dia a dia.
