pipeline {
    agent any

    options {
        timestamps()
    }

    stages {

        stage('Checkout') {
            steps {
                echo "Repositorio descargado correctamente."
                sh 'pwd'
                sh 'ls -la'
            }
        }

        stage('Python') {
            steps {
                sh 'python3 --version'
                sh 'pip3 --version'
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

        stage('Sales') {
            steps {
                sh '''
                    . env/bin/activate
                    python -m Data_Operations.script_asana_sales_task
                '''
            }
        }

        stage('Operations') {
            steps {
                sh '''
                    . env/bin/activate
                    python -m Data_Operations.script_asana_operations_task
                '''
            }
        }
    }
}