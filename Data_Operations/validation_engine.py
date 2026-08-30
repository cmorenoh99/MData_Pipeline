"""
Data_Operations/validation_engine.py

Motor central de validaciones del framework de observabilidad e integridad
de datos, e integracion con la logica de decision de carga.

Objetivo Especifico 2 (run_validation): ejecuta las 5 categorias de
validacion y genera el reporte de auditoria + Data Health Score.

Objetivo Especifico 3 (process_and_load): usa esos resultados para
decidir el enrutamiento de cada registro (produccion via UPSERT, o
tabla de errores) e integra con la clase SQLDatabaseConection existente.

TFM - Framework de observabilidad y validacion de integridad de datos
Autor: Camila Moreno Higuita
"""

import os
import json
import uuid
import time
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text as sa_text

from Utils.contract_loader import load_contract


def create_execution(warehouse, source_name: str, record_count: int) -> str:

    execution_id = str(uuid.uuid4())

    query = sa_text("""
        INSERT INTO data_quality_execution (
            execution_id,
            source_name,
            execution_timestamp,
            record_count,
            overall_status
        )
        VALUES (
            :execution_id,
            :source_name,
            NOW(),
            :record_count,
            :overall_status
        )
    """)

    with warehouse.engine.begin() as conn:
        conn.execute(
            query,
            {
                "execution_id": execution_id,
                "source_name": source_name,
                "record_count": record_count,
                "overall_status": "RUNNING"
            }
        )

    return execution_id


def update_execution( warehouse, execution_id: str, health_score: float,  overall_status: str, records_loaded: int = 0, records_rejected: int = 0, duration_seconds: float = None) -> None:

    query = sa_text("""
        UPDATE data_quality_execution
        SET
            health_score = :health_score,
            overall_status = :overall_status,
            records_loaded = :records_loaded,
            records_rejected = :records_rejected,
            duration_seconds = :duration_seconds
        WHERE execution_id = :execution_id
    """)

    with warehouse.engine.begin() as conn:
        conn.execute(
            query,
            {
                "execution_id": execution_id,
                "health_score": health_score,
                "overall_status": overall_status,
                "records_loaded": records_loaded,
                "records_rejected": records_rejected,
                "duration_seconds": duration_seconds
            }
        )

def mark_execution_error(
    warehouse,
    execution_id: str,
    error_message: str,
    duration_seconds: float
) -> None:

    query = sa_text("""
        UPDATE data_quality_execution
        SET
            overall_status = 'ERROR',
            duration_seconds = :duration_seconds
        WHERE execution_id = :execution_id
    """)

    with warehouse.engine.begin() as conn:
        conn.execute(
            query,
            {
                "execution_id": execution_id,
                "duration_seconds": duration_seconds
            }
        )

    print(
        f"[ERROR] Ejecución {execution_id} falló: "
        f"{error_message}"
    )

def save_validation_results( warehouse,  execution_id: str, results: list) -> None:

    query = sa_text("""
        INSERT INTO data_quality_validation (
            execution_id,
            validation_name,
            status,
            score,
            failed_records,
            details
        )
        VALUES (
            :execution_id,
            :validation_name,
            :status,
            :score,
            :failed_records,
            CAST(:details AS JSONB)
        )
    """)

    with warehouse.engine.begin() as conn:

        for result in results:

            status = result.get("status")

            if status == "PASS":
                score = 100

            elif status == "FAIL":
                score = 0

            else:
                score = None

            failed_records = (
                result.get("invalid_records")
                or result.get("duplicates_found")
                or 0
            )

            details = json.dumps(result, default=str)

            conn.execute(
                query,
                {
                    "execution_id": execution_id,
                    "validation_name": result.get("validation"),
                    "status": status,
                    "score": score,
                    "failed_records": failed_records,
                    "details": details
                }
            )

