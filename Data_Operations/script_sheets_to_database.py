import argparse
from Utils.Integrations.GoogleSheets.client import PeopleAndCultureSheets
from Utils.databaseConections import DataAnalytics
from Data_Operations.validation_engine import process_and_load
parser = argparse.ArgumentParser(description="Script para insertar datos de sheets a base de datos")

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
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
elif args.sheet_file == "PeopleAndCulture":
    Source = PeopleAndCultureSheets()
    if args.sheet not in Source.allowed_names:
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
elif args.sheet_file == "InsideSales":
    Source = InsideSalesSheets()
    if args.sheet not in Source.allowed_names:
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
elif args.sheet_file == "FoxKids":
    Source = FoxKidsSheets()
    if args.sheet not in Source.allowed_names:
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
elif args.sheet_file == "TeamMap":
    Source = TeamMapSheets()
    if args.sheet not in Source.allowed_names:
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
elif args.sheet_file == "UnitEconomic":
    Source = UnitEconomic()
    if args.sheet not in Source.allowed_names:
        raise ValueError(f"El nombre de la hoja {args.sheet} no existe para {args.sheet_file}")
else:
    raise ValueError("sheet_file no válido")
Target = DataAnalytics()
print("Conectado a google sheets Y Data Analytics correctamente\n")
    
# Obtener datos de la sheet seleccionada
print(f"\nObteniendo datos de la hoja {args.sheet} desde Google Sheets...")
print(f"Datos obtenidos correctamente de la hoja {args.sheet} desde Google Sheets")

source = Source[args.sheet]
print("----------------------------------------")
print(f"Longitud {args.table}_df a cargar: {len(source)}")
print("----------------------------------------")

report = process_and_load(
    warehouse=Target,
    source_name=args.table,
    df=source,
    contract_name="sheets_employees"
)

print("----------------------------------------")
print("RESULTADO VALIDATION ENGINE")
print(report)
print("----------------------------------------")

if report["overall_status"] == "ABORTED":
    raise SystemExit(2)

elif report["overall_status"] not in ["PASS", "PARTIAL"]:
    raise SystemExit(1)

raise SystemExit(0) 