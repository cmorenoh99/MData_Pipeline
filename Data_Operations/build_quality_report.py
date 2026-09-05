"""
Genera un resumen HTML del estado de calidad de todas las fuentes
procesadas en la ejecucion actual del pipeline.

Ubicacion esperada en el repositorio:
    Data_Operations/build_quality_report.py

Se ejecuta desde el stage 'Evaluacion de calidad' del Jenkinsfile. Lee los
informes de audit_reports/ generados DURANTE este build (los posteriores al
fichero marcador .build_marker) y produce un HTML listo para el correo.

Uso:
    python -m Data_Operations.build_quality_report \
        --marker .build_marker \
        --output build_quality_report.html

Salida por stdout (consumida por el Jenkinsfile):
    BUILD_STATUS=FAILURE|ABORTED|SUCCESS
    FAILED_SOURCES=asana_sales_task,sheets_employees
    FAILED_STAGES=Sales,Google Sheets
"""

import argparse
import glob
import html
import json
import os
import sys

REPORTS_DIR = "audit_reports"

# Correspondencia entre el nombre de la fuente y el stage del Jenkinsfile.
# Permite que el correo indique en que stage se produjo cada incidencia.
STAGE_BY_SOURCE = {
    "asana_sales_task": "Sales",
    "asana_operations_task": "Operations",
    "sheets_employees": "Google Sheets",
}

# Estados que se consideran problematicos
PROBLEM_STATES = {"FAIL", "ABORTED", "PARTIAL", "ERROR"}

STATE_COLORS = {
    "PASS": "#28a745",
    "PARTIAL": "#f0ad4e",
    "ABORTED": "#f0ad4e",
    "FAIL": "#dc3545",
    "ERROR": "#dc3545",
}

TABLE_STYLE = (
    'border="1" cellpadding="6" cellspacing="0" '
    'style="border-collapse:collapse;width:100%;font-size:14px;"'
)


def esc(value):
    """Escapa cualquier valor para insertarlo en HTML."""
    return html.escape(str(value))


def stage_for(source):
    return STAGE_BY_SOURCE.get(source, "No identificado")


def load_reports_since(marker_path):
    """
    Devuelve el informe mas reciente de cada fuente, considerando
    unicamente los ficheros creados despues del marcador de inicio de
    build. Evita arrastrar informes de ejecuciones anteriores.
    """
    if os.path.exists(marker_path):
        cutoff = os.path.getmtime(marker_path)
    else:
        print("AVISO: no se encontro el fichero marcador; no se filtra por build.",
              file=sys.stderr)
        cutoff = 0

    latest_by_source = {}

    for path in glob.glob(os.path.join(REPORTS_DIR, "*.json")):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        if mtime < cutoff:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"AVISO: no se pudo leer {path}: {exc}", file=sys.stderr)
            continue

        source = report.get("source", "desconocida")
        current = latest_by_source.get(source)

        if current is None or mtime > current["_mtime"]:
            report["_mtime"] = mtime
            report["_file"] = os.path.basename(path)
            latest_by_source[source] = report

    return latest_by_source


def failed_validations(report):
    """Validaciones que no pasaron. Se ignoran NOT_APPLICABLE e INSUFFICIENT_HISTORY."""
    return [
        v.get("validation", "desconocida")
        for v in report.get("validations", [])
        if v.get("status") in {"FAIL", "ERROR"}
    ]


def get_impact(report):
    """Normaliza el bloque de impact_analysis, que puede ser dict o lista."""
    impact = report.get("impact_analysis")
    if isinstance(impact, list):
        impact = impact[0] if impact else None
    return impact if isinstance(impact, dict) else None


def assets_of(report):
    impact = get_impact(report)
    if not impact:
        return []
    return impact.get("downstream_assets") or []


def assets_summary(report):
    """Texto corto con los activos afectados, para la tabla resumen."""
    assets = assets_of(report)
    if not assets:
        return "Ninguno identificado"
    return ", ".join(str(a.get("name", "sin nombre")) for a in assets)


# -------------------------------------------------------------------
# Render
# -------------------------------------------------------------------

def render_summary_table(reports):
    """Tabla de una fila por fuente: es lo primero que se ve en el correo."""
    rows = []

    for report in reports:
        source = report.get("source", "desconocida")
        status = str(report.get("overall_status", "No disponible"))
        color = STATE_COLORS.get(status, "#6c757d")
        failures = failed_validations(report)

        rows.append(f"""
        <tr>
            <td><b>{esc(source)}</b></td>
            <td>{esc(stage_for(source))}</td>
            <td style="color:{color};"><b>{esc(status)}</b></td>
            <td align="right">{esc(report.get("health_score", "n/d"))}</td>
            <td>{esc(", ".join(failures) if failures else "Ninguna")}</td>
            <td>{esc(assets_summary(report))}</td>
        </tr>
        """)

    return f"""
    <table {TABLE_STYLE}>
        <tr style="background:#f1f3f5;">
            <th align="left">Fuente</th>
            <th align="left">Stage</th>
            <th align="left">Estado</th>
            <th align="right">Health Score</th>
            <th align="left">Validaciones fallidas</th>
            <th align="left">Activos afectados</th>
        </tr>
        {"".join(rows)}
    </table>
    """


