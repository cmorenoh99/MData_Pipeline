"""
Utils/lineage.py

Componente transversal para la captura de linaje mediante OpenLineage.

El run_id utilizado por OpenLineage corresponde al execution_id
generado por el Validation Engine, permitiendo correlacionar:

    Data Quality <-> OpenLineage <-> Marquez
"""

import os
from datetime import datetime, timezone

from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import (
    InputDataset,
    Job,
    OutputDataset,
    Run,
    RunEvent,
    RunState,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

OPENLINEAGE_URL = os.getenv(
    "OPENLINEAGE_URL",
    "http://localhost:5000"
)

OPENLINEAGE_NAMESPACE = os.getenv(
    "OPENLINEAGE_NAMESPACE",
    "mdata_pipeline"
)

PRODUCER = "https://github.com/cmorenoh99/MData_Pipeline"


client = OpenLineageClient(
    config={
        "transport": {
            "type": "http",
            "url": OPENLINEAGE_URL,
        }
    }
)


# ============================================================
# CONFIGURACIÓN DE LOS PIPELINES
# ============================================================

LINEAGE_CONFIG = {

    "asana_sales_task": {
        "job": "ingest_asana_sales",
        "input_namespace": "asana",
        "input_name": "Sales.tasks",
        "output_namespace": "postgresql",
        "output_name": "asana_sales_task",
    },

    "asana_operations_task": {
        "job": "ingest_asana_operations",
        "input_namespace": "asana",
        "input_name": "Operations.tasks",
        "output_namespace": "postgresql",
        "output_name": "asana_operations_task",
    },

    "sheets_employees": {
        "job": "ingest_sheets_employees",
        "input_namespace": "google_sheets",
        "input_name": "PeopleAndCulture.Employees",
        "output_namespace": "postgresql",
        "output_name": "sheets_employees",
    },
}


# ============================================================
# UTILIDADES
# ============================================================

def _current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_config(source_name: str) -> dict:
    """
    Obtiene la configuración de lineage correspondiente
    al proceso de ingestión.
    """

    if source_name not in LINEAGE_CONFIG:
        raise ValueError(
            f"No existe configuración de OpenLineage "
            f"para source_name='{source_name}'"
        )

    return LINEAGE_CONFIG[source_name]


def _build_event(
    run_id: str,
    source_name: str,
    state: RunState,
) -> RunEvent:

    config = _get_config(source_name)

    job = Job(
        namespace=OPENLINEAGE_NAMESPACE,
        name=config["job"],
    )

    run = Run(
        runId=run_id,
    )

    input_dataset = InputDataset(
        namespace=config["input_namespace"],
        name=config["input_name"],
    )

    output_dataset = OutputDataset(
        namespace=config["output_namespace"],
        name=config["output_name"],
    )

    return RunEvent(
        eventType=state,
        eventTime=_current_time(),
        run=run,
        job=job,
        producer=PRODUCER,
        inputs=[input_dataset],
        outputs=[output_dataset],
    )


def _emit(
    run_id: str,
    source_name: str,
    state: RunState,
) -> None:

    event = _build_event(
        run_id=run_id,
        source_name=source_name,
        state=state,
    )

    client.emit(event)


# ============================================================
# START
# ============================================================

def start_lineage_run(
    run_id: str,
    source_name: str,
) -> None:
    """
    Registra el inicio de una ejecución del pipeline.
    """

    _emit(
        run_id=run_id,
        source_name=source_name,
        state=RunState.START,
    )


# ============================================================
# COMPLETE
# ============================================================

def complete_lineage_run(
    run_id: str,
    source_name: str,
) -> None:
    """
    Registra la finalización técnica de una ejecución.

    Tanto PASS como PARTIAL del Validation Engine
    representan una ejecución técnica completada.
    """

    _emit(
        run_id=run_id,
        source_name=source_name,
        state=RunState.COMPLETE,
    )


# ============================================================
# ABORT
# ============================================================

def abort_lineage_run(
    run_id: str,
    source_name: str,
) -> None:
    """
    Registra una ejecución abortada por una política
    de calidad de datos.
    """

    _emit(
        run_id=run_id,
        source_name=source_name,
        state=RunState.ABORT,
    )


# ============================================================
# FAIL
# ============================================================

def fail_lineage_run(
    run_id: str,
    source_name: str,
) -> None:
    """
    Registra una ejecución terminada por un error técnico.
    """

    _emit(
        run_id=run_id,
        source_name=source_name,
        state=RunState.FAIL,
    )