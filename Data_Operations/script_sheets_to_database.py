import argparse

from Utils.Integrations.GoogleSheets.client import PeopleAndCultureSheets
from Utils.databaseConections import DataAnalytics

from Data_Operations.validation_engine import process_and_load


parser = argparse.ArgumentParser(
    description="Script para insertar datos de sheets a base de datos"
)

parser.add_argument(
    "--sheet_file",
    type=str,
    required=True,
    help="Sheet de la hoja a elegir"
)

parser.add_argument(
    "--sheet",
    type=str,
    required=True,
    help="Sheet de la hoja a elegir"
)

parser.add_argument(
    "--table",
    type=str,
    required=True,
    help="Tabla en la base de datos destino"
)

args = parser.parse_args()

print("Conectando a Google Sheets y Data Analytics...")

if args.sheet_file == "Bonus":

    Source = BonusSheets()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

elif args.sheet_file == "PeopleAndCulture":

    Source = PeopleAndCultureSheets()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

elif args.sheet_file == "InsideSales":

    Source = InsideSalesSheets()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

elif args.sheet_file == "FoxKids":

    Source = FoxKidsSheets()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

elif args.sheet_file == "TeamMap":

    Source = TeamMapSheets()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

elif args.sheet_file == "UnitEconomic":

    Source = UnitEconomic()

    if args.sheet not in Source.allowed_names:
        raise ValueError(
            f"El nombre de la hoja {args.sheet} "
            f"no existe para {args.sheet_file}"
        )

else:

    raise ValueError("sheet_file no válido")


Target = DataAnalytics()

print("Conectado a Google Sheets y Data Analytics correctamente\n")


# ============================================================
# OBTENER DATOS DE GOOGLE SHEETS
# ============================================================

print(
    f"Obteniendo datos de la hoja "
    f"{args.sheet} desde Google Sheets..."
)

source = Source[args.sheet]

print(
    f"Datos obtenidos correctamente de la hoja "
    f"{args.sheet} desde Google Sheets"
)

print("----------------------------------------")

print(
    f"Longitud {args.table}_df a cargar: "
    f"{len(source)}"
)

print("----------------------------------------")


# ============================================================
# VALIDACIÓN + ENRUTAMIENTO + CARGA
# ============================================================

report = process_and_load(
    warehouse=Target,
    source_name=args.table,
    df=source,
    contract_name="sheets_employees"
)


# ============================================================
# FIN
# ============================================================

print("Proceso finalizado.")