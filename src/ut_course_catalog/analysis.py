from __future__ import annotations

from enum import Enum, auto
from logging import getLogger
from typing import Any, Iterable

import pandas as pd
from PIL.Image import Image
from tqdm.auto import tqdm

from .ja import CommonCode

LOG = getLogger(__name__)


def create_wordcloud(
    txt: str, *, size: tuple[int, int] = (1200, 900), **kwargs: Any
) -> Image:
    from janome.tokenizer import Tokenizer
    from wordcloud import WordCloud

    t = Tokenizer()
    words = {}
    for token in tqdm(t.tokenize(txt), desc="Tokenizing"):
        data = str(token).split()[1].split(",")
        if data[0] == "名詞":
            key = data[6]
            if key not in words:
                words[key] = 1
            else:
                words[key] += 1

    font_path = "C:\\Windows\\Fonts\\msgothic.ttc"
    wordcloud = WordCloud(
        font_path=font_path, width=size[0], height=size[1], **kwargs
    ).generate_from_frequencies(words)
    return wordcloud.to_image()


class ScoringMethod(Enum):
    中間 = auto()
    期末 = auto()
    小テスト = auto()
    演習 = auto()
    課題 = auto()
    レポート = auto()
    発表 = auto()
    出席 = auto()


def _in_any(items: Iterable[str], text: str) -> bool:
    return any([item in text for item in items])


def parse_scoring_method(text: str | None) -> set[ScoringMethod]:
    d = {
        ScoringMethod.中間: ["中間", "mid"],
        ScoringMethod.期末: ["試験", "exam", "テスト", "最終試験", "追試", "Makeup"],
        ScoringMethod.小テスト: ["小テスト", "クイズ", "quiz"],
        ScoringMethod.演習: ["演習", "実習"],
        ScoringMethod.課題: ["課題", "assign", "宿題"],
        ScoringMethod.レポート: ["レポート", "レポ", "report"],
        ScoringMethod.発表: ["発表", "presenta", "プレゼン"],
        ScoringMethod.出席: [
            "出席",
            "発表",
            "参加",
            "attend",
            "平常",
            "出欠",
            "リアペ",
            "リアクション",
        ],
    }
    result: set[ScoringMethod] = set()
    if text is None:
        return result
    for k, v in d.items():
        if _in_any(v, text):
            result.add(k)
    if "期末" in text and not _in_any(["期末レポ", "期末課題"], text):
        result.add(ScoringMethod.期末)

    return result


def encode_scoring_method(texts: pd.Series[str]) -> pd.DataFrame:
    methods = texts.apply(lambda x: list(parse_scoring_method(x)))
    columns = []
    for method in ScoringMethod:
        column = methods.apply(lambda x: method in x)
        column.name = method.name
        columns.append(column)
    df = pd.concat(columns, axis=1)
    return df


def encode_common_code(common_codes: pd.Series[CommonCode]) -> pd.DataFrame:
    df = pd.DataFrame(common_codes.apply(lambda x: x._asdict() if x else {}).to_list())
    df.rename(columns={"講義使用言語": "講義使用言語_"}, inplace=True)
    return df


def to_perfect_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = pd.concat(
        [
            df,
            encode_scoring_method(df["成績評価方法"]),
            encode_common_code(df["共通科目コード"]),
        ],
        axis=1,
    )
    return df


def to_perfect_isolated_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = to_perfect_dataframe(df)

    # replace enum with its name
    def deenum(x: Any) -> Any:
        if isinstance(x, Enum):
            return x.name
        if isinstance(x, list):
            return [deenum(y) for y in x]
        if isinstance(x, dict):
            return {deenum(k): deenum(v) for k, v in x.items()}
        if isinstance(x, set):
            return {deenum(y) for y in x}
        if isinstance(x, tuple):
            return tuple(deenum(y) for y in x)
        return x

    df = df.applymap(deenum)
    return df
