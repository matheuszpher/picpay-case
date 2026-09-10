"""Bronze -> silver: as 4 tabelas do dicionário, com StructType explícito (ADR-0007).

Nada de inferSchema: o schema do JSON cru (`RAW_DETAIL_SCHEMA`) é declarado à mão e usado em
`spark.createDataFrame`. As 4 tabelas nascem de select/explode sobre esse DataFrame tipado.
"""

from __future__ import annotations

import os
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

RAW_DETAIL_SCHEMA = StructType(
    [
        StructField("id", IntegerType(), nullable=False),
        StructField("name", StringType(), nullable=False),
        StructField("height", IntegerType(), nullable=True),
        StructField("weight", IntegerType(), nullable=True),
        StructField("base_experience", IntegerType(), nullable=True),
        StructField(
            "types",
            ArrayType(
                StructType(
                    [
                        StructField("slot", IntegerType(), nullable=True),
                        StructField(
                            "type",
                            StructType(
                                [StructField("name", StringType(), nullable=True)]
                            ),
                            nullable=True,
                        ),
                    ]
                )
            ),
            nullable=True,
        ),
        StructField(
            "stats",
            ArrayType(
                StructType(
                    [
                        StructField("base_stat", IntegerType(), nullable=True),
                        StructField(
                            "stat",
                            StructType(
                                [StructField("name", StringType(), nullable=True)]
                            ),
                            nullable=True,
                        ),
                    ]
                )
            ),
            nullable=True,
        ),
        StructField(
            "abilities",
            ArrayType(
                StructType(
                    [
                        StructField(
                            "ability",
                            StructType(
                                [StructField("name", StringType(), nullable=True)]
                            ),
                            nullable=True,
                        ),
                        StructField("is_hidden", BooleanType(), nullable=True),
                    ]
                )
            ),
            nullable=True,
        ),
    ]
)


def _get_spark() -> SparkSession:
    return (
        SparkSession.builder.appName("part1-pokeapi-transform")
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .getOrCreate()
    )


def _details_to_df(details: list[dict]) -> DataFrame:
    return _get_spark().createDataFrame(details, schema=RAW_DETAIL_SCHEMA)


def build_pokemon(details: list[dict]) -> DataFrame:
    """DF[pokemon_id:int, name:str, height:int, weight:int, base_experience:int]."""
    df = _details_to_df(details)
    return df.select(
        F.col("id").alias("pokemon_id"),
        F.col("name"),
        F.col("height"),
        F.col("weight"),
        F.col("base_experience"),
    )


def build_pokemon_type(details: list[dict]) -> DataFrame:
    """DF[pokemon_id:int, type_name:str]: explode de `types`, 1 linha por (pokémon, tipo)."""
    df = _details_to_df(details)
    return df.select(
        F.col("id").alias("pokemon_id"), F.explode("types").alias("type_entry")
    ).select(
        "pokemon_id",
        F.col("type_entry.type.name").alias("type_name"),
    )


def build_pokemon_stats(details: list[dict]) -> DataFrame:
    """DF[pokemon_id:int, stat_name:str, base_stat:int]: explode de `stats`."""
    df = _details_to_df(details)
    return df.select(
        F.col("id").alias("pokemon_id"), F.explode("stats").alias("stat_entry")
    ).select(
        "pokemon_id",
        F.col("stat_entry.stat.name").alias("stat_name"),
        F.col("stat_entry.base_stat").alias("base_stat"),
    )


def build_pokemon_ability(details: list[dict]) -> DataFrame:
    """DF[pokemon_id:int, ability_name:str, is_hidden:bool]: explode de `abilities`."""
    df = _details_to_df(details)
    return df.select(
        F.col("id").alias("pokemon_id"), F.explode("abilities").alias("ability_entry")
    ).select(
        "pokemon_id",
        F.col("ability_entry.ability.name").alias("ability_name"),
        F.col("ability_entry.is_hidden").alias("is_hidden"),
    )


def write_silver(df: DataFrame, name: str, base_path: str | Path = "data") -> None:
    """Escreve Parquet em {base_path}/silver/{name} (overwrite: reprocessável)."""
    output_path = Path(base_path) / "silver" / name
    df.write.mode("overwrite").parquet(str(output_path))
