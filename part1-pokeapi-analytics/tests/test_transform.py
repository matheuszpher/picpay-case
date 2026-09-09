"""Testes de src/transform.py — SparkSession local, fixture pequena, nada de rede."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from src import transform

# Escrita de Parquet via Hadoop's FileOutputCommitter chama NativeIO no Windows e exige
# hadoop.dll (não só winutils.exe) em %HADOOP_HOME%\bin. No Docker/CI (Linux, ADR-0015) isso
# não é necessário — é só uma limitação do dev-box Windows local.
_hadoop_home = os.environ.get("HADOOP_HOME")
_has_hadoop_dll = (
    bool(_hadoop_home) and (Path(_hadoop_home) / "bin" / "hadoop.dll").exists()
)
_SKIP_WRITE_TESTS = sys.platform.startswith("win") and not _has_hadoop_dll
_SKIP_REASON = (
    "Escrita de Parquet requer hadoop.dll em %HADOOP_HOME%\\bin no Windows local; "
    "roda normalmente no Docker/CI (Linux) — ver ADR-0015."
)

# 3 pokémons: bulbasaur é multi-tipo e tem hidden ability; squirtle também tem hidden ability.
SAMPLE_DETAILS = [
    {
        "id": 1,
        "name": "bulbasaur",
        "height": 7,
        "weight": 69,
        "base_experience": 64,
        "types": [
            {"slot": 1, "type": {"name": "grass"}},
            {"slot": 2, "type": {"name": "poison"}},
        ],
        "stats": [
            {"base_stat": 45, "stat": {"name": "hp"}},
            {"base_stat": 49, "stat": {"name": "attack"}},
        ],
        "abilities": [
            {"ability": {"name": "overgrow"}, "is_hidden": False},
            {"ability": {"name": "chlorophyll"}, "is_hidden": True},
        ],
    },
    {
        "id": 4,
        "name": "charmander",
        "height": 6,
        "weight": 85,
        "base_experience": 62,
        "types": [
            {"slot": 1, "type": {"name": "fire"}},
        ],
        "stats": [
            {"base_stat": 39, "stat": {"name": "hp"}},
            {"base_stat": 52, "stat": {"name": "attack"}},
        ],
        "abilities": [
            {"ability": {"name": "blaze"}, "is_hidden": False},
        ],
    },
    {
        "id": 7,
        "name": "squirtle",
        "height": 5,
        "weight": 90,
        "base_experience": 63,
        "types": [
            {"slot": 1, "type": {"name": "water"}},
        ],
        "stats": [
            {"base_stat": 44, "stat": {"name": "hp"}},
        ],
        "abilities": [
            {"ability": {"name": "torrent"}, "is_hidden": False},
            {"ability": {"name": "rain-dish"}, "is_hidden": True},
        ],
    },
]


# ---------------------------------------------------------------------------
# build_pokemon
# ---------------------------------------------------------------------------


def test_build_pokemon_schema_is_explicit(spark):
    df = transform.build_pokemon(SAMPLE_DETAILS)

    expected_schema = StructType(
        [
            StructField("pokemon_id", IntegerType(), nullable=False),
            StructField("name", StringType(), nullable=False),
            StructField("height", IntegerType(), nullable=True),
            StructField("weight", IntegerType(), nullable=True),
            StructField("base_experience", IntegerType(), nullable=True),
        ]
    )
    assert df.schema == expected_schema


def test_build_pokemon_grain_is_one_row_per_pokemon(spark):
    df = transform.build_pokemon(SAMPLE_DETAILS)

    assert df.count() == 3
    rows = {row.pokemon_id: row.asDict() for row in df.collect()}
    assert rows[1]["name"] == "bulbasaur"
    assert rows[1]["height"] == 7
    assert rows[1]["weight"] == 69
    assert rows[1]["base_experience"] == 64
    assert set(rows.keys()) == {1, 4, 7}


# ---------------------------------------------------------------------------
# build_pokemon_type
# ---------------------------------------------------------------------------


def test_build_pokemon_type_schema_is_explicit(spark):
    df = transform.build_pokemon_type(SAMPLE_DETAILS)

    expected_schema = StructType(
        [
            StructField("pokemon_id", IntegerType(), nullable=False),
            StructField("type_name", StringType(), nullable=True),
        ]
    )
    assert df.schema == expected_schema


def test_build_pokemon_type_grain_is_one_row_per_pokemon_and_type(spark):
    df = transform.build_pokemon_type(SAMPLE_DETAILS)

    # bulbasaur (2 tipos) + charmander (1) + squirtle (1) = 4 linhas
    assert df.count() == 4

    bulbasaur_types = {row.type_name for row in df.filter(df.pokemon_id == 1).collect()}
    assert bulbasaur_types == {"grass", "poison"}

    charmander_types = {
        row.type_name for row in df.filter(df.pokemon_id == 4).collect()
    }
    assert charmander_types == {"fire"}


# ---------------------------------------------------------------------------
# build_pokemon_stats
# ---------------------------------------------------------------------------


def test_build_pokemon_stats_schema_is_explicit(spark):
    df = transform.build_pokemon_stats(SAMPLE_DETAILS)

    expected_schema = StructType(
        [
            StructField("pokemon_id", IntegerType(), nullable=False),
            StructField("stat_name", StringType(), nullable=True),
            StructField("base_stat", IntegerType(), nullable=True),
        ]
    )
    assert df.schema == expected_schema


def test_build_pokemon_stats_grain_is_one_row_per_pokemon_and_stat(spark):
    df = transform.build_pokemon_stats(SAMPLE_DETAILS)

    # bulbasaur (2) + charmander (2) + squirtle (1) = 5 linhas
    assert df.count() == 5

    bulbasaur_hp = df.filter((df.pokemon_id == 1) & (df.stat_name == "hp")).collect()
    assert len(bulbasaur_hp) == 1
    assert bulbasaur_hp[0].base_stat == 45


# ---------------------------------------------------------------------------
# build_pokemon_ability
# ---------------------------------------------------------------------------


def test_build_pokemon_ability_schema_is_explicit_with_real_boolean(spark):
    df = transform.build_pokemon_ability(SAMPLE_DETAILS)

    expected_schema = StructType(
        [
            StructField("pokemon_id", IntegerType(), nullable=False),
            StructField("ability_name", StringType(), nullable=True),
            StructField("is_hidden", BooleanType(), nullable=True),
        ]
    )
    assert df.schema == expected_schema
    assert isinstance(df.schema["is_hidden"].dataType, BooleanType)


def test_build_pokemon_ability_grain_and_hidden_flag(spark):
    df = transform.build_pokemon_ability(SAMPLE_DETAILS)

    # bulbasaur (2) + charmander (1) + squirtle (2) = 5 linhas
    assert df.count() == 5

    hidden = df.filter(df.is_hidden == True).collect()
    hidden_names = {row.ability_name for row in hidden}
    assert hidden_names == {"chlorophyll", "rain-dish"}

    not_hidden = df.filter(df.is_hidden == False).collect()
    not_hidden_names = {row.ability_name for row in not_hidden}
    assert not_hidden_names == {"overgrow", "blaze", "torrent"}


# ---------------------------------------------------------------------------
# write_silver
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SKIP_WRITE_TESTS, reason=_SKIP_REASON)
def test_write_silver_writes_parquet_and_roundtrips(spark, tmp_path):
    df = transform.build_pokemon(SAMPLE_DETAILS)

    transform.write_silver(df, "pokemon", base_path=tmp_path)

    output_dir = tmp_path / "silver" / "pokemon"
    assert output_dir.exists()
    assert any(p.suffix == ".parquet" for p in output_dir.iterdir())

    read_back = spark.read.parquet(str(output_dir))
    # nullable não sobrevive ao round-trip Parquet (o leitor do Spark marca tudo como
    # nullable=True); comparar nome + tipo é o que de fato importa aqui.
    assert [(f.name, f.dataType) for f in read_back.schema.fields] == [
        (f.name, f.dataType) for f in df.schema.fields
    ]
    assert sorted(row.pokemon_id for row in read_back.collect()) == [1, 4, 7]


@pytest.mark.skipif(_SKIP_WRITE_TESTS, reason=_SKIP_REASON)
def test_write_silver_overwrites_on_rerun(spark, tmp_path):
    df_full = transform.build_pokemon(SAMPLE_DETAILS)
    transform.write_silver(df_full, "pokemon", base_path=tmp_path)

    df_partial = transform.build_pokemon(SAMPLE_DETAILS[:1])
    transform.write_silver(df_partial, "pokemon", base_path=tmp_path)

    output_dir = tmp_path / "silver" / "pokemon"
    read_back = spark.read.parquet(str(output_dir))
    assert read_back.count() == 1
