import os
import google.auth
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from Utils.constants import GOOGLE_SHEET_PEOPLE_AND_CULTURE_ID
from Utils.functions import Transform

class SheetsConection(Transform):
    """
    Conecta a Google Sheets API con un Service Account.
    Hereda de Transform las utilidades genericas de limpieza/casting de
    DataFrames: clean_strings, convert_dates, cast_fields, rename_select,
    normalize_columns (polimorfico: string o DataFrame).
    """

    #SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly","https://www.googleapis.com/auth/drive.readonly"]
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]

    @property
    def ranges(self):
        #{sheet_name: range, columns: {}}
        return []
    
    @property
    def sheet_id(self):
        return 1
    
    @property
    def allowed_names(self):
        return set()

    @property
    def clean_numeric(self):
        """
        Si es True, limpia los valores formateados (separadores de miles,
        simbolos de moneda) en las columnas numericas antes de castear.
        Default False para no alterar el comportamiento de las demas hojas.
        """
        return False

    def __init__(self):

        creds, _ = google.auth.default(
            scopes=self.SCOPES
        )

        self.service = build(
            "sheets",
            "v4",
            credentials=creds,
            cache_discovery=False
        )

        self.sheets = self.service.spreadsheets()
        self.sheets_map = {}

        self.build_sheets()

    def __getitem__(self, key: str) -> pd.DataFrame:
        """Permite usar instancia[key] para acceder a sheets_map"""
        return self.sheets_map[key]
    
    def build_sheets(self):
        for range in self.ranges:
            raw_sheet = self.get_page(range['range'])
            raw_sheet = self.cast_sheet_to_df(raw_sheet)
            raw_sheet = self.normalize_columns(raw_sheet, rename_columns=range.get('columns'))
            title_case_cols = tuple(range.get('title_case', []))
            clean_sheet = self.clean_strings(raw_sheet, title_case_cols=title_case_cols)
            clean_sheet = clean_sheet.replace("n/a", pd.NA) # reemplazar n/a por null
            if range.get("columns_config",None) is not None and range['columns_config'].get("dates",None) is not None:
                clean_sheet = self.convert_dates(clean_sheet, date_columns=list(range['columns_config']['dates']['date_columns']))
            if (
                range.get("columns_config", None) is not None
                and range["columns_config"].get("dtypes", None) is not None
            ):
                dtypes = range["columns_config"]["dtypes"]

                if self.clean_numeric:
                    clean_sheet = self.clean_numeric_columns(clean_sheet, dtypes)

                skip_cast = range["columns_config"].get("skip_cast", [])

                dtypes_to_apply = {
                    col: dtype
                    for col, dtype in dtypes.items()
                    if col not in skip_cast
                }

                clean_sheet = clean_sheet.astype(dtypes_to_apply)
            self.sheets_map[range['name']] = clean_sheet
    
    def get_page(self,name:str)->pd.DataFrame:
        raw_data = self.sheets.values().get(
            spreadsheetId=self.sheet_id,
            range=name
        ).execute()
        rows = raw_data.get("values", [])
        if not rows:
            raise RuntimeError(f"La hoja {name!r} no devolvio datos.")
        return rows
    
    def cast_sheet_to_df(self,rows: list[list]) -> pd.DataFrame:
    
        header = rows[0]
        data = rows[1:]
        num_cols = len(header)

        normalized_rows = [
            row + [None] * (num_cols - len(row)) if len(row) < num_cols else row[:num_cols]
            for row in data
        ]
        normalized_rows = [
            row for row in normalized_rows
            if any(value not in (None, "") for value in row)
        ]

        return pd.DataFrame(normalized_rows, columns=header)

    NUMERIC_DTYPES = {"float", "Float64", "Float32", "int", "Int64", "Int32"}

    def clean_numeric_columns(self, df: pd.DataFrame, dtypes: dict) -> pd.DataFrame:
        """
        Limpia los valores formateados que devuelve Google Sheets (ej:
        '1,000.00', '$ 3.504') antes de castear a un dtype numerico.
        Solo toca las columnas cuyo dtype destino es numerico: quita simbolos
        de moneda/espacios y separadores de miles (coma), dejando el punto
        como separador decimal. Las cadenas vacias se vuelven NA.
        """
        cleaned = df.copy()
        for col, dtype in dtypes.items():
            if col not in cleaned.columns or str(dtype) not in self.NUMERIC_DTYPES:
                continue
            s = cleaned[col].astype("string")
            s = s.str.replace(r"[^\d,.\-]", "", regex=True)  # quitar $, espacios, etc.
            s = s.str.replace(",", "", regex=False)           # quitar separador de miles
            cleaned[col] = s.replace("", pd.NA)
        return cleaned

    # clean_strings, convert_dates y normalize_columns (polimorfico) se
    # heredan de Transform (ver Utils/functions.py).