def render_impact(report):
    """Detalle del Impact Analysis de una fuente."""
    impact = get_impact(report)

    if not impact:
        return ('<p style="color:#6c757d;">Sin informacion de Impact Analysis '
                'para esta fuente.</p>')

    assets = assets_of(report)

    if assets:
        items = "".join(
            "<li><b>{}</b> ({}) &mdash; responsable: {}</li>".format(
                esc(a.get("name", "No disponible")),
                esc(a.get("type", "No disponible")),
                esc(a.get("owner", "No disponible")),
            )
            for a in assets
        )
        assets_html = f"<ul style='margin-top:4px;'>{items}</ul>"
    else:
        assets_html = "<p>No se identificaron activos analiticos dependientes.</p>"

    return f"""
    <table {TABLE_STYLE}>
        <tr><td width="35%"><b>Dataset afectado</b></td>
            <td>{esc(impact.get("dataset", "No disponible"))}</td></tr>
        <tr><td><b>Incidencia</b></td>
            <td>{esc(impact.get("issue", "No disponible"))}</td></tr>
        <tr><td><b>Impact status</b></td>
            <td><b>{esc(impact.get("impact_status", "No disponible"))}</b></td></tr>
        <tr><td><b>Linaje disponible</b></td>
            <td>{esc(impact.get("lineage_available", "No disponible"))}</td></tr>
        <tr><td><b>Nodos del grafo</b></td>
            <td>{esc(impact.get("lineage_nodes", "No disponible"))}</td></tr>
    </table>
    <p style="margin:8px 0 2px 0;"><b>Activos analiticos potencialmente afectados</b></p>
    {assets_html}
    """


def render_source_detail(report):
    """Bloque completo de una fuente con incidencias."""
    source = report.get("source", "desconocida")
    status = str(report.get("overall_status", "No disponible"))
    color = STATE_COLORS.get(status, "#6c757d")
    failures = failed_validations(report)

    return f"""
    <h3 style="margin:18px 0 6px 0;border-left:4px solid {color};padding-left:8px;">
        {esc(source)}
        <span style="font-weight:normal;font-size:14px;color:#6c757d;">
            &nbsp;|&nbsp; stage {esc(stage_for(source))}
        </span>
    </h3>

    <table {TABLE_STYLE}>
        <tr><td width="35%"><b>Stage del pipeline</b></td>
            <td>{esc(stage_for(source))}</td></tr>
        <tr><td><b>Execution ID</b></td>
            <td><code>{esc(report.get("execution_id", "No disponible"))}</code></td></tr>
        <tr><td><b>Estado de ejecucion</b></td>
            <td style="color:{color};"><b>{esc(status)}</b></td></tr>
        <tr><td><b>Health Score</b></td>
            <td><b>{esc(report.get("health_score", "No disponible"))}</b></td></tr>
        <tr><td><b>Validaciones fallidas</b></td>
            <td>{esc(", ".join(failures) if failures else "Ninguna")}</td></tr>
        <tr><td><b>Registros recibidos</b></td>
            <td>{esc(report.get("record_count",
                                report.get("records_received", "No disponible")))}</td></tr>
        <tr><td><b>Registros cargados</b></td>
            <td>{esc(report.get("records_loaded", "No disponible"))}</td></tr>
        <tr><td><b>Registros rechazados</b></td>
            <td>{esc(report.get("records_rejected", "No disponible"))}</td></tr>
        <tr><td><b>Informe de auditoria</b></td>
            <td><code>{esc(report.get("_file", "No disponible"))}</code></td></tr>
    </table>

    <p style="margin:10px 0 2px 0;"><b>Impact Analysis</b></p>
    {render_impact(report)}
    """


# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", default=".build_marker")
    parser.add_argument("--output", default="build_quality_report.html")
    args = parser.parse_args()

    reports_map = load_reports_since(args.marker)

    if not reports_map:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("<p>No se encontraron informes de auditoria para esta ejecucion.</p>")
        print("BUILD_STATUS=SUCCESS")
        print("FAILED_SOURCES=")
        print("FAILED_STAGES=")
        return

    # Primero las fuentes con incidencias, despues las correctas
    ordered = sorted(
        reports_map.values(),
        key=lambda r: (r.get("overall_status") == "PASS", r.get("source", "")),
    )

    problem_reports = [
        r for r in ordered if r.get("overall_status") in PROBLEM_STATES
    ]
    problem_sources = [r.get("source", "desconocida") for r in problem_reports]
    problem_stages = [stage_for(s) for s in problem_sources]

    if problem_reports:
        cabecera = (
            f"<p>Se detectaron incidencias de calidad en <b>{len(problem_reports)}</b> "
            f"de <b>{len(ordered)}</b> fuentes procesadas.</p>"
            f"<p><b>Fuentes afectadas:</b> {esc(', '.join(problem_sources))}<br>"
            f"<b>Stages afectados:</b> {esc(', '.join(problem_stages))}</p>"
        )
    else:
        cabecera = (
            f"<p>Las <b>{len(ordered)}</b> fuentes procesadas superaron "
            "todas las validaciones.</p>"
        )

    partes = [
        cabecera,
        "<h2 style='margin:16px 0 6px 0;'>Resumen por fuente</h2>",
        render_summary_table(ordered),
    ]

    if problem_reports:
        partes.append("<h2 style='margin:20px 0 0 0;'>Detalle de las incidencias</h2>")
        partes.extend(render_source_detail(r) for r in problem_reports)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))

    estados = {r.get("overall_status") for r in ordered}

    if "FAIL" in estados or "ERROR" in estados:
        build_status = "FAILURE"
    elif "ABORTED" in estados:
        build_status = "ABORTED"
    else:
        build_status = "SUCCESS"

    print(f"BUILD_STATUS={build_status}")
    print(f"FAILED_SOURCES={','.join(problem_sources)}")
    print(f"FAILED_STAGES={','.join(problem_stages)}")


if __name__ == "__main__":
    main()
