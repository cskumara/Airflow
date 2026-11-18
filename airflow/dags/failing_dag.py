from datetime import datetime

from airflow.sdk import dag, task
from airflow_callback import notify_pipeline_doctor

@dag(
    dag_id="failing_dag",
    start_date=datetime(2026, 1, 1),
    schedule=None,          # only runs when you trigger it manually
    catchup=False,
    default_args={"retries": 0,"on_failure_callback": notify_pipeline_doctor},   # fail immediately, no retries
    tags=["example", "failure"],
)
def failing_dag():

    @task
    def start():
        print("This task succeeds.")
        return 10

    @task
    def divide(value: int):
        print(f"Trying to divide {value} by zero...")
        return value / 0     # raises ZeroDivisionError -> task fails

    @task
    def never_runs(result):
        print("You won't see this, because the task before it failed.")

    @task(trigger_rule="one_failed")
    def on_failure():
        print("Something upstream failed! Sending a pretend alert.")

    result = divide(start())
    never_runs(result)
    result >> on_failure()


failing_dag()