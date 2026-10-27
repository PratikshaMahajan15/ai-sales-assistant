import pandas as pd
from db import get_client


def execute(sql: str) -> pd.DataFrame:
    client = get_client()
    result = client.query(sql)
    return pd.DataFrame(result.result_rows, columns=result.column_names)


def preview(df: pd.DataFrame, max_rows: int = 10) -> str:
    return df.head(max_rows).to_string(index=False)
