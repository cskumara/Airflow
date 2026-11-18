from datetime import datetime

from airflow.sdk import dag, task


@dag(
    dag_id="hello_airflow",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["example"],
)
def hello_airflow():

    @task
    def extract():
        data = {"name": "Airflow", "numbers": [1, 2, 3, 4, 5]}
        print(f"Extracted: {data}")
        return data

    @task
    def transform(data: dict):
        total = sum(data["numbers"])
        print(f"Sum of numbers: {total}")
        return {"name": data["name"], "total": total}

    @task
    def load(result: dict):
        print(f"Hello from {result['name']}! Total = {result['total']}")

    load(transform(extract()))


hello_airflow()