# ## 1. Librerias
import asana
from asana.rest import ApiException
import requests
import pandas as pd
import json
import datetime
import os
from dotenv import load_dotenv
from Utils import constants
from Data_Operations.validation_engine import process_and_load
from Utils.databaseConections import DataAnalytics
from Utils.databaseConections import SQLDatabaseConection
load_dotenv() 


# ## 2. Connecting to the Asana API
# Token de acceso
configuration = asana.Configuration()
configuration.access_token = os.environ['TOKEN_ACCESO_ASANA']
# Crear cliente
api_client = asana.ApiClient(configuration)
# Verificar conexión
try:
    users_api = asana.UsersApi(api_client)
    me = users_api.get_user("me", {})  # :white_check_mark: Llamada correcta
    print('--'*20)
    print("✅ Conectado exitosamente. Usuario autenticado:", me["name"])  # :white_check_mark: Diccionario
    print('--'*20)  # :marca_de_verificación_blanca: Diccionario
except ApiException as e:
    print('--'*20)
    print("❌ Error al conectar con Asana API:", e)
    print('--'*20)


# ## 3. Configuration parameters for the project
# Calcular fecha límite con zona horaria UTC

# Creación instancia para API Class
tasks_api_instance = asana.TasksApi(api_client)
project_gid = constants.ASANA_OPERATIONS_PROJECT_ID


operations_task = [] #Lista vacia inicial
try:
    # Traer tareas del proyecto
    api_response = tasks_api_instance.get_tasks_for_project(project_gid, constants.OPTS)
    for data in api_response:
      operations_task.append(data)
    print('--'*20)    
    print("data cargada API: ", len(operations_task))
    print('--'*20)
except ApiException as e:
    print('--'*20)
    print("Exception when calling TasksApi->get_tasks_for_project: %s\n" % e)
    print('--'*20)

# ## 4. Extraction of required values
#Mapeo de los custom fields
gid_id = constants.ASANA_CUSTOM_FIELD_ID_ID
gid_restaurante = constants.ASANA_CUSTOM_FIELD_RESTAURANTE_ID
gid_prioridad = constants.ASANA_CUSTOM_FIELD_PRIORIDAD_ID
gid_tipo = constants.ASANA_CUSTOM_FIELD_TIPO_ID
gid_razon_perdida = constants.ASANA_CUSTOM_FIELD_RAZON_PERDIDA_ID


operations_task_clean = []  # Lista limpia para construir info final

for i in operations_task:
    # Construir el diccionario final de la tarea
    operations_task_clean.append({
        'gid': i['gid'],
        'resource_subtype': i['resource_subtype'],
        'name': i['name'],
        'project_id': next((m for m in i['memberships'] if m['project']['gid'] == project_gid), None)['project']['gid'],
        'project_name': next((m for m in i['memberships'] if m['project']['gid'] == project_gid), None)['project']['name'],
        'section_id': next((m for m in i['memberships'] if m['project']['gid'] == project_gid), None)['section']['gid'],
        'section_name': next((m for m in i['memberships'] if m['project']['gid'] == project_gid), None)['section']['name'],
        'created_at': i['created_at'],
        'assigne_id': i['assignee']['gid'] if i.get('assignee') else None,
        'assigne_name': i['assignee']['name'] if i.get('assignee') else None,
        'assigne_email': i['assignee']['email'] if i.get('assignee') else None,
        'id': next((field.get('display_value') for field in i.get('custom_fields', []) if field.get('gid') == gid_id), None),
        'restaurant': next((field.get('display_value') for field in i.get('custom_fields', []) if field.get('gid') == gid_restaurante), None),
        'priority': next((field.get('display_value') for field in i.get('custom_fields', []) if field.get('gid') == gid_prioridad), None),
        'type': next((field.get('display_value') for field in i.get('custom_fields', []) if field.get('gid') == gid_tipo), None),
        'lost_reason': next((field.get('display_value') for field in i.get('custom_fields', []) if field.get('gid') == gid_razon_perdida), None),
        'completed': i['completed'],
        'completed_at': i['completed_at'],
        'actual_time_minutes': i['actual_time_minutes'],
        'permalink_url': i['permalink_url'],
        'modified_at': i['modified_at'],
    })

# Crear DataFrame para visualización de tabla final
operations_task_df = pd.DataFrame(operations_task_clean)
print('--'*20)
print('longitud dataframe: ',len(operations_task_df ))
print('--'*20)
print(operations_task_df.head())


# ## 5. Data typing
## Tipado de datos
# Definir el tipo de dato correspodiente a cada columna
operations_task_df['gid'] = operations_task_df['gid'].astype(int)
operations_task_df['project_id'] = operations_task_df['project_id'].astype(int)
operations_task_df['section_id'] = operations_task_df['section_id'].fillna(0).astype(int)
operations_task_df['created_at'] = pd.to_datetime(operations_task_df['created_at'], utc=True)
operations_task_df['assigne_id'] = operations_task_df['assigne_id'].fillna(0).astype(int)
operations_task_df['completed_at'] = pd.to_datetime(operations_task_df['completed_at'], utc=True)
operations_task_df['actual_time_minutes'] = operations_task_df['actual_time_minutes'].fillna(0).astype(int)
operations_task_df['modified_at'] = pd.to_datetime(operations_task_df['modified_at'], utc=True)


## limpieza de datos
# Recorte de espacios en blanco
operations_task_df["name"] = operations_task_df["name"].str.strip()
operations_task_df["id"] = operations_task_df["id"].str.strip()
operations_task_df["restaurant"] = operations_task_df["restaurant"].str.strip()
# Poner en miniscula
operations_task_df["restaurant"] = operations_task_df["restaurant"].str.lower()

