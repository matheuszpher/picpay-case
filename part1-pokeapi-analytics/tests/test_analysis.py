"""Testes de src/analysis.py — SparkSession local, fixture pequena com respostas
calculadas NA MÃO (não só "rodou sem erro"). Nada de rede, nada de Parquet.

Fixture: 6 pokémons.
- bulbasaur(1) e ivysaur(2): multi-tipo (grass+poison).
- pidgey(5): multi-tipo (normal+flying).
- charmander(3), squirtle(4), rattata(6): mono-tipo.
- ability "overgrow" (1,2) e "keen-eye" (5): só aparecem em multi-tipo -> devem
  ENTRAR no resultado da Q2.
- ability "chlorophyll": aparece no bulbasaur (multi) E no charmander (mono) ->
  deve FICAR DE FORA da Q2 (não é "nunca em mono").
- ability "blaze"/"torrent"/"run-away": só em mono-tipo -> ficam de fora (trivial).
- squirtle(4) e rattata(6) têm o MESMO versatility_score de propósito, para
  provar que o tiebreaker (pokemon_id asc) decide quem entra no top 5.
"""

from __future__ import annotations

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from src import analysis

POKEMON_SCHEMA = StructType(
    [
        StructField("pokemon_id", IntegerType(), True),
        StructField("name", StringType(), True),
        StructField("height", IntegerType(), True),
        StructField("weight", IntegerType(), True),
        StructField("base_experience", IntegerType(), True),
    ]
)
TYPE_SCHEMA = StructType(
    [
        StructField("pokemon_id", IntegerType(), True),
        StructField("type_name", StringType(), True),
    ]
)
STATS_SCHEMA = StructType(
    [
        StructField("pokemon_id", IntegerType(), True),
        StructField("stat_name", StringType(), True),
        StructField("base_stat", IntegerType(), True),
    ]
)
ABILITY_SCHEMA = StructType(
    [
        StructField("pokemon_id", IntegerType(), True),
        StructField("ability_name", StringType(), True),
        StructField("is_hidden", BooleanType(), True),
    ]
)

POKEMON_ROWS = [
    (1, "bulbasaur", 7, 69, 64),
    (2, "ivysaur", 10, 130, 142),
    (3, "charmander", 6, 85, 62),
    (4, "squirtle", 5, 90, 63),
    (5, "pidgey", 3, 18, 50),
    (6, "rattata", 3, 35, 51),
]
TYPE_ROWS = [
    (1, "grass"),
    (1, "poison"),
    (2, "grass"),
    (2, "poison"),
    (3, "fire"),
    (4, "water"),
    (5, "normal"),
    (5, "flying"),
    (6, "normal"),
]
STATS_ROWS = [
    (1, "hp", 45),
    (1, "attack", 49),  # bulbasaur: forca = 94
    (2, "hp", 60),
    (2, "attack", 62),  # ivysaur: forca = 122
    (3, "hp", 39),
    (3, "attack", 52),  # charmander: forca = 91
    (4, "hp", 44),
    (4, "attack", 48),  # squirtle: forca = 92
    (5, "hp", 40),
    (5, "attack", 45),  # pidgey: forca = 85
    (6, "hp", 36),
    (6, "attack", 56),  # rattata: forca = 92 (empate com squirtle)
]
ABILITY_ROWS = [
    (1, "overgrow", False),
    (1, "chlorophyll", True),
    (2, "overgrow", False),
    (3, "blaze", False),
    (3, "chlorophyll", False),  # chlorophyll também em mono -> exclui da Q2
    (4, "torrent", False),
    (5, "keen-eye", False),
    (6, "run-away", False),
]


@pytest.fixture()
def dfs(spark):
    pokemon = spark.createDataFrame(POKEMON_ROWS, schema=POKEMON_SCHEMA)
    types = spark.createDataFrame(TYPE_ROWS, schema=TYPE_SCHEMA)
    stats = spark.createDataFrame(STATS_ROWS, schema=STATS_SCHEMA)
    abilities = spark.createDataFrame(ABILITY_ROWS, schema=ABILITY_SCHEMA)
    return pokemon, types, stats, abilities


# ---------------------------------------------------------------------------
# forca
# ---------------------------------------------------------------------------


