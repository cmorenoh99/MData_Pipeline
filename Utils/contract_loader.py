from pathlib import Path
import yaml


def load_contract(contract_name: str) -> dict:

    base_path = Path(__file__).resolve().parent.parent

    contract_path = (
        base_path
        / "Data_Operations"
        / "contracts"
        / f"{contract_name}.yaml"
    )

    if not contract_path.exists():
        raise FileNotFoundError(
            f"No se encontró el contrato: {contract_path}"
        )

    with open(contract_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)