"""Checks de qualidade do silver: not-null, unicidade, integridade referencial.

Fail loud: `run_quality_report` imprime um relatório legível e levanta `DataQualityError`
se uma invariante crítica for violada (PK nula/duplicada em `pokemon`, ou órfãos em
`pokemon_type`/`pokemon_stats`/`pokemon_ability`). Não é só log: quebra o pipeline.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


class DataQualityError(Exception):
    """Levantado quando uma invariante crítica de qualidade de dados é violada."""


def check_not_null(df: DataFrame, cols: list[str]) -> dict:
    """Conta nulos em cada coluna de `cols`; passa se todas estiverem 100% preenchidas."""
    null_counts = {col: df.filter(F.col(col).isNull()).count() for col in cols}
    passed = all(count == 0 for count in null_counts.values())
    details = ", ".join(f"{col}={count} nulos" for col, count in null_counts.items())
    return {
        "check": f"not_null({', '.join(cols)})",
        "passed": passed,
        "details": details,
    }


def check_unique(df: DataFrame, cols: list[str]) -> dict:
    """Verifica se `cols` (combinados) formam chave única: zero grupos com contagem > 1."""
    duplicate_count = df.groupBy(*cols).count().filter(F.col("count") > 1).count()
    passed = duplicate_count == 0
    return {
        "check": f"unique({', '.join(cols)})",
        "passed": passed,
        "details": f"{duplicate_count} chave(s) duplicada(s)",
    }


def check_referential(
    child: DataFrame, parent: DataFrame, key: str = "pokemon_id"
) -> dict:
    """Zero órfãos: toda chave `key` em `child` deve existir em `parent`."""
    orphan_count = child.join(
        parent.select(key).distinct(), on=key, how="left_anti"
    ).count()
    passed = orphan_count == 0
    return {
        "check": f"referential({key})",
        "passed": passed,
        "details": f"{orphan_count} órfão(s)",
    }


def run_quality_report(dfs: dict[str, DataFrame]) -> None:
    """Roda os checks do silver, imprime o relatório e falha em invariante crítica.

    Espera `dfs` com as chaves: pokemon, pokemon_type, pokemon_stats, pokemon_ability.
    Críticos: PK nula/duplicada em `pokemon`; órfãos em type/stats/ability -> pokemon.
    """
    pokemon = dfs["pokemon"]
    pokemon_type = dfs["pokemon_type"]
    pokemon_stats = dfs["pokemon_stats"]
    pokemon_ability = dfs["pokemon_ability"]

    checks = [
        (check_not_null(pokemon, ["pokemon_id"]), True),
        (check_unique(pokemon, ["pokemon_id"]), True),
        (check_unique(pokemon_type, ["pokemon_id", "type_name"]), False),
        (check_referential(pokemon_type, pokemon), True),
        (check_referential(pokemon_stats, pokemon), True),
        (check_referential(pokemon_ability, pokemon), True),
    ]

    _print_report(checks)

    failed_critical = [
        result for result, critical in checks if critical and not result["passed"]
    ]
    if failed_critical:
        summary = "; ".join(f"{r['check']}: {r['details']}" for r in failed_critical)
        raise DataQualityError(f"Invariante(s) crítica(s) violada(s): {summary}")


def _print_report(checks: list[tuple[dict, bool]]) -> None:
    print("=" * 70)
    print("RELATÓRIO DE QUALIDADE - silver")
    print("=" * 70)
    for result, critical in checks:
        status = "PASS" if result["passed"] else "FAIL"
        flag = " [CRÍTICO]" if critical else ""
        print(f"[{status}]{flag} {result['check']}: {result['details']}")
    print("=" * 70)