def save_error_results(warehouse, execution_id: str, source_name: str, df_invalid: pd.DataFrame, contract: dict ) -> None:

    if df_invalid.empty:
        return

    id_field = contract["identifier"]["field"]

    query = sa_text("""
        INSERT INTO data_quality_error (
            execution_id,
            source_name,
            record_id,
            validation_name,
            error_type,
            error_detail,
            detected_at
        )
        VALUES (
            :execution_id,
            :source_name,
            :record_id,
            :validation_name,
            :error_type,
            :error_detail,
            NOW()
        )
    """)

    rows = []

    for _, row in df_invalid.iterrows():

        record_id = row.get(id_field)

        reasons = str(
            row.get("_validation_reasons", "")
        )

        for reason in reasons.split(","):

            reason = reason.strip()

            if not reason:
                continue

            if reason.startswith("null_critical_field:"):

                validation_name = "completeness"
                error_type = "NULL_CRITICAL_FIELD"
                error_detail = reason.replace(
                    "null_critical_field:",
                    ""
                )

            elif reason == "duplicate_gid":

                validation_name = "uniqueness"
                error_type = "DUPLICATE_IDENTIFIER"
                error_detail = id_field

            elif reason == "project_mismatch":

                validation_name = "project_integrity"
                error_type = "PROJECT_MISMATCH"
                error_detail = "project_id"

            elif reason == "volumetry_anomaly":

                validation_name = "volumetry"
                error_type = "VOLUMETRY_ANOMALY"
                error_detail = "batch_volume"

            else:

                validation_name = "unknown"
                error_type = "VALIDATION_ERROR"
                error_detail = reason

            rows.append(
                {
                    "execution_id": execution_id,
                    "source_name": source_name,
                    "record_id": str(record_id)
                    if pd.notna(record_id)
                    else None,
                    "validation_name": validation_name,
                    "error_type": error_type,
                    "error_detail": error_detail
                }
            )

    if not rows:
        return

    with warehouse.engine.begin() as conn:

        for row in rows:

            conn.execute(
                query,
                row
            )

def save_volume_history(warehouse, execution_id: str, source_name: str, result: dict) -> None:

    query = sa_text("""
        INSERT INTO data_quality_volume_history (
            source_name,
            execution_id,
            execution_date,
            record_count,
            historical_mean,
            historical_std,
            z_score,
            threshold,
            status,
            created_at
        )
        VALUES (
            :source_name,
            :execution_id,
            NOW(),
            :record_count,
            :historical_mean,
            :historical_std,
            :z_score,
            :threshold,
            :status,
            NOW()
        )
    """)

    with warehouse.engine.begin() as conn:

        conn.execute(
            query,
            {
                "source_name": source_name,
                "execution_id": execution_id,
                "record_count": result.get(
                    "current_count"
                ),
                "historical_mean": (
                    float(result["historical_mean"])
                    if result.get("historical_mean") is not None
                    else None
                ),
                "historical_std": (
                    float(result["historical_std"])
                    if result.get("historical_std") is not None
                    else None
                ),
                "z_score": (
                    float(result["z_score"])
                    if result.get("z_score") is not None
                    else None
                ),
                "threshold": (
                    float(result["threshold"])
                    if result.get("threshold") is not None
                    else None
                ),
                "status": result.get(
                    "status"
                )
            }
        )
# ---------------------------------------------------------------------
# 1. UNICIDAD
# ---------------------------------------------------------------------
def check_uniqueness(df: pd.DataFrame, contract: dict) -> dict:
    id_field = contract["identifier"]["field"]
    total = len(df)
    unique = df[id_field].nunique()
    passed = total == unique

    return {
        "validation": "uniqueness",
        "status": "PASS" if passed else "FAIL",
        "total_records": total,
        "unique_records": int(unique),
        "duplicates_found": int(total - unique),
    }


# ---------------------------------------------------------------------
# 2. COMPLETITUD
# ---------------------------------------------------------------------
def check_completeness(df: pd.DataFrame, contract: dict) -> dict:
    threshold = contract["completeness"]["threshold_percent"]
    critical_fields = contract["completeness"]["critical_fields"]
    total = len(df)

    field_results = {}
    overall_pass = True

    for field in critical_fields:
        if field not in df.columns:
            field_results[field] = {"status": "FIELD_MISSING", "null_percent": None}
            overall_pass = False
            continue

        series = df[field]
        nulls = int(series.isna().sum())
        if series.dtype == object:
            empty_mask = series.astype(str).str.strip().eq("") & series.notna()
            nulls += int(empty_mask.sum())

        null_pct = round((nulls / total) * 100, 2) if total else 0.0
        status = "PASS" if null_pct <= threshold else "FAIL"
        if status == "FAIL":
            overall_pass = False

        field_results[field] = {
            "status": status,
            "null_percent": null_pct,
            "nulls": nulls,
        }

    return {
        "validation": "completeness",
        "status": "PASS" if overall_pass else "FAIL",
        "threshold_percent": threshold,
        "fields": field_results,
    }


