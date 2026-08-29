pipeline {
    agent any

    options {
        timestamps()
    }

    environment {
        TOKEN_ACCESO_ASANA = credentials('TOKEN_ACCESO_ASANA')
        DATABASE_DATANALYTICS_PASSWORD = credentials('DATABASE_DATANALYTICS_PASSWORD')

        DATABASE_DATANALYTICS_NAME = "postgres"
        DATABASE_DATANALYTICS_USER = "postgres"
        DATABASE_DATANALYTICS_HOST = "host.docker.internal"
        DATABASE_DATANALYTICS_PORT = "5432"
    }

    stages {

        stage('Checkout') {
            steps {
                echo "Repositorio descargado correctamente."
            }
        }

        stage('Requirements') {
            steps {
                sh '''
                    python3 -m venv env
                    . env/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt
                '''
            }
        }
    }
}