# Reorganizar las columnas
cols = ["gid","pipedrive_id","resource_subtype", "name", "project_id",
        "project_name", "section_id", "section_name", "created_at","assigne_id", "assigne_name","assigne_email",
        "id", "restaurant", "priority", "type","lost_reason",
        "completed", "completed_at","actual_time_minutes", "modified_at", "permalink_url"]
operations_task_df = operations_task_df[[c for c in cols if c in operations_task_df.columns]]

print('--'*20)
print('tipado de datos: ')
print('--'*20)
print(operations_task_df.dtypes)
print('--'*20)

'''
# ## 6. Filter tasks by date (last 7 days)
#Guardar la totalidad de los datos
all_data = billing_task_df

# Calcular fecha límite con zona horaria UTC
fecha_limite7 = pd.Timestamp(datetime.datetime.now() - datetime.timedelta(days=7), tz='UTC')

# Filtrar registros desde los últimos 7 días hacia adelante (hasta hoy)
billing_task_df = billing_task_df[billing_task_df['modified_at'] >= fecha_limite7]


# ## 7. Upload Historic Table
# Tabla 1: History
warehouse = DataAnalytics()
billing_task_df_history = warehouse.get_dataframe("""SELECT * FROM asana_billing_info_task""")

print('--'*20)
print('Data Historica: ',len(billing_task_df_history))
print('--'*20)

print(billing_task_df_history.dtypes)


# ## 8. Filtered past records
# Filtrar los registros de billing_task_df_history cuyo gid no está en billing_task_df
filtered_history = billing_task_df_history[~billing_task_df_history['gid'].isin(billing_task_df['gid'])]


# Mostrar resultado
print('--'*20)
print('Regisros que no cambiaron: ',len(filtered_history))
print('Registrados modificados los ultimos 7 días: ',len(billing_task_df))
print('--'*20)



# ## 9. Merge filtered and actual
# Usar concat para agregar las filas de los gids actualizados al DataFrame detail_task
billing_task_df = pd.concat([pd.DataFrame(filtered_history), billing_task_df], ignore_index=True)
print('--'*20)
print('Data definitiva: ',len(billing_task_df))
print('--'*20)


# ## 10. Verification tables
# Definir el tipo de dato correspodiente a cada columna
billing_task_df['gid'] = billing_task_df['gid'].astype(int)
billing_task_df['project_id'] = billing_task_df['project_id'].astype(int)
billing_task_df['pipedrive_id'] = billing_task_df['pipedrive_id'].astype(str)
billing_task_df['section_id'] = billing_task_df['section_id'].fillna(0).astype(int)
billing_task_df['created_at'] = pd.to_datetime(billing_task_df['created_at'], utc=True)
billing_task_df['assigne_id'] = billing_task_df['assigne_id'].fillna(0).astype(int)
billing_task_df['completed_at'] = pd.to_datetime(billing_task_df['completed_at'], utc=True)
billing_task_df['actual_time_minutes'] = billing_task_df['actual_time_minutes'].fillna(0).astype(int)
billing_task_df['uuid_foxtrack'] = billing_task_df['uuid_foxtrack'].replace([None, "None"], pd.NA).astype("string")
billing_task_df['modified_at'] = pd.to_datetime(billing_task_df['modified_at'], utc=True)

print('--'*20)
print(billing_task_df.dtypes)
print('--'*20)

# Mostrar la cantidad de filas en ambas tablas
billing_task_df_365 = billing_task_df[billing_task_df['modified_at'] >= fecha_limite]
print('--'*20)
print(f"Registro modificados desde el {fecha_limite} : {len(billing_task_df_365)}")
print('--'*20)

#Regla de validacion de insercion
if len(all_data) != len(billing_task_df_365):
    #Filtrar billing_task para quedarse solo con los 'gid' presentes en all_data y eliminar tareas eliminadas
    data_para_mantener= billing_task_df_365[billing_task_df_365['gid'].isin(all_data['gid'])]
    #registros eliminados 
    data_para_eliminar = billing_task_df_365[~billing_task_df_365['gid'].isin(all_data['gid'])]
    # Filtrar los registros de billing_task cuyo gid no está en billing_task
    billing_task_df = billing_task_df[~billing_task_df['gid'].isin(data_para_eliminar['gid'])]
    #data final a insetar luego de eliminar los registros eliminados 
    print('--'*20)
    print(f"✅ Longitud final de datos a insertar: {len(billing_task_df)}")
    print('--'*20)
else:
    if len(all_data) == len(billing_task_df_365):
        print('--'*20)
        print(f"✅ Longitud final de datos a insertar: {len(billing_task_df)}")
        print('--'*20)
    else:
        # Esto nunca debería ejecutarse; se deja como control de errores
        raise Exception(":x: Error inesperado en la validación de longitudes")

'''
# ## 11. Final Table
operations_task_df = operations_task_df.drop_duplicates().reset_index(drop=True)
print('--'*20)
print(f"Longitud operations_task_df a cargar: {len(operations_task_df)}")
print('--'*20)


# ## 12. Load
#warehouse = DataAnalytics()  
#warehouse.insert_dataframe(operations_task_df, 'asana_operations_task', 'replace')



warehouse = DataAnalytics()
report = process_and_load(
    source_name="asana_operations_task",
    df=operations_task_df,
    contract_name="asana_operations_task",
    warehouse=warehouse,
)
print(f"Estado: {report['overall_status']} | Health Score: {report['health_score']}")