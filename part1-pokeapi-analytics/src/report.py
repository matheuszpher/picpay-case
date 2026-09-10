"""Persistência dos resultados do notebook e geração do relatório gerencial em HTML.

Vive em src/, não no notebook: a mesma régua do resto do projeto, lógica testável
fica em src/ e o notebook só chama. As cores e a fonte do HTML seguem a identidade
visual pública do PicPay (verde de marca, tipografia sans-serif).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PICPAY_GREEN = "#21C25E"
PICPAY_DARK = "#0B3D2E"
PICPAY_FONT = "'Poppins', 'Segoe UI', Arial, sans-serif"


def build_results(
    *,
    generated_at: datetime,
    ingest_seconds: float,
    dataset_counts: dict[str, int],
    q1_resultado: int,
    q2_abilities: list[str],
    q3_top5: list[dict],
) -> dict:
    """Monta o dict de resultados persistido a cada execução do notebook."""
    return {
        "generated_at": generated_at.isoformat(),
        "ingest_seconds": round(ingest_seconds, 1),
        "dataset_counts": dataset_counts,
        "q1_multitype_above_avg": q1_resultado,
        "q2_abilities_exclusive_multitype": {
            "count": len(q2_abilities),
            "abilities": q2_abilities,
        },
        "q3_top5_versatility": q3_top5,
    }


def save_results_json(
    results: dict, path: str | Path = "data/results/latest.json"
) -> Path:
    """Grava os resultados em JSON. Sobrescreve o arquivo a cada execução."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return output_path


def build_html_report(results: dict) -> str:
    """Monta o relatório gerencial em HTML, com cores e fonte do PicPay."""
    counts = results["dataset_counts"]
    q2 = results["q2_abilities_exclusive_multitype"]

    top5_rows = "".join(
        f"<tr><td>{i}</td><td>{row['name']}</td><td>{row['pokemon_id']}</td>"
        f"<td>{row['versatility_score']:.2f}</td></tr>"
        for i, row in enumerate(results["q3_top5_versatility"], start=1)
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatorio PokeAPI Analytics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body {{ font-family: {PICPAY_FONT}; margin: 0; background: #F5F7F6; color: {PICPAY_DARK}; }}
  header {{ background: {PICPAY_GREEN}; color: #fff; padding: 32px 40px; }}
  header h1 {{ margin: 0; font-weight: 700; font-size: 28px; }}
  header p {{ margin: 4px 0 0; opacity: .9; }}
  main {{ padding: 32px 40px; max-width: 900px; margin: 0 auto; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 20px 24px;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); flex: 1; min-width: 160px; }}
  .card .value {{ font-size: 32px; font-weight: 700; color: {PICPAY_GREEN}; }}
  .card .label {{ font-size: 13px; color: #5b6b64; margin-top: 4px; }}
  section {{ background: #fff; border-radius: 12px; padding: 24px 28px; margin-bottom: 24px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  section h2 {{ margin-top: 0; font-size: 18px; color: {PICPAY_DARK};
               border-bottom: 2px solid {PICPAY_GREEN}; padding-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #E5E9E7; font-size: 14px; }}
  th {{ color: #5b6b64; font-weight: 600; }}
  footer {{ text-align: center; padding: 24px; color: #8a9691; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>PicPay ML Case: PokeAPI Analytics</h1>
  <p>Relatorio gerencial gerado em {results["generated_at"]}</p>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="value">{counts.get("pokemon", 0)}</div><div class="label">pokemons (silver)</div></div>
    <div class="card"><div class="value">{results["q1_multitype_above_avg"]}</div><div class="label">multi-tipo acima da media (Q1)</div></div>
    <div class="card"><div class="value">{q2["count"]}</div><div class="label">abilities exclusivas (Q2)</div></div>
    <div class="card"><div class="value">{results["ingest_seconds"]:.1f}s</div><div class="label">tempo de ingestao</div></div>
  </div>

  <section>
    <h2>Q1. Multi-tipo e forca acima da media</h2>
    <p><strong>{results["q1_multitype_above_avg"]}</strong> pokemons sao multi-tipo e tem forca
    acima da media (media das forcas por pokemon, nao media linha a linha de base_stat).</p>
  </section>

  <section>
    <h2>Q2. Abilities exclusivas de multi-tipo</h2>
    <p><strong>{q2["count"]}</strong> abilities nunca aparecem em pokemon de tipo unico.</p>
  </section>

  <section>
    <h2>Q3. Top 5 versatilidade</h2>
    <table>
      <thead><tr><th>#</th><th>Pokemon</th><th>ID</th><th>Score</th></tr></thead>
      <tbody>{top5_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Dataset (silver)</h2>
    <table>
      <thead><tr><th>Tabela</th><th>Linhas</th></tr></thead>
      <tbody>
        <tr><td>pokemon</td><td>{counts.get("pokemon", 0)}</td></tr>
        <tr><td>pokemon_type</td><td>{counts.get("pokemon_type", 0)}</td></tr>
        <tr><td>pokemon_stats</td><td>{counts.get("pokemon_stats", 0)}</td></tr>
        <tr><td>pokemon_ability</td><td>{counts.get("pokemon_ability", 0)}</td></tr>
      </tbody>
    </table>
  </section>
</main>
<footer>PicPay ML Case - Parte 1 (PokeAPI Analytics) - gerado automaticamente pelo notebook.ipynb</footer>
</body>
</html>
"""


def save_html_report(
    html: str,
    generated_at: datetime,
    reports_dir: str | Path = "data/reports",
) -> tuple[Path, Path]:
    """Salva o relatório HTML em dois arquivos.

    Um com nome fixo (`report-apipokemon-latest.html`), sobrescrito a cada
    execução, e outro com nome único por execução
    (`report-apipokemon-{DDMMYY}-{HHMMSS}.html`), preservando o histórico de
    execuções anteriores. Retorna `(latest_path, timestamped_path)`.
    """
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    latest_path = reports_path / "report-apipokemon-latest.html"
    latest_path.write_text(html, encoding="utf-8")

    timestamped_name = (
        f"report-apipokemon-{generated_at:%d%m%y}-{generated_at:%H%M%S}.html"
    )
    timestamped_path = reports_path / timestamped_name
    timestamped_path.write_text(html, encoding="utf-8")

    return latest_path, timestamped_path
