import os
import urllib.parse
import pandas as pd
import json
from dotenv import load_dotenv
from typing import Literal, Sequence
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ResourceClosedError
from psycopg2.extensions import JSONB
load_dotenv()

class SQLDatabaseConection:

    def __init__(self):
        self.engine = None
        
    def _write_dataframe(self, df: pd.DataFrame, table_name: str, if_exists: str = "append",conn=None) -> None:
        """
        Escribe un DataFrame en la base de datos usando pandas.to_sql.
        - df: DataFrame a escribir.
        - table_name: nombre de la tabla destino (puede incluir esquema, e.g. "schema.table").
        - if_exists: comportamiento si la tabla ya existe ("append", "replace" o "fail").
        """
        if self.engine is None:
            raise RuntimeError("SQLAlchemy engine is not initialized.")

        for col in df.columns:
            # Detecta si la columna tiene dict o list en algún valor
            if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
                # Convertir a JSON string SOLO donde aplique
                df[col] = df[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)

        df.to_sql(
            name=table_name,
            con=conn if conn is not None else self.engine, 
            if_exists=if_exists,
            index=False,
            chunksize=5000,
            method="multi",
        )
    
    
    def _validate_columns(self, df: pd.DataFrame, table_name: str) -> bool:
        """
        Valida que todas las columnas del DataFrame existan en la tabla destino.
        Retorna:
            - True  si la tabla existe y las columnas son compatibles.
            - False si la tabla no existe o las columnas no son simétricas.
        """
        inspector = inspect(self.engine)
        if not inspector.has_table(table_name):
            return False

        target_columns = {col["name"] for col in inspector.get_columns(table_name)}
        missing_cols   = [c for c in df.columns if c not in target_columns]
        if missing_cols:
            return False

        return True

    def insert_dataframe(self, 
                        df: pd.DataFrame, 
                        table_name: str, 
                        insert_type: Literal["append", "replace", "upsert"] = "replace", 
                        key_columns: str | Sequence[str] | None = None,
                        ) -> None:
        """
        Inserta un DataFrame en la tabla destino según la estrategia indicada.
        Parámetros:
            - df : pd.DataFrame --> Datos a insertar. No puede estar vacío.
            - table_name : str -->Tabla destino. Acepta formato ``"schema.tabla"`` o ``"tabla"``.
            - insert_type : {"append", "replace", "upsert"}
                * "append" --> Agrega filas al final de la tabla.       
                * "replace" -->  TRUNCATE + INSERT en la misma transacción (crea la tabla si no existe).
                * "upsert"  —-> UPDATE filas existentes + INSERT filas nuevas (atómico en una sola transacción. Requiere 'key_columns').
            - key_columns : str | Sequence[str], opcional --> Solo para insert_type="upsert". Nombre(s) de columna(s) que definen la clave única para detectar filas existentes (e.g. "id" o ["id", "fecha"]).
        """
        # Validaciones básicas
        if df.empty:
            raise ValueError("El dataframe está vacío. No hay datos para insertar.")
        if insert_type not in {'append','replace', 'upsert'}:
            raise ValueError("Elija por favor uno de los tipos de inserción válidos ['append', 'replace', 'upsert'].")
        if self.engine is None:
            raise RuntimeError("SQLAlchemy engine no pudo ser inicializado.")

        # Append
        if insert_type == "append":
            if not self._validate_columns(df, table_name):
                raise ValueError(f"La tabla '{table_name}' no existe o las columnas no son simetricas entre el DataFrame y el {table_name}.")
            self._write_dataframe(df, table_name, if_exists="append") # Insertar nuevas filas con append
            print(f"Se insertaron un total {df.shape[0]:,} registros en la tabla {table_name} con append.")
        
        # Replace (TRUNCATE + INSERT en la misma transacción)Q
        elif insert_type == "replace":
            if not self._validate_columns(df, table_name):
                self._write_dataframe(df, table_name, if_exists="replace") # Crea la tabla nueva con los datos del DataFrame
                print(f"Tabla '{table_name}' creada con la estructura del DataFrame, insertando un total de {df.shape[0]:,} registros.")
            else:
                with self.engine.begin() as conn:
                    conn.execute(text(f"TRUNCATE TABLE {table_name}")) # Truncate (borra filas pero mantiene la tabla y su estructura)
                    self._write_dataframe(df, table_name, if_exists="append", conn=conn) # Insertar nuevas filas con append
                print(f"Tabla '{table_name}' truncada y reemplazada con un total de {df.shape[0]:,} registros.")
                    
        # Upsert (UPDATE filas existentes + INSERT filas nuevas)
        elif insert_type == "upsert":
            if not self._validate_columns(df, table_name):
                raise ValueError(f"La tabla '{table_name}' no existe o las columnas no son simetricas entre el DataFrame y el {table_name}.")
            if key_columns is None:
                raise ValueError("Para insert_type='upsert' se requiere especificar key_columns.")
                        
            # Definicion de tabla temporal y cláusulas SET y WHERE para la consulta de upsert
            temporal_table_name = "stage_" + table_name
            keys = [key_columns] if isinstance(key_columns, str) else list(key_columns)
            set_cols = [col for col in df.columns if col not in keys]

            # Detectar columnas JSON/JSONB, timestamp y numéricas en destino
            # para hacer cast explícito (la tabla stage hereda dtypes del DF
            # y suele quedar como text → mismatch al hacer UPDATE/INSERT).
            inspector = inspect(self.engine)
            col_type_map = {}
            for _col in inspector.get_columns(table_name):
                t = _col["type"].__class__.__name__.lower()
                if 'timestamp' in t:
                    t = 'timestamptz' if getattr(_col["type"], 'timezone', False) else 'timestamp'
                col_type_map[_col["name"]] = t

            # Mapeo de nombres de tipo SQLAlchemy -> sintaxis de cast Postgres.
            # Los numéricos requieren cast porque la tabla stage los crea como text.
            NUMERIC_CASTS = {
                'integer':          'integer',
                'bigint':           'bigint',
                'smallint':         'smallint',
                'numeric':          'numeric',
                'real':             'real',
                'double_precision': 'double precision',
                'float':            'double precision',
            }

            def col_ref(col, alias):
                t = col_type_map.get(col, '')
                if t in ('json', 'jsonb', 'timestamp', 'timestamptz'):
                    return f"{alias}.{col}::{t}"
                if t in NUMERIC_CASTS:
                    return f"{alias}.{col}::{NUMERIC_CASTS[t]}"
                return f"{alias}.{col}"

            set_clause   = ", ".join(f"{col} = {col_ref(col, temporal_table_name)}" for col in set_cols)
            where_clause = " AND ".join(f"{table_name}.{k} = {temporal_table_name}.{k}" for k in keys)

            # Ejecutar la consulta de upsert en una sola transacción
            with self.engine.begin() as conn:

                try:
                    # Crear tabla temporal y cargar datos del DataFrame
                    self._write_dataframe(df, temporal_table_name, if_exists="replace", conn=conn)

                    # UPDATE: actualizar filas que ya existen en destino
                    if set_cols:
                        result_update = conn.execute(text(
                            f"UPDATE {table_name} "
                            f"SET {set_clause} "
                            f"FROM {temporal_table_name} "
                            f"WHERE {where_clause}"
                        ))
                        rows_updated = result_update.rowcount

                    # INSERT: insertar filas que no existen en destino
                    select_cols = ", ".join(col_ref(c, temporal_table_name) for c in df.columns)
                    result_insert = conn.execute(text(
                        f"INSERT INTO {table_name} ({', '.join(df.columns)}) "
                        f"SELECT {select_cols} "
                        f"FROM {temporal_table_name} "
                        f"WHERE NOT EXISTS ("
                        f"  SELECT 1 FROM {table_name} WHERE {where_clause}"
                        f")"
                    ))
                    rows_inserted = result_insert.rowcount

                finally:
                    conn.execute(text(f"DROP TABLE IF EXISTS {temporal_table_name}"))
                print(f"Upsert realizado correctamente en '{table_name}': {rows_updated} actualizados, {rows_inserted} insertados.")
            
    def get_dataframe(self, query: str) -> pd.DataFrame:
        """
        Read a dataframe from SQL. Uses engine for consistent dialect behavior.
        """
        if self.engine is None:
            raise RuntimeError("SQLAlchemy engine is not initialized.")

        return pd.read_sql_query(query, self.engine)
    
    def execute_query(self, query: str, params: dict | None = None):
        """
        Ejecuta INSERT/UPDATE/DELETE.
        Input: query (str): consulta SQL a ejecutar. Puede contener parámetros nombrados (e.g. :param_name) que serán reemplazados por los valores en params.
               params (dict): diccionario de parámetros nombrados a reemplazar en la consulta SQL.
        Output: Si el statement retorna filas (ej. RETURNING), devuelve el primer valor. Si no retorna filas, devuelve None.
        """
        if self.engine is None:
            raise RuntimeError("SQLAlchemy engine is not initialized.")

        with self.engine.begin() as conn:
            result = conn.execute(text(query), params or {})
            try:
                row = result.fetchone()
            except ResourceClosedError:
                return None
            return None if row is None else row[0]
        
    def get_count(self, table_name: str) -> int:
        """
        Retorna el conteo de filas de la tabla especificada.
        """
        if self.engine is None:
            raise RuntimeError("SQLAlchemy engine is not initialized.")
        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = result.scalar()
        return count
    
    @staticmethod
    def build_pg_engine(host: str, database: str, user: str, password: str, port: str):
        pwd = urllib.parse.quote_plus(password)
        url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{database}"
        return create_engine(url, pool_pre_ping=True)

        
