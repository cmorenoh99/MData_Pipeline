import json
import re
import unicodedata
from typing import Optional
import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype


class Transform:
    """
    Utilidades genericas para transformacion de DataFrames ya construidos.

    Diseñada para ser heredada por integraciones que necesiten:
      - Strings + columnas: normalize_columns (polimorfico)
      - Schema-driven:      cast_fields, rename_select
      - Limpieza:           clean_strings, convert_dates

    No depende del origen de los datos (Pipedrive, Jira, GoogleSheets, etc.).
    Para utilidades especificas de aplastar JSON anidado, ver TransformJSON.
    """

    # ------------------------------------------------------------------
    # Normalizacion snake_case (string unitario o columnas de DataFrame)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_columns(value, rename_columns: dict[str, str] | None = None):
        """
        Convierte a snake_case ASCII apto para columnas SQL. Polimorfico:

            - Si recibe un string: devuelve el string normalizado.
              Ej: "Ciudad / Pais" -> "ciudad_pais", "Pretensión" -> "pretension".

            - Si recibe un DataFrame: normaliza todas las columnas aplicando
              `split('.')[-1]` (para aplastar prefijos de pd.json_normalize)
              y opcionalmente aplica un dict `rename_columns` despues.

        En ambos casos elimina acentos (NFKD + strip combining marks) y
        reemplaza caracteres no-alfanumericos por "_".
        """
        if isinstance(value, pd.DataFrame):
            cleaned = value.copy()
            cleaned.columns = [
                Transform.normalize_columns(c.split(".")[-1]) for c in cleaned.columns
            ]
            if rename_columns:
                cleaned.rename(columns=rename_columns, inplace=True)
            return cleaned

        n = unicodedata.normalize("NFKD", str(value))
        n = "".join(c for c in n if not unicodedata.combining(c))
        return re.sub(r"[^a-zA-Z0-9]+", "_", n).strip("_").lower()

    # ------------------------------------------------------------------
    # Schema-driven (rename + select + cast)
    # ------------------------------------------------------------------

    def cast_fields(self, df: pd.DataFrame, schema: dict[str, tuple[str, str]]) -> pd.DataFrame:
        """
        Aplica casting de tipos según `schema` (dict donde la key es el nombre
        de la columna origen, y el value es una tupla (renombre, dtype)).
            - datetime64[ns]: se normaliza a UTC y se deja timezone-naive.
            - Int64 / Float64: nullable usando to_numeric.
            - date: solo fecha (sin hora).
            - otros: astype directo.
        """
        for _, (dst, dtype) in schema.items():
            if dst not in df.columns:
                continue
            if dtype == "datetime64[ns]":
                df[dst] = pd.to_datetime(df[dst], errors="coerce", utc=True).dt.tz_convert(None)
            elif dtype == "Int64":
                s = df[dst]
                if s.dtype == object:
                    s = s.astype(str).str.extract(r"(\d+)", expand=False)
                df[dst] = pd.to_numeric(s, errors="coerce").astype("Int64")
            elif dtype == "Float64":
                df[dst] = pd.to_numeric(df[dst], errors="coerce").astype("Float64")
            elif dtype == "date":
                df[dst] = pd.to_datetime(df[dst], errors="coerce").dt.floor("D")
            elif dtype in ["object", "array"]:
                continue
            else:
                df[dst] = df[dst].astype(dtype)
        return df

    def rename_select(
        self,
        df: pd.DataFrame,
        schema: dict[str, tuple[str, str]],
        sort_by: str | None = None,
        ascending: bool = False,
        cast: bool = True,
    ) -> pd.DataFrame:
        """
        Pipeline schema-driven generico para todas las integraciones:
            1) Filtra el DataFrame a las columnas origen presentes en el schema
               (para columnas que no existen en el DataFrame, se crean con pd.NA).
            2) Renombra las columnas al nombre destino.
            3) Si cast=True (default), aplica `cast_fields` con los dtypes del
               schema.
            4) Si sort_by y la columna destino existe, ordena.

        Args:
            df: DataFrame origen.
            schema: dict {src: (dst, dtype)}.
            sort_by: columna destino por la que ordenar (opcional).
            ascending: sentido de ordenamiento (default False).
            cast: aplicar casting de tipos al final. Default True.
        Returns:
            DataFrame final con cols renombradas, tipadas y (opcionalmente)
            ordenadas, en el orden del schema.
        """
        out = pd.DataFrame(
            {dst: df[src].copy() if src in df.columns else pd.Series(pd.NA, index=df.index)
             for src, (dst, _) in schema.items()},
            index=df.index,
        )
        if cast:
            out = self.cast_fields(out, schema)
        if sort_by and sort_by in out.columns:
            out = out.sort_values(by=sort_by, ascending=ascending)
        return out

    # ------------------------------------------------------------------
    # Limpieza de DataFrames
    # ------------------------------------------------------------------

    def clean_strings(self, df: pd.DataFrame, title_case_cols: tuple[str, ...] = ()) -> pd.DataFrame:
        """
        Normaliza columnas tipo string del DataFrame:
            - colapsa whitespaces multiples.
            - aplica strip.
            - aplica title case en las columnas listadas en title_case_cols.
            - cadenas vacias "" se reemplazan por pd.NA.
        """
        cleaned = df.copy()
        title_case = set(title_case_cols)

        for col in cleaned.columns:
            if is_object_dtype(cleaned[col]) or is_string_dtype(cleaned[col]):
                if cleaned[col].apply(lambda x: isinstance(x, (list, dict))).any():
                    continue
                s = cleaned[col].astype("string")

                if col in title_case:
                    cleaned[col] = (
                        cleaned[col]
                        .str.replace(r"\s+", " ", regex=True)
                        .str.strip()
                        .str.title()
                        .replace({"": pd.NA})
                    )
                else:
                    cleaned[col] = (
                        cleaned[col]
                        .str.replace(r"\s+", " ", regex=True)
                        .str.strip()
                        .replace({"": pd.NA})
                    )
        return cleaned

    def convert_dates(
        self,
        df: pd.DataFrame,
        date_columns: Optional[list[str]] = None,
        timestamp_columns: Optional[list[str]] = None,
        date_format: str = "%Y-%m-%d",
        timestamp_format: str = "%Y-%m-%d %H:%M:%S",
    ) -> pd.DataFrame:
        """
        Convierte columnas de fechas y timestamps en el DataFrame.
            - date_columns: parsea y convierte a date (YYYY-MM-DD) -> datetime.date.
            - timestamp_columns: parsea y mantiene como datetime64[ns].
        """
        if not date_columns and not timestamp_columns:
            return df

        converted = df.copy()

        if date_columns:
            for col in date_columns:
                if col in converted.columns:
                    converted[col] = pd.to_datetime(converted[col], errors="coerce", format=date_format).dt.floor("D")

        if timestamp_columns:
            for col in timestamp_columns:
                if col in converted.columns:
                    converted[col] = pd.to_datetime(converted[col], errors="coerce", format=timestamp_format)

        return converted


