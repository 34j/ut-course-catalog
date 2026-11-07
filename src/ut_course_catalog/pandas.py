from collections.abc import Iterable
from typing import NamedTuple

import pandas as pd


def to_series(item: NamedTuple) -> pd.Series:
    return pd.Series(item._asdict())


def to_dataframe(items: Iterable[NamedTuple]) -> pd.DataFrame:
    return pd.DataFrame([x._asdict() for x in items if x])