class FoxtrackClient(SQLDatabaseConection):
    """
    Connect to FoxTrack database.
    """
    def __init__(self):
        self.engine = self.build_pg_engine(
            host=os.environ["DATABASE_FOXTRACK_HOST"],
            database=os.environ["DATABASE_FOXTRACK_NAME"],
            user=os.environ["DATABASE_FOXTRACK_USER"],
            password=os.environ["DATABASE_FOXTRACK_PASSWORD"],
            port=os.environ["DATABASE_FOXTRACK_PORT"],
        )

class DataAnalytics(SQLDatabaseConection):
    '''
    objective: Class used to connect to the Data Analytics database (that is used on DBeaber)
    '''
    def __init__(self):
        self.engine = self.build_pg_engine(
            host=os.environ["DATABASE_DATANALYTICS_HOST"],
            database=os.environ["DATABASE_DATANALYTICS_NAME"],
            user=os.environ["DATABASE_DATANALYTICS_USER"],
            password=os.environ["DATABASE_DATANALYTICS_PASSWORD"],
            port=os.environ["DATABASE_DATANALYTICS_PORT"],
        )

    def get_max_modified(self, table_name: str) -> pd.Timestamp | None:
        """
        Obtiene la última fecha de modificación (modified) de la tabla destino.
        Retorna un pd.Timestamp o None si la tabla no existe o no tiene datos.
        """
        try:
            max_modified = self.execute_query(f"SELECT max(modified) AS max_modified FROM foxtrack_{table_name}")
        except Exception as e:
            print(f"[ERROR] No se pudo obtener max modified de {table_name}: {e}")
            return None
    
        if max_modified is None:
            print(f"[INFO] La tabla foxtrack_{table_name} no existe o no tiene datos. Se considerará max_modified como NULL.")
            return None
        return max_modified
    
    def get_max_sk(self, table_name: str) -> int:
        """
        Obtiene el máximo valor de la SK (id) de la tabla destino.
        Retorna un entero o 0 si la tabla no existe o no tiene datos.
        """
        try:
            max_sk = self.execute_query(f"SELECT max(id) AS max_sk FROM foxtrack_{table_name}")
        except Exception as e:
            print(f"[ERROR] No se pudo obtener max SK de {table_name}: {e}")
            return 0
    
        if max_sk is None:
            print(f"[INFO] La tabla foxtrack_{table_name} no existe o no tiene datos. Se considerará max_sk como 0.")
            return 0
        return max_sk