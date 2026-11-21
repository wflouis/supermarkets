"""PostgreSQL connection and helpers."""

import os

from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env") 

user = os.environ['DB_USER']
password = os.environ['DB_PASSWORD']
host = "127.0.0.1"
port = 5432
database = "supermarkets"

def get_connection():
    engine = create_engine(
        f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    )
    return engine

if __name__ == "__main__":

    try:
        engine = get_connection()
        print(f"Connection to the {host} for user {user} created successfully.")

    except Exception as ex:
        print("Connection could not be made due to the following error:\n", ex)

def execute_query(query, engine=None, **params):
    """Execute a SQL query and return the result as a pandas DataFrame."""
    engine = engine or get_connection()
    with engine.connect() as connection:
        return pd.read_sql(text(query), connection, params=params or None)

def run_schema(engine, sql_file=None):
    """Execute sql/schema.sql. Drops and recreates all tables."""
    sql_file = sql_file or PROJECT_ROOT / "sql" / "schema.sql"
    with engine.begin() as conn:
        conn.execute(text(sql_file.read_text(encoding="utf-8")))

def nan_to_none(df):
    """Replace NaN with None in text columns only; numeric dtypes stay numeric."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype) == "string":
            df[col] = df[col].where(df[col].notna(), None)
    return df