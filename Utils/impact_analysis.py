import os
import yaml
import requests


MARQUEZ_URL = os.getenv(
    "OPENLINEAGE_URL",
    "http://localhost:5000"
)

ASSETS_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "Data_Operations",
    "contracts",
    "analytical_assets.yaml"
)


def load_analytical_assets():
    """
    Carga el inventario de activos analíticos definidos
    en analytical_assets.yaml.
    """
    try:
        with open(ASSETS_CONFIG_PATH, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

        return config.get("assets", [])

    except Exception as e:
        print(f"[IMPACT ANALYSIS] Error cargando analytical_assets.yaml: {e}")
        return []

def get_marquez_lineage(dataset_namespace, dataset_name, depth=20):
    """
    Consulta el grafo de linaje almacenado en Marquez
    para un dataset determinado.
    """

    node_id = f"dataset:{dataset_namespace}:{dataset_name}"

    url = f"{MARQUEZ_URL}/api/v1/lineage"

    try:
        response = requests.get(
            url,
            params={
                "nodeId": node_id,
                "depth": depth
            },
            timeout=10
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:
        print(
            f"[IMPACT ANALYSIS] Error consultando "
            f"Marquez para {node_id}: {e}"
        )
        return None

def get_downstream_assets(dataset_name):
    """
    Busca qué activos analíticos declarados dependen
    del dataset afectado.
    """

    assets = load_analytical_assets()

    impacted_assets = []

    for asset in assets:

        datasets = asset.get("datasets", [])

        if dataset_name in datasets:

            impacted_assets.append({
                "name": asset.get("name"),
                "type": asset.get("type"),
                "owner": asset.get("owner")
            })

    return impacted_assets


def analyze_impact(
    dataset_namespace,
    dataset_name,
    execution_id,
    issue
):
    """
    Ejecuta el análisis de impacto de una incidencia
    de calidad de datos.

    1. Consulta el grafo de Marquez.
    2. Comprueba que el dataset existe en lineage.
    3. Busca activos analíticos dependientes.
    4. Devuelve el resultado estructurado.
    """

    print("\n" + "=" * 70)
    print("IMPACT ANALYSIS")
    print("=" * 70)

    print(f"Execution ID: {execution_id}")
    print(f"Dataset afectado: {dataset_name}")
    print(f"Incidencia: {issue}")

    # -------------------------------------------------
    # 1. Consultar grafo de lineage
    # -------------------------------------------------

    lineage = get_marquez_lineage(
        dataset_namespace=dataset_namespace,
        dataset_name=dataset_name
    )

    lineage_available = lineage is not None

    if lineage_available:

        graph = lineage.get("graph", [])

        print(
            f"Grafo Marquez consultado correctamente "
            f"({len(graph)} nodos)"
        )

    else:

        graph = []

        print(
            "No fue posible recuperar el grafo "
            "de linaje desde Marquez."
        )

    # -------------------------------------------------
    # 2. Consultar activos analíticos
    # -------------------------------------------------

    impacted_assets = get_downstream_assets(dataset_name)

    # -------------------------------------------------
    # 3. Determinar impacto
    # -------------------------------------------------

    if not lineage_available:
        impact_status = "LINEAGE_UNAVAILABLE"
    elif impacted_assets:
        impact_status = "IMPACTED"
    else:
        impact_status = "NO_DOWNSTREAM_ASSETS"

    # -------------------------------------------------
    # 4. Resultado
    # -------------------------------------------------

    result = {
        "execution_id": execution_id,
        "dataset_namespace": dataset_namespace,
        "dataset": dataset_name,
        "issue": issue,
        "impact_status": impact_status,
        "lineage_available": lineage_available,
        "lineage_nodes": len(graph),
        "downstream_assets": impacted_assets
    }

    # -------------------------------------------------
    # 5. Mostrar resultado
    # -------------------------------------------------

    print(f"Impact status: {impact_status}")

    if impacted_assets:

        print("\nActivos analíticos potencialmente afectados:")

        for asset in impacted_assets:

            print(
                f"  - {asset['name']} "
                f"({asset['type']}) "
                f"| Owner: {asset['owner']}"
            )

    else:

        print(
            "No se identificaron activos analíticos "
            "dependientes."
        )

    print("=" * 70)

    return result

from Utils.lineage import LINEAGE_CONFIG


def analyze_source_impact(
    source_name,
    execution_id,
    issue
):
    """
    Ejecuta Impact Analysis utilizando la configuración
    de lineage definida para la fuente.
    """

    config = LINEAGE_CONFIG.get(source_name)

    if not config:

        print(
            f"[IMPACT ANALYSIS] No existe configuración "
            f"de lineage para {source_name}"
        )

        return {
            "execution_id": execution_id,
            "dataset": source_name,
            "issue": issue,
            "impact_status": "LINEAGE_NOT_CONFIGURED",
            "downstream_assets": []
        }

    return analyze_impact(
        dataset_namespace=config["output_namespace"],
        dataset_name=config["output_name"],
        execution_id=execution_id,
        issue=issue
    )