# ---------------------------------------------------------------------
# 3. VOLUMETRIA (Z-SCORE)
# ---------------------------------------------------------------------

def check_volumetry(
    df: pd.DataFrame,
    contract: dict,
    engine,
    source_name: str,
    window_days: int = 30,
    min_history: int = 3
) -> dict:

    current_count = len(df)

    volumetry_config = contract.get("volumetry", {})

    window_days = volumetry_config.get(
        "window_days",
        window_days
    )

    threshold = volumetry_config.get(
        "z_score_threshold",
        3.0
    )

    query = sa_text("""
        SELECT record_count
        FROM data_quality_volume_history
        WHERE source_name = :source_name
          AND execution_date >= NOW() - (:window_days || ' days')::interval
        ORDER BY execution_date DESC
    """)

    try:

        with engine.connect() as conn:

            rows = conn.execute(
                query,
                {
                    "source_name": source_name,
                    "window_days": window_days
                }
            ).fetchall()

        historical_counts = [
            row[0]
            for row in rows
            if row[0] is not None
        ]

    except Exception as exc:

        return {
            "validation": "volumetry",
            "status": "ERROR",
            "message": str(exc),
            "current_count": current_count
        }

    if len(historical_counts) < min_history:

        return {
            "validation": "volumetry",
            "status": "INSUFFICIENT_HISTORY",
            "current_count": current_count,
            "history_count": len(historical_counts),
            "required_history": min_history
        }

    historical_series = pd.Series(
        historical_counts,
        dtype="float64"
    )

    historical_mean = historical_series.mean()

    historical_std = historical_series.std(
        ddof=1
    )

    if historical_std == 0:

        z_score = 0.0

    else:

        z_score = (
            current_count - historical_mean
        ) / historical_std

    status = (
        "PASS"
        if abs(z_score) <= threshold
        else "FAIL"
    )

    return {
        "validation": "volumetry",
        "status": status,
        "current_count": current_count,
        "historical_mean": historical_mean,
        "historical_std": historical_std,
        "z_score": z_score,
        "threshold": threshold,
        "history_count": len(historical_counts),
        "window_days": window_days
    }


# ---------------------------------------------------------------------
# 4. CONSISTENCIA DE ESQUEMA (basada en dtype de columna)
# ---------------------------------------------------------------------
_DTYPE_CHECKS = {
    "int": pd.api.types.is_integer_dtype,
    "float": pd.api.types.is_float_dtype,
    "string": lambda s: pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s),
    "bool": pd.api.types.is_bool_dtype,
    "timestamp": pd.api.types.is_datetime64_any_dtype,
    "date": pd.api.types.is_datetime64_any_dtype,
}


def check_schema_consistency(df: pd.DataFrame, contract: dict) -> dict:
    schema = contract["schema"]
    field_results = {}
    overall_pass = True

    for field, expected_type in schema.items():
        if field not in df.columns:
            field_results[field] = {"status": "FIELD_MISSING"}
            overall_pass = False
            continue

        check_fn = _DTYPE_CHECKS.get(expected_type)
        if check_fn is None:
            field_results[field] = {"status": "UNKNOWN_TYPE", "expected_type": expected_type}
            overall_pass = False
            continue

        is_valid = bool(check_fn(df[field]))
        status = "PASS" if is_valid else "FAIL"
        if status == "FAIL":
            overall_pass = False

        field_results[field] = {
            "status": status,
            "expected_type": expected_type,
            "actual_dtype": str(df[field].dtype),
        }

    return {
        "validation": "schema_consistency",
        "status": "PASS" if overall_pass else "FAIL",
        "fields": field_results,
    }


# ---------------------------------------------------------------------
# 5. INTEGRIDAD DE PROYECTO DE ORIGEN
# ---------------------------------------------------------------------
def check_project_integrity(df: pd.DataFrame, contract: dict) -> dict:
    config = contract.get("project_integrity")

    if not config:
        return {"validation": "project_integrity", "status": "NOT_APPLICABLE"}

    expected_id = str(config["expected_project_id"])
    expected_name = config["expected_project_name"]
    id_field = contract["identifier"]["field"]

    mismatches = df[df["project_id"].astype(str) != expected_id]
    status = "PASS" if mismatches.empty else "FAIL"

    return {
        "validation": "project_integrity",
        "status": status,
        "expected_project_id": expected_id,
        "expected_project_name": expected_name,
        "mismatched_records": mismatches[id_field].tolist() if not mismatches.empty else [],
    }


