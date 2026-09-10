"""Gold: as 3 análises sobre o silver (ADR-0007).

Funções puras sobre DataFrames: recebem os DFs do silver já carregados (não leem
Parquet diretamente) e são determinísticas, mesma entrada, mesma saída.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def forca(stats: DataFrame) -> DataFrame:
    """DF[pokemon_id, forca] = soma de TODOS os base_stat por pokémon.

    Cacheada: reusada por `q1_multitype_above_avg` e `q3_top5_versatility`. O
    `.cache()` marca o plano lógico analisado no CacheManager do Spark. Chamadas
    independentes de `forca(stats)` a partir de Q1 e Q3 (mesmo `stats` de entrada)
    reaproveitam os dados já materializados, mesmo sendo objetos Python distintos.
    """
    df = stats.groupBy("pokemon_id").agg(F.sum("base_stat").alias("forca"))
    df.cache()
    return df


def _n_types(types: DataFrame) -> DataFrame:
    """DF[pokemon_id, n_types] = contagem de tipos distintos por pokémon."""
    return types.groupBy("pokemon_id").agg(
        F.countDistinct("type_name").alias("n_types")
    )


def q1_multitype_above_avg(
    pokemon: DataFrame, types: DataFrame, stats: DataFrame
) -> tuple[int, DataFrame]:
    """Quantos pokémons são multi-tipo E têm força acima da média?

    PEGADINHA do enunciado: "média geral da força" é a média das FORÇAS por
    pokémon (uma força por pokémon, `avg(forca)`), não a média linha a linha de
    `base_stat` (que teria um valor por combinação pokémon×stat, pesando errado
    pokémons com mais stats registrados).
    """
    forca_df = forca(stats)
    n_types_df = _n_types(types)

    media_forca = forca_df.agg(F.avg("forca")).first()[0]

    detalhe = (
        forca_df.join(F.broadcast(n_types_df), "pokemon_id")
        .filter((F.col("n_types") > 1) & (F.col("forca") > media_forca))
        .join(F.broadcast(pokemon.select("pokemon_id", "name")), "pokemon_id")
        .select("pokemon_id", "name", "forca", "n_types")
    )
    resultado = detalhe.count()
    return resultado, detalhe


def q2_abilities_exclusive_multitype(
    types: DataFrame, abilities: DataFrame
) -> DataFrame:
    """DF[ability_name] com as abilities que NUNCA aparecem em pokémon de tipo único.

    Lógica: todas as abilities distintas MENOS as que aparecem em algum pokémon
    mono-tipo (`subtract`). Não é "aparece em algum multi-tipo" (isso deixaria
    passar abilities que também aparecem em mono), é "nunca aparece em mono".
    Como toda ability vem de algum pokémon, o que sobra do `subtract` só pode
    vir de pokémons multi-tipo.
    """
    n_types_df = _n_types(types)

    ability_por_pokemon = abilities.join(F.broadcast(n_types_df), "pokemon_id")
    abilities_em_mono = (
        ability_por_pokemon.filter(F.col("n_types") == 1)
        .select("ability_name")
        .distinct()
    )

    return abilities.select("ability_name").distinct().subtract(abilities_em_mono)


def q3_top5_versatility(
    pokemon: DataFrame, types: DataFrame, stats: DataFrame, abilities: DataFrame
) -> DataFrame:
    """DF[pokemon_id, name, versatility_score]: top 5 por versatilidade.

    score = (n_types * 2) + n_abilities + (soma_stats / 100). `n_abilities` conta
    TODAS as abilities distintas por pokémon, incluindo as com `is_hidden=true`.
    Empates são resolvidos por `pokemon_id` asc (tiebreaker determinístico).
    """
    forca_df = forca(stats)
    n_types_df = _n_types(types)
    n_abilities_df = abilities.groupBy("pokemon_id").agg(
        F.countDistinct("ability_name").alias("n_abilities")
    )

    combined = (
        forca_df.join(F.broadcast(n_types_df), "pokemon_id")
        .join(F.broadcast(n_abilities_df), "pokemon_id")
        .withColumn(
            "versatility_score",
            F.col("n_types") * 2 + F.col("n_abilities") + (F.col("forca") / 100),
        )
    )

    top5 = combined.orderBy(
        F.col("versatility_score").desc(), F.col("pokemon_id").asc()
    ).limit(5)

    return top5.join(
        F.broadcast(pokemon.select("pokemon_id", "name")), "pokemon_id"
    ).select("pokemon_id", "name", "versatility_score")