class PeopleAndCultureSheets(SheetsConection):

    @property
    def sheet_id(self):
        return GOOGLE_SHEET_PEOPLE_AND_CULTURE_ID
    
    @property
    def allowed_names(self):
        return set(["Employees"])
    
    @property
    def ranges(self):
        return [
            {
                "range": "'Employees'!A:AL",
                "name": "Employees",
                "columns": {
                        "id_type": "identification_type",
                        "birthday_yyyy_mm_dd": "birthday",
                        "join_date_yyyy_mm_dd": "join_date",
                        "continuing_education": "specialization",
                        "do_you_have_children": "children",
                        "how_many_children": "number_of_children",
                        "relationship": "emergency_relationship",
                        "number_emergency_contact": "emergency_number_contact",
                        "private_health_insurance": "prepagada",
                        "medical_conditions_or_allergies": "medical_conditions",
                        "condition_or_allergy_details": "details_medical_conditions",
                        "any_dietary_restrictions": "dietary_restrictions",
                        "sweater_tshirt_size": "sweater",
                        "is_referred": "ingreso_como_referido",
                        "referred_by": "referido",
                        "referral_completion_date": "fecha_cumplimiento_referido",
                        "reason": "motivo",
                        "photo_link": "link_foto",
                    },
                "title_case": ["name","emergency_contact"],
                "columns_config": {
                    "dates": {
                        "date_columns": [
                            "birthday",
                            "end_date",
                            "join_date",
                            "fecha_cumplimiento_referido"
                        ],
                        "timestamp_columns": [],
                        "date_format": "%Y-%m-%d",
                        "timestamp_format": "%Y-%m-%d %H:%M:%S"
                    },

                    "dtypes": {
                        "identification_type": "string",
                        "id_country": "string",
                        "id_number": "string",
                        "mail_corporativo": "string",
                        "name": "string",
                        "birthday": "datetime64[ns]",
                        "gender": "string",
                        "company": "string",
                        "department": "string",
                        "team": "string",
                        "role": "string",
                        "join_date": "datetime64[ns]",
                        "employee_phone_number": "string",
                        "personal_mail": "string",
                        "country": "string",
                        "city": "string",
                        "address": "string",
                        "profession": "string",
                        "specialization": "string",
                        "civil_status": "string",
                        "children": "string",
                        "number_of_children": "Int64",
                        "emergency_contact": "string",
                        "emergency_relationship": "string",
                        "emergency_number_contact": "string",
                        "eps": "string",
                        "prepagada": "string",
                        "medical_conditions": "string",
                        "details_medical_conditions": "string",
                        "dietary_restrictions": "string",
                        "blood_type": "string",
                        "sweater": "string",
                        "ingreso_como_referido": "string",
                        "referido": "string",
                        "fecha_cumplimiento_referido": "datetime64[ns]",
                        "end_date": "datetime64[ns]",
                        "status": "string",
                        "motivo": "string"
                    }
                }
            }
        ]

