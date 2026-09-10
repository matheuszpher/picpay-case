"""Testes de src/report.py: persistência dos resultados e geração do HTML gerencial.

Nada de Spark aqui, o módulo só monta dict/HTML e escreve arquivo.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime

from src import report

SAMPLE_RESULTS_KWARGS = {
    "generated_at": datetime(2026, 8, 11, 11, 3, 20),
    "ingest_seconds": 36.5,
    "dataset_counts": {
        "pokemon": 1351,
        "pokemon_type": 2116,
        "pokemon_stats": 8106,
        "pokemon_ability": 2941,
    },
    "q1_resultado": 510,
    "q2_abilities": ["overgrow", "keen-eye"],
    "q3_top5": [
        {
            "pokemon_id": 10190,
            "name": "eternatus-eternamax",
            "versatility_score": 16.25,
        },
        {"pokemon_id": 784, "name": "kommo-o", "versatility_score": 13.0},
    ],
    "forca_values": [94, 122, 91, 92, 85, 92, 700, 68, 310, 455],
}


# ---------------------------------------------------------------------------
# build_results
# ---------------------------------------------------------------------------


def test_build_results_shape():
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)

    assert results["q1_multitype_above_avg"] == 510
    assert results["q2_abilities_exclusive_multitype"]["count"] == 2
    assert results["q2_abilities_exclusive_multitype"]["abilities"] == [
        "overgrow",
        "keen-eye",
    ]
    assert results["dataset_counts"]["pokemon"] == 1351
    assert results["ingest_seconds"] == 36.5
    assert results["generated_at"] == "2026-08-11T11:03:20"


# ---------------------------------------------------------------------------
# save_results_json
# ---------------------------------------------------------------------------


def test_save_results_json_writes_file(tmp_path):
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)
    path = tmp_path / "results" / "latest.json"

    output_path = report.save_results_json(results, path=path)

    assert output_path == path
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["q1_multitype_above_avg"] == 510


def test_save_results_json_overwrites_on_rerun(tmp_path):
    path = tmp_path / "results" / "latest.json"

    first = report.build_results(**SAMPLE_RESULTS_KWARGS)
    report.save_results_json(first, path=path)

    second_kwargs = dict(SAMPLE_RESULTS_KWARGS)
    second_kwargs["q1_resultado"] = 999
    second = report.build_results(**second_kwargs)
    report.save_results_json(second, path=path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["q1_multitype_above_avg"] == 999  # não sobrou nada da 1a execução


# ---------------------------------------------------------------------------
# build_html_report
# ---------------------------------------------------------------------------


def test_build_html_report_contains_key_numbers_and_picpay_colors():
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)

    html = report.build_html_report(results)

    assert "510" in html
    assert "eternatus-eternamax" in html
    assert "kommo-o" in html
    assert report.PICPAY_GREEN in html
    assert "Poppins" in html


def test_build_html_report_is_valid_enough_html():
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)

    html = report.build_html_report(results)

    assert html.strip().startswith("<!doctype html>")
    assert "<html" in html and "</html>" in html


def test_build_html_report_embeds_logo_and_two_charts_as_base64_png():
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)

    html = report.build_html_report(results)

    # 1 logo + 2 graficos = 3 imagens embutidas, nenhuma referenciada por caminho externo
    assert html.count("data:image/png;base64,") == 3
    assert 'src="http' not in html  # nenhuma imagem carregada de fora


# ---------------------------------------------------------------------------
# build_top5_chart / build_forca_distribution_chart: nada estatico ou chumbado,
# o grafico tem que refletir os dados recebidos.
# ---------------------------------------------------------------------------


def test_build_top5_chart_returns_base64_png():
    chart_b64 = report.build_top5_chart(SAMPLE_RESULTS_KWARGS["q3_top5"])

    assert isinstance(chart_b64, str)
    assert len(chart_b64) > 500  # um PNG de verdade, nao uma string vazia/trivial
    # cabecalho de um PNG valido, uma vez decodificado
    assert base64.b64decode(chart_b64)[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_top5_chart_changes_when_data_changes():
    chart_a = report.build_top5_chart(SAMPLE_RESULTS_KWARGS["q3_top5"])

    different_top5 = [
        {"pokemon_id": 1, "name": "bulbasaur", "versatility_score": 1.0},
        {"pokemon_id": 2, "name": "ivysaur", "versatility_score": 2.0},
    ]
    chart_b = report.build_top5_chart(different_top5)

    assert chart_a != chart_b  # nao e uma imagem chumbada: muda com o dado


def test_build_forca_distribution_chart_returns_base64_png():
    chart_b64 = report.build_forca_distribution_chart(
        SAMPLE_RESULTS_KWARGS["forca_values"]
    )

    assert base64.b64decode(chart_b64)[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_forca_distribution_chart_changes_when_data_changes():
    chart_a = report.build_forca_distribution_chart([100, 200, 300, 400, 500])
    chart_b = report.build_forca_distribution_chart([10, 20, 30, 40, 50, 900, 900])

    assert chart_a != chart_b


def test_logo_asset_exists_and_is_a_real_png():
    assert report.LOGO_PATH.exists()

    header = report.LOGO_PATH.read_bytes()[:8]
    assert header == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# save_html_report
# ---------------------------------------------------------------------------


def test_save_html_report_creates_latest_and_timestamped_files(tmp_path):
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)
    html = report.build_html_report(results)

    latest_path, timestamped_path = report.save_html_report(
        html,
        generated_at=datetime(2026, 8, 11, 11, 3, 20),
        reports_dir=tmp_path,
    )

    assert latest_path.name == "report-apipokemon-latest.html"
    assert latest_path.exists()
    assert timestamped_path.name == "report-apipokemon-110826-110320.html"
    assert timestamped_path.exists()
    assert latest_path.read_text(encoding="utf-8") == timestamped_path.read_text(
        encoding="utf-8"
    )


def test_save_html_report_timestamped_name_matches_pattern(tmp_path):
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)
    html = report.build_html_report(results)

    _, timestamped_path = report.save_html_report(
        html, generated_at=datetime.now(), reports_dir=tmp_path
    )

    assert re.match(r"report-apipokemon-\d{6}-\d{6}\.html$", timestamped_path.name)


def test_save_html_report_overwrites_latest_but_keeps_previous_timestamped(tmp_path):
    results = report.build_results(**SAMPLE_RESULTS_KWARGS)

    html_v1 = report.build_html_report(results)
    latest_1, timestamped_1 = report.save_html_report(
        html_v1,
        generated_at=datetime(2026, 8, 11, 11, 3, 20),
        reports_dir=tmp_path,
    )

    results_v2 = dict(SAMPLE_RESULTS_KWARGS)
    results_v2["q1_resultado"] = 999
    html_v2 = report.build_html_report(report.build_results(**results_v2))
    latest_2, timestamped_2 = report.save_html_report(
        html_v2,
        generated_at=datetime(2026, 8, 11, 11, 5, 0),
        reports_dir=tmp_path,
    )

    # "latest" é o mesmo arquivo, sobrescrito com o conteúdo da 2a execução
    assert latest_1 == latest_2
    assert "999" in latest_2.read_text(encoding="utf-8")

    # o timestamped da 1a execução continua existindo e não foi tocado
    assert timestamped_1.exists()
    assert timestamped_1 != timestamped_2
    assert "510" in timestamped_1.read_text(encoding="utf-8")
