"""Testes de src/quality.py: SparkSession local, fixtures pequenas, nada de rede.

Cada invariante crítica tem um teste de caso feliz e um de violação, garantindo que
`run_quality_report` realmente levanta `DataQualityError` (fail loud, não só log).
"""

from __future__ import annotations

import pytest
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from src import quality

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


def _pokemon_df(spark, rows):
    return spark.createDataFrame(rows, schema=POKEMON_SCHEMA)


def _type_df(spark, rows):
    return spark.createDataFrame(rows, schema=TYPE_SCHEMA)


def _stats_df(spark, rows):
    return spark.createDataFrame(rows, schema=STATS_SCHEMA)


def _ability_df(spark, rows):
    return spark.createDataFrame(rows, schema=ABILITY_SCHEMA)


VALID_POKEMON_ROWS = [
    (1, "bulbasaur", 7, 69, 64),
    (4, "charmander", 6, 85, 62),
    (7, "squirtle", 5, 90, 63),
]
VALID_TYPE_ROWS = [(1, "grass"), (1, "poison"), (4, "fire"), (7, "water")]
VALID_STATS_ROWS = [(1, "hp", 45), (4, "hp", 39), (7, "hp", 44)]
VALID_ABILITY_ROWS = [
    (1, "overgrow", False),
    (4, "blaze", False),
    (7, "torrent", False),
]


def _valid_dfs(spark):
    return {
        "pokemon": _pokemon_df(spark, VALID_POKEMON_ROWS),
        "pokemon_type": _type_df(spark, VALID_TYPE_ROWS),
        "pokemon_stats": _stats_df(spark, VALID_STATS_ROWS),
        "pokemon_ability": _ability_df(spark, VALID_ABILITY_ROWS),
    }


# ---------------------------------------------------------------------------
# check_not_null
# ---------------------------------------------------------------------------


def test_check_not_null_happy_path(spark):
    df = _pokemon_df(spark, VALID_POKEMON_ROWS)

    result = quality.check_not_null(df, ["pokemon_id", "name"])

    assert result["passed"] is True


def test_check_not_null_detects_null_pk(spark):
    df = _pokemon_df(spark, VALID_POKEMON_ROWS + [(None, "missingno", 1, 1, 1)])

    result = quality.check_not_null(df, ["pokemon_id"])

    assert result["passed"] is False
    assert "1 nulos" in result["details"]


# ---------------------------------------------------------------------------
# check_unique
# ---------------------------------------------------------------------------


def test_check_unique_happy_path(spark):
    df = _pokemon_df(spark, VALID_POKEMON_ROWS)

    result = quality.check_unique(df, ["pokemon_id"])

    assert result["passed"] is True


def test_check_unique_detects_duplicate_pk(spark):
    df = _pokemon_df(spark, VALID_POKEMON_ROWS + [(1, "bulbasaur-dup", 7, 69, 64)])

    result = quality.check_unique(df, ["pokemon_id"])

    assert result["passed"] is False
    assert "1 chave" in result["details"]


def test_check_unique_composite_key_happy_path(spark):
    df = _type_df(spark, VALID_TYPE_ROWS)

    result = quality.check_unique(df, ["pokemon_id", "type_name"])

    assert result["passed"] is True


def test_check_unique_composite_key_detects_duplicate(spark):
    df = _type_df(spark, VALID_TYPE_ROWS + [(1, "grass")])  # duplica (1, grass)

    result = quality.check_unique(df, ["pokemon_id", "type_name"])

    assert result["passed"] is False


# ---------------------------------------------------------------------------
# check_referential
# ---------------------------------------------------------------------------


def test_check_referential_happy_path(spark):
    pokemon = _pokemon_df(spark, VALID_POKEMON_ROWS)
    types = _type_df(spark, VALID_TYPE_ROWS)

    result = quality.check_referential(types, pokemon)

    assert result["passed"] is True
    assert "0 órfão" in result["details"]


def test_check_referential_detects_orphan(spark):
    pokemon = _pokemon_df(spark, VALID_POKEMON_ROWS)
    types = _type_df(
        spark, VALID_TYPE_ROWS + [(999, "ghost")]
    )  # 999 não existe em pokemon

    result = quality.check_referential(types, pokemon)

    assert result["passed"] is False
    assert "1 órfão" in result["details"]


# ---------------------------------------------------------------------------
# run_quality_report - caso feliz
# ---------------------------------------------------------------------------


def test_run_quality_report_happy_path_does_not_raise_and_prints_report(spark, capsys):
    dfs = _valid_dfs(spark)

    quality.run_quality_report(dfs)  # não deve levantar

    captured = capsys.readouterr()
    assert "RELATÓRIO DE QUALIDADE" in captured.out
    assert "FAIL" not in captured.out


# ---------------------------------------------------------------------------
# run_quality_report - cada invariante critica violada deve levantar
# ---------------------------------------------------------------------------


def test_run_quality_report_raises_on_null_pk(spark):
    dfs = _valid_dfs(spark)
    dfs["pokemon"] = _pokemon_df(
        spark, VALID_POKEMON_ROWS + [(None, "missingno", 1, 1, 1)]
    )

    with pytest.raises(quality.DataQualityError):
        quality.run_quality_report(dfs)


def test_run_quality_report_raises_on_duplicate_pk(spark):
    dfs = _valid_dfs(spark)
    dfs["pokemon"] = _pokemon_df(
        spark, VALID_POKEMON_ROWS + [(1, "bulbasaur-dup", 7, 69, 64)]
    )

    with pytest.raises(quality.DataQualityError):
        quality.run_quality_report(dfs)


def test_run_quality_report_raises_on_orphan_in_type(spark):
    dfs = _valid_dfs(spark)
    dfs["pokemon_type"] = _type_df(spark, VALID_TYPE_ROWS + [(999, "ghost")])

    with pytest.raises(quality.DataQualityError):
        quality.run_quality_report(dfs)


def test_run_quality_report_raises_on_orphan_in_stats(spark):
    dfs = _valid_dfs(spark)
    dfs["pokemon_stats"] = _stats_df(spark, VALID_STATS_ROWS + [(999, "hp", 1)])

    with pytest.raises(quality.DataQualityError):
        quality.run_quality_report(dfs)


def test_run_quality_report_raises_on_orphan_in_ability(spark):
    dfs = _valid_dfs(spark)
    dfs["pokemon_ability"] = _ability_df(
        spark, VALID_ABILITY_ROWS + [(999, "levitate", False)]
    )

    with pytest.raises(quality.DataQualityError):
        quality.run_quality_report(dfs)


def test_run_quality_report_does_not_raise_on_non_critical_duplicate(spark, capsys):
    """Duplicata em (pokemon_id, type_name) é reportada (FAIL) mas não é crítica: não levanta."""
    dfs = _valid_dfs(spark)
    dfs["pokemon_type"] = _type_df(spark, VALID_TYPE_ROWS + [(1, "grass")])

    quality.run_quality_report(dfs)  # não deve levantar

    captured = capsys.readouterr()
    assert "FAIL" in captured.out