def test_forca_sums_all_base_stat_per_pokemon(dfs):
    _, _, stats, _ = dfs

    result = {row.pokemon_id: row.forca for row in analysis.forca(stats).collect()}

    assert result == {1: 94, 2: 122, 3: 91, 4: 92, 5: 85, 6: 92}


def test_forca_result_is_cached(dfs):
    _, _, stats, _ = dfs

    result = analysis.forca(stats)

    assert result.storageLevel.useMemory is True


# ---------------------------------------------------------------------------
# q1_multitype_above_avg
# ---------------------------------------------------------------------------


def test_q1_uses_average_of_forca_per_pokemon_not_average_of_raw_base_stat(dfs):
    """Trava a pegadinha: a média certa é das 6 forças (576/6=96.0), não das 12
    linhas de base_stat (576/12=48.0). Com o divisor errado (48.0), quase todo
    multi-tipo passaria (94, 122 e 85 > 48) e o resultado seria 3, não 1."""
    pokemon, types, stats, _ = dfs

    resultado, _ = analysis.q1_multitype_above_avg(pokemon, types, stats)

    assert resultado == 1


def test_q1_detalhe_contains_exactly_the_matching_pokemon(dfs):
    pokemon, types, stats, _ = dfs

    resultado, detalhe = analysis.q1_multitype_above_avg(pokemon, types, stats)

    rows = detalhe.collect()
    assert resultado == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.pokemon_id == 2
    assert row.name == "ivysaur"
    assert row.forca == 122
    assert row.n_types == 2


# ---------------------------------------------------------------------------
# q2_abilities_exclusive_multitype
# ---------------------------------------------------------------------------


def test_q2_includes_abilities_that_only_appear_in_multitype(dfs):
    _, types, _, abilities = dfs

    result = {
        row.ability_name
        for row in analysis.q2_abilities_exclusive_multitype(types, abilities).collect()
    }

    assert "overgrow" in result  # só em bulbasaur(multi) e ivysaur(multi)
    assert "keen-eye" in result  # só em pidgey (multi)


def test_q2_excludes_ability_shared_between_multitype_and_monotype(dfs):
    _, types, _, abilities = dfs

    result = {
        row.ability_name
        for row in analysis.q2_abilities_exclusive_multitype(types, abilities).collect()
    }

    # chlorophyll aparece no bulbasaur (multi) E no charmander (mono) -> não é
    # "nunca em mono", então tem que ficar de fora, mesmo aparecendo em multi.
    assert "chlorophyll" not in result


def test_q2_excludes_abilities_only_in_monotype(dfs):
    _, types, _, abilities = dfs

    result = {
        row.ability_name
        for row in analysis.q2_abilities_exclusive_multitype(types, abilities).collect()
    }

    assert "blaze" not in result
    assert "torrent" not in result
    assert "run-away" not in result


def test_q2_exact_result_set(dfs):
    _, types, _, abilities = dfs

    result = {
        row.ability_name
        for row in analysis.q2_abilities_exclusive_multitype(types, abilities).collect()
    }

    assert result == {"overgrow", "keen-eye"}


# ---------------------------------------------------------------------------
# q3_top5_versatility
# ---------------------------------------------------------------------------


def test_q3_top5_ranking_and_tiebreak_by_pokemon_id(dfs):
    pokemon, types, stats, abilities = dfs

    result = analysis.q3_top5_versatility(pokemon, types, stats, abilities)
    rows = result.orderBy(
        F.col("versatility_score").desc(), F.col("pokemon_id").asc()
    ).collect()

    assert len(rows) == 5
    assert [r.pokemon_id for r in rows] == [1, 2, 5, 3, 4]
    assert [r.name for r in rows] == [
        "bulbasaur",
        "ivysaur",
        "pidgey",
        "charmander",
        "squirtle",
    ]
    assert [r.versatility_score for r in rows] == pytest.approx(
        [6.94, 6.22, 5.85, 4.91, 3.92]
    )


def test_q3_excludes_the_tied_pokemon_with_larger_id(dfs):
    """squirtle(4) e rattata(6) empatam em 3.92 — só squirtle deve entrar no
    top 5, porque o tiebreaker é pokemon_id asc (4 < 6)."""
    pokemon, types, stats, abilities = dfs

    result = analysis.q3_top5_versatility(pokemon, types, stats, abilities)
    ids = {row.pokemon_id for row in result.collect()}

    assert 4 in ids
    assert 6 not in ids