# ---------------------------------------------------------------------
# DATA HEALTH SCORE
# ---------------------------------------------------------------------
def calculate_health_score( results: list, contract: dict) -> float:

    weights = contract.get(
        "health_score",
        {}
    ).get(
        "weights",
        {}
    )

    weighted_score = 0.0
    total_weight = 0.0

    for result in results:

        validation_name = result["validation"]
        status = result["status"]

        weight = weights.get(
            validation_name,
            0
        )

        # Validación no aplicable
        if status == "NOT_APPLICABLE":
            continue

        # No tenemos suficiente histórico
        if status == "INSUFFICIENT_HISTORY":
            continue

        # Error técnico de ejecución
        if status == "ERROR":
            continue

        if status == "PASS":
            score = 100

        elif status == "FAIL":
            score = 0

        else:
            continue

        weighted_score += (
            score * weight
        )

        total_weight += weight

    if total_weight == 0:
        return 100.0

    return round(
        weighted_score / total_weight,
        2
    )

# ---------------------------------------------------------------------
# OBJETIVO 2: EVALUACION (reporte de auditoria, sin cargar datos)
# ---------------------------------------------------------------------
def run_validation(source_name: str, df: pd.DataFrame, contract_name: str, engine=None) -> dict:
    contract = load_contract(contract_name)
    results = [
        check_uniqueness(df, contract),
        check_completeness(df, contract),
        check_schema_consistency(df, contract),
        check_project_integrity(df, contract),
    ]
    if engine is not None:
        results.append(check_volumetry(df, contract, engine, source_name))

    health_score = calculate_health_score( results, contract)
    has_failure = any(r["status"] == "FAIL" for r in results)

    report = {
        "source": source_name,
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "record_count": len(df),
        "health_score": health_score,
        "overall_status": "FAIL" if has_failure else "PASS",
        "validations": results,
    }

    _write_audit_report(report, source_name)
    return report


# ---------------------------------------------------------------------
# OBJETIVO 3: ENRUTAMIENTO Y CARGA
# ---------------------------------------------------------------------
def should_abort_batch(results: list, contract: dict) -> tuple:
    """
    Fallas estructurales que invalidan la confiabilidad de TODO el lote:
    anomalia severa de volumetria, o inconsistencia de tipo en el
    identificador o en project_id. En estos casos no se enruta por
    fila: se aborta la carga completa.
    """
    id_field = contract["identifier"]["field"]
    for r in results:
        if r["validation"] == "volumetry" and r["status"] == "FAIL":
            return True, "volumetry_anomaly"
        if r["validation"] == "schema_consistency" and r["status"] == "FAIL":
            failed_fields = {f for f, res in r["fields"].items() if res["status"] == "FAIL"}
            if failed_fields & {id_field, "project_id"}:
                return True, "schema_break_on_identifier"
    return False, None


def route_records(df: pd.DataFrame, contract: dict) -> tuple:
    """
    Determina, fila por fila, cuales registros son validos para
    produccion y cuales deben redirigirse a la tabla de errores.
    """
    id_field = contract["identifier"]["field"]
    reasons = pd.Series([[] for _ in range(len(df))], index=df.index)

    dup_mask = df[id_field].duplicated(keep="first")
    for idx in df.index[dup_mask]:
        reasons[idx].append("duplicate_gid")

    for field in contract["completeness"]["critical_fields"]:
        if field not in df.columns:
            continue
        is_null = df[field].isna()
        if df[field].dtype == object:
            is_empty = df[field].astype(str).str.strip().eq("") & df[field].notna()
            is_null = is_null | is_empty
        for idx in df.index[is_null]:
            reasons[idx].append(f"null_critical_field:{field}")

    proj_config = contract.get("project_integrity")
    if proj_config:
        expected_id = str(proj_config["expected_project_id"])
        mismatch = df["project_id"].astype(str) != expected_id
        for idx in df.index[mismatch]:
            reasons[idx].append("project_mismatch")

    is_valid = reasons.apply(len).eq(0)
    df_valid = df[is_valid].copy()
    df_invalid = df[~is_valid].copy()
    if not df_invalid.empty:
        df_invalid["_validation_reasons"] = reasons[~is_valid].apply(lambda r: ", ".join(r))

    return df_valid, df_invalid