class TransformJSON(Transform):
    """
    Extiende Transform con utilidades para aplastar respuestas JSON anidadas
    (dicts y listas anidadas), tipico en APIs REST como Jira, Pipedrive, Asana.
    """

    # ------------------------------------------------------------------
    # Aplastado de valores JSON unitarios
    # ------------------------------------------------------------------

    @staticmethod
    def extract_scalar(
        val,
        dict_keys: tuple = ("displayName", "name", "value", "accountId"),
        list_sep: str = ", ",
    ):
        """
        Aplana un valor anidado de API a un escalar Python.
            - dict: extrae el primer key encontrado de `dict_keys`. Si ninguno
                    aplica, fallback a str(val).
            - list: concatena recursivamente los elementos con `list_sep`.
                    Lista vacia -> None.
            - otros: devuelve tal cual.
        """
        if isinstance(val, dict):
            for k in dict_keys:
                if k in val:
                    return val[k]
            return str(val)
        if isinstance(val, list):
            if not val:
                return None
            return list_sep.join(
                str(TransformJSON.extract_scalar(i, dict_keys, list_sep)) for i in val
            )
        return val

    # ------------------------------------------------------------------
    # Detectores de columnas JSON-anidadas
    # ------------------------------------------------------------------

    def _as_dict(self, x):
        """
        Intenta convertir la entrada en un diccionario:
            - (dict) lo retorna igual.
            - (str JSON que empieza con "{") intenta parsear con json.loads.
            - (otro/None/NaN) retorna {}.
        """
        if isinstance(x, dict):
            return x
        if isinstance(x, str) and x.strip().startswith("{"):
            try:
                v = json.loads(x)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
        return {}

    def get_dict_columns(self, df, sample=50, min_ratio=0.7):
        """Detecta columnas que contienen valores tipo dict/json."""
        out = []
        for c in df.columns:
            s = df[c].dropna().head(sample)
            if not s.empty and s.map(lambda x: self._as_dict(x) != {}).mean() >= min_ratio:
                out.append(c)
        return out

    def get_list_of_dict_columns(self, df: pd.DataFrame, max_checks: int = 30) -> dict:
        """
        Clasifica columnas list[dict] en 2 grupos:
            - primary: listas con dicts {value, primary} (Pipedrive style).
            - one_to_many: cualquier otra lista de dicts.
        Retorna dict con primary, one_to_many y all.
        """
        primary_cols = []
        one_to_many_cols = []
        all_cols = []

        for col in df.columns:
            sample_values = df[col].dropna().head(max_checks)
            found_list_of_dict = False
            found_primary_pattern = False

            for v in sample_values:
                if not (isinstance(v, list) and v):
                    continue
                first_item = v[0]
                if not isinstance(first_item, dict):
                    continue
                found_list_of_dict = True
                keys = first_item.keys()
                if "value" in keys and "primary" in keys:
                    found_primary_pattern = True

            if found_list_of_dict:
                all_cols.append(col)
                if found_primary_pattern:
                    primary_cols.append(col)
                else:
                    one_to_many_cols.append(col)

        return {
            "primary": primary_cols,
            "one_to_many": one_to_many_cols,
            "all": all_cols,
        }

    # ------------------------------------------------------------------
    # Aplastado de columnas JSON-anidadas
    # ------------------------------------------------------------------

    def extract_primary_value(self, lst):
        """
        Extrae el valor "principal" desde una lista de diccionarios.
        Busca el dict con primary=True; fallback al primer elemento.
        """
        if not isinstance(lst, list) or len(lst) == 0:
            return pd.NA
        for it in lst:
            if isinstance(it, dict) and it.get("primary") is True:
                return it.get("value", pd.NA)
        first = lst[0]
        if isinstance(first, dict):
            return first.get("value", pd.NA)
        return first

    def normalize_dict(self, df: pd.DataFrame, cols=None, sample: int = 50, min_ratio: float = 0.7) -> pd.DataFrame:
        """
        Recibe un DataFrame con columnas dict/json y devuelve uno "plano":
            1) Normaliza columnas dict/json.
            2) Aplana con pd.json_normalize y agrega prefijos por columna.
        """
        deals = df.copy()
        cols = cols or self.get_dict_columns(deals, sample=sample, min_ratio=min_ratio)

        for c in cols:
            if c in deals.columns:
                deals[c] = deals[c].map(self._as_dict)

        deals_flat = deals.copy()
        for c in cols:
            if c in deals_flat.columns:
                flat = pd.json_normalize(deals_flat[c]).add_prefix(f"{c}_")
                deals_flat = deals_flat.drop(columns=[c]).join(flat)

        return deals_flat

    def normalize_list_dict_primary(self, df: pd.DataFrame, max_checks: int = 30) -> pd.DataFrame:
        """
        Para columnas list[dict] tipo primary-value: reemplaza la columna
        original por el valor escalar.
        """
        df_out = df.copy()
        list_cols = self.get_list_of_dict_columns(df_out, max_checks=max_checks)
        primary_cols = list_cols["primary"]
        for col in primary_cols:
            df_out[col] = df_out[col].apply(self.extract_primary_value)
        return df_out

    def normalize_list_dict_one_to_many(self,df: pd.DataFrame,max_checks: int = 30) -> dict[str, pd.DataFrame]:
        """
        Para cada columna list[dict] one-to-many:
            1) explode(col).
            2) normalize_dict(tmp).
        Retorna:
            {"col": df_normalizado, ...}.
        """
        cols = self.get_list_of_dict_columns(df,max_checks=max_checks)["one_to_many"]
        children = {}

        for col in cols:
            tmp = df.copy()
            tmp = tmp.explode(col, ignore_index=True)
            tmp = self.normalize_dict(tmp)
            children[col] = tmp
        return children