def _load_with_bootstrap(warehouse, df, table_name, insert_type, key_columns=None):
    """
    Inserta el DataFrame en la tabla indicada. Si la tabla aun no existe
    (caso tipico de las tablas de error en la primera ejecucion), se
    crea automaticamente con 'replace' y las ejecuciones futuras ya
    usaran el insert_type solicitado con normalidad.
    """
    try:
        warehouse.insert_dataframe(df, table_name, insert_type=insert_type, key_columns=key_columns)
    except ValueError:
        warehouse.insert_dataframe(df, table_name, insert_type="replace")


def _notify_team(source_name: str, report: dict) -> None:
    # Placeholder: reemplazar por notificacion real (correo/Slack) al
    # integrar con el Jenkinsfile.
    print(f"[ALERTA] Fallo de calidad en '{source_name}': {report.get('overall_status')}")


def _print_validation_summary(report: dict, df_invalid: pd.DataFrame = None) -> None:
    """
    Imprime un resumen legible del resultado de validación.
    Diseñado para facilitar auditoría, troubleshooting y evidencias del TFM.
    """

    print("----------------------------------------")
    print("RESULTADO VALIDATION ENGINE")
    print("----------------------------------------")

    print(f"Fuente:              {report['source']}")
    print(f"Execution ID:        {report['execution_id']}")
    print(f"Registros recibidos: {report['record_count']}")
    print(f"Registros cargados:  {report.get('records_loaded', 0)}")
    print(f"Registros rechazados:{report.get('records_rejected', 0)}")
    print(f"Health Score:        {report['health_score']}")
    print(f"Estado general:      {report['overall_status']}")

    print("----------------------------------------")
    print("VALIDACIONES")
    print("----------------------------------------")

    for validation in report["validations"]:

        name = validation["validation"]
        status = validation["status"]

        if status == "PASS":
            icon = "✓"
        elif status == "FAIL":
            icon = "✗"
        elif status == "INSUFFICIENT_HISTORY":
            icon = "⚠"
        else:
            icon = "•"

        print(f"{icon} {name:<22} {status}")

    print("----------------------------------------")
    print("INCIDENCIAS")
    print("----------------------------------------")

    if df_invalid is not None and not df_invalid.empty:

        print(f"Registros afectados: {len(df_invalid)}")

        if "_validation_reasons" in df_invalid.columns:

            reasons = (
                df_invalid["_validation_reasons"]
                .dropna()
                .astype(str)
            )

            for reason in reasons:

                for item in reason.split(","):

                    item = item.strip()

                    if item.startswith("null_critical_field:"):
                        field = item.replace(
                            "null_critical_field:",
                            ""
                        )

                        print(
                            f"✗ Campo crítico nulo: {field}"
                        )

                    elif item == "duplicate_gid":
                        print(
                            "✗ Identificador duplicado"
                        )

                    elif item == "project_mismatch":
                        print(
                            "✗ Inconsistencia de proyecto"
                        )

                    elif item == "volumetry_anomaly":
                        print(
                            "✗ Anomalía de volumetría"
                        )

                    else:
                        print(
                            f"✗ {item}"
                        )

    else:

        print("✓ No se detectaron registros rechazados.")

    print("----------------------------------------")
    print("RESUMEN")
    print("----------------------------------------")

    if report["overall_status"] == "PASS":

        print("✓ Ejecución completada correctamente.")

    elif report["overall_status"] == "PARTIAL":

        print("⚠ Ejecución completada parcialmente.")
        print(
            "  Los registros inválidos fueron "
            "redirigidos a la tabla de errores."
        )

    elif report["overall_status"] == "ABORTED":

        print("✗ Ejecución ABORTADA por calidad de datos.")

    else:

        print("✗ Ejecución finalizada con errores.")

    print("----------------------------------------")


def process_and_load(source_name: str, df: pd.DataFrame, contract_name: str, warehouse, key_columns: str = None) -> dict:
    """
    Objetivo 3: ejecuta las 5 validaciones, decide el enrutamiento y
    realiza la carga en PostgreSQL usando la clase SQLDatabaseConection
    ya existente (UPSERT para validos, tabla de errores para invalidos).

    Parametros:
        source_name: nombre de la tabla destino (ej. "asana_sales_task")
        df: DataFrame ya extraido y tipado por el script de ingesta
        contract_name: nombre del contrato en contracts/ (sin extension)
        warehouse: instancia de DataAnalytics / SQLDatabaseConection ya conectada
        key_columns: columna(s) clave para el UPSERT (por defecto, el
                     identificador declarado en el contrato)
    """
    
    start_time = time.perf_counter()

    execution_id = create_execution(
        warehouse=warehouse,
        source_name=source_name,
        record_count=len(df)
    )

    try:
        contract = load_contract(contract_name)

        key_columns = (
            key_columns
            or contract["identifier"]["field"]
        )

        volumetry_result = check_volumetry(
            df,
            contract,
            warehouse.engine,
            source_name
        )

        results = [
            check_uniqueness(df, contract),
            check_completeness(df, contract),
            check_schema_consistency(df, contract),
            check_project_integrity(df, contract),
            volumetry_result
        ]

        if "project_integrity" in contract:
            results.insert(
                3,
                check_project_integrity(df, contract)
            )

        save_validation_results( warehouse=warehouse, execution_id=execution_id, results=results)
        save_volume_history(warehouse=warehouse, execution_id=execution_id, source_name=source_name,  result=volumetry_result)

        health_score = calculate_health_score(results, contract )
        abort, abort_reason = should_abort_batch(results, contract)

        report = {
            "execution_id": execution_id,
            "source": source_name,
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "record_count": len(df),
            "health_score": health_score,
            "validations": results,
        }

        if abort:
            report["overall_status"] = "ABORTED"

            duration_seconds = time.perf_counter() - start_time

            update_execution(
                warehouse=warehouse,
                execution_id=execution_id,
                health_score=health_score,
                overall_status="ABORTED",
                records_loaded=0,
                records_rejected=len(df),
                duration_seconds=duration_seconds
            )
            report["abort_reason"] = abort_reason
            df_errors = df.copy()
            df_errors["_validation_reasons"] = abort_reason
            save_error_results(warehouse=warehouse, execution_id=execution_id, source_name=source_name, df_invalid=df_errors, contract=contract)
            _load_with_bootstrap(warehouse, df_errors, f"{source_name}_errors", insert_type="append")
            _notify_team(source_name, report)
            _write_audit_report(report, source_name)
            report["records_loaded"] = 0
            report["records_rejected"] = len(df)

            _print_validation_summary(
                report,
                df_errors
            )

            return report

        df_valid, df_invalid = route_records(df, contract)

        save_error_results( warehouse=warehouse, execution_id=execution_id, source_name=source_name, df_invalid=df_invalid, contract=contract)

        if not df_valid.empty:
            _load_with_bootstrap(warehouse, df_valid, source_name, insert_type="upsert", key_columns=key_columns)

        if not df_invalid.empty:
            _load_with_bootstrap(
                warehouse,
                df_invalid,
                f"{source_name}_errors",
                insert_type="append"
            )
            _notify_team(source_name, report)

        report["overall_status"] = "PASS" if df_invalid.empty else "PARTIAL"
        report["records_loaded"] = len(df_valid)
        report["records_rejected"] = len(df_invalid)

        _print_validation_summary(
            report,
            df_invalid
        )

        duration_seconds = time.perf_counter() - start_time

        update_execution(
            warehouse=warehouse,
            execution_id=execution_id,
            health_score=health_score,
            overall_status=report["overall_status"],
            records_loaded=len(df_valid),
            records_rejected=len(df_invalid),
            duration_seconds=duration_seconds
        )

        _write_audit_report(report, source_name)

        return report

    except Exception as exc:

        duration_seconds = (
            time.perf_counter() - start_time
        )

        mark_execution_error(
            warehouse=warehouse,
            execution_id=execution_id,
            error_message=str(exc),
            duration_seconds=duration_seconds
        )

        raise



def _write_audit_report(report: dict, source_name: str) -> None:
    os.makedirs("audit_reports", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = os.path.join("audit_reports", f"{source_name}_{timestamp}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)