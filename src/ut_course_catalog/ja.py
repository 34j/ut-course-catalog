from __future__ import annotations

import asyncio
import hashlib
import math
import pickle  # nosec
import re
from asyncio import create_task
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from inspect import isawaitable
from logging import Logger, getLogger
from pathlib import Path
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    NamedTuple,
    Optional,
    TypeVar,
    Union,
)

import aiofiles
import aiohttp
from aiohttp_client_cache import SQLiteBackend
from aiohttp_client_cache.session import CachedSession
from bs4 import BeautifulSoup, ResultSet, Tag
from pandas import DataFrame
from tenacity import WrappedFn, retry
from tenacity.before_sleep import before_sleep_log
from tenacity.stop import stop_after_attempt, stop_after_delay
from tenacity.wait import wait_exponential
from tqdm import tqdm
from typing_extensions import Self

from ut_course_catalog.common import BASE_URL, Semester, Weekday

from .common import Language, RateLimitter


def current_fiscal_year() -> int:
    """Returns current fiscal year"""
    now = datetime.now()
    return now.year if now.month >= 4 else now.year - 1


class Institution(Enum):
    """Institution in the University of Tokyo."""

    学部前期課程 = "jd"
    """Junior Division"""
    学部後期課程 = "ug"
    """Senior Division"""
    大学院 = "g"
    """Graduate"""
    All = "all"


class Faculty(Enum):
    """Faculty in the University of Tokyo."""

    法学部 = 1
    医学部 = 2
    工学部 = 3
    文学部 = 4
    理学部 = 5
    農学部 = 6
    経済学部 = 7
    教養学部 = 8
    教育学部 = 9
    薬学部 = 10
    人文社会系研究科 = 11
    教育学研究科 = 12
    法学政治学研究科 = 13
    経済学研究科 = 14
    総合文化研究科 = 15
    理学系研究科 = 16
    工学系研究科 = 17
    農学生命科学研究科 = 18
    医学系研究科 = 19
    薬学系研究科 = 20
    数理科学研究科 = 21
    新領域創成科学研究科 = 22
    情報理工学系研究科 = 23
    学際情報学府 = 24
    公共政策学教育部 = 25
    教養学部前期課程 = 26

    @classmethod
    def value_of(cls, value: str) -> Faculty:
        """Converts a commonly used expression in the website to a Faculty enum value."""
        for k, v in cls.__members__.items():
            if k == value:
                return v
        if value == "教養学部（前期課程）":
            return cls.教養学部前期課程
        else:
            raise ValueError(f"'{cls.__name__}' enum not found for '{value}'")


class ClassForm(Enum):
    講義 = "L"
    演習 = "S"
    実験 = "E"
    実習 = "P"
    卒業論文 = "T"
    その他 = "Z"


class CommonCode(str):
    @property
    def institution(self) -> Institution | None:
        try:
            return {
                "C": Institution.学部前期課程,
                "F": Institution.学部後期課程,
                "G": Institution.大学院,
            }[self[0]]
        except IndexError:
            return None

    @property
    def faculty(self) -> Faculty:
        code = self[1:3]
        g_faculties = {
            "HS": Faculty.人文社会系研究科,
            "LP": Faculty.法学政治学研究科,
            "AS": Faculty.総合文化研究科,
            "SC": Faculty.理学系研究科,
            "EN": Faculty.工学系研究科,
            "AG": Faculty.農学生命科学研究科,
            "ME": Faculty.医学系研究科,
            "PH": Faculty.薬学系研究科,
            "MA": Faculty.数理科学研究科,
            "FS": Faculty.新領域創成科学研究科,
            "IF": Faculty.情報理工学系研究科,
            "II": Faculty.学際情報学府,
            "PP": Faculty.公共政策学教育部,
        }
        ug_faculties = {
            "LA": Faculty.法学部,
            "ME": Faculty.医学部,
            "EN": Faculty.工学部,
            "LE": Faculty.文学部,
            "SC": Faculty.理学部,
            "AG": Faculty.農学部,
            "EC": Faculty.経済学部,
            "AS": Faculty.教養学部,
            "ED": Faculty.教育学部,
            "PH": Faculty.薬学部,
        }
        if self.institution == Institution.学部前期課程:
            if code == "AS":
                return Faculty.教養学部前期課程
        if self.institution == Institution.大学院:
            if code in g_faculties:
                return g_faculties[code]
            if code in ug_faculties:
                return ug_faculties[code]
        else:
            if code in ug_faculties:
                return ug_faculties[code]
            if code in g_faculties:
                return g_faculties[code]
        raise RuntimeWarning(f"Unknown faculty code: {code}")

    @property
    def department_code(self) -> str | None:
        try:
            return self[4:6]
        except IndexError:
            return None

    @property
    def level(self) -> str | None:
        try:
            return self[6]
        except IndexError:
            return None

    @property
    def reference_number(self) -> str | None:
        try:
            return self[7:10]
        except IndexError:
            return None

    @property
    def class_form(self) -> ClassForm | None:
        try:
            return {
                "L": ClassForm.講義,
                "S": ClassForm.演習,
                "E": ClassForm.実験,
                "P": ClassForm.実習,
                "T": ClassForm.卒業論文,
                "Z": ClassForm.その他,
            }[self[10]]
        except IndexError:
            return None

    @property
    def language(self) -> Language | None:
        try:
            return {
                1: Language.Japanese,
                2: Language.JapaneseAndEnglish,
                3: Language.English,
                4: Language.OtherLanguagesToo,
                5: Language.OnlyOtherLanguages,
                9: Language.Others,
            }[int(self[11])]
        except IndexError:
            return None

    @property
    def department_name(self) -> str:
        return CommonCode.parse_department(self.faculty, self.department_code)

    @property
    def small_category(self) -> str | None:
        if self.reference_number:
            return self.reference_number[1:3]

    @property
    def middle_category(self) -> str | None:
        if self.reference_number:
            return self.reference_number[0]

    @property
    def large_category(self) -> str | None:
        return self.department_code

    def _asdict(self) -> dict[str, Any]:
        return {
            "課程": self.institution,
            "学部": self.faculty,
            "学科": self.department_name,
            "学科コード": self.department_code,
            "レベル": self.level,
            "整理番号": self.reference_number,
            "授業形態": self.class_form,
            "講義使用言語": self.language,
            "小分類": self.small_category,
            "中分類": self.middle_category,
            "大分類": self.large_category,
        }

    def _asdict_en(self) -> dict[str, Any]:
        return {
            "institution": self.institution,
            "faculty": self.faculty,
            "department_code": self.department_code,
            "level": self.level,
            "reference_number": self.reference_number,
            "class_form": self.class_form,
            "language": self.language,
            "department_name": self.department_name,
            "large_category": self.large_category,
            "middle_category": self.middle_category,
            "small_category": self.small_category,
        }

    @staticmethod
    def parse_department(
        faculty: Faculty, department_code: str
    ) -> dict[Faculty, dict[str, str]]:
        d = {
            Faculty.教養学部前期課程: {
                "FC": "基礎科目",
                "IC": "展開科目",
                "GC": "総合科目",
                "TC": "主題科目",
                "PF": "基礎科目(PEAK)",
                "PI": "展開科目(PEAK)",
                "PG": "総合科目(PEAK)",
                "PT": "主題科目(PEAK)",
            },
            Faculty.法学部: {
                "CO": "共通科目",
                "PL": "実定法系科目",
                "BL": "基礎法学系科目",
                "PS": "政治系科目",
                "EC": "経済系科目",
                "SE": "演習科目",
            },
            Faculty.医学部: {"ME": "医学科", "IE": "健康総合科学科"},
            Faculty.工学部: {
                "CO": "共通科目",
                "JL": "日本語教育部門",
                "CE": "社会基盤学科",
                "AR": "建築学科",
                "UE": "都市工学科",
                "MX": "機械系",
                "ME": "機械工学科",
                "MI": "機械情報工学科",
                "AA": "航空宇宙工学科",
                "PE": "精密工学科",
                "EE": "電子・情報系",
                "AM": "応用物理系",
                "AP": "物理工学科",
                "MP": "計数工学科",
                "MA": "マテリアル工学科",
                "CH": "化学・生命系",
                "CA": "応用化学科",
                "CS": "化学システム工学科",
                "CB": "化学生命工学科",
                "SI": "システム創成学科",
                "SA": "環境・エネルギーシステムコース",
                "SB": "システムデザイン＆マネジメントコース",
                "SC": "知能社会システムコース",
            },
            Faculty.文学部: {
                "HU": "人文学科",
                "XX": "専修課程以外",
            },
            Faculty.理学部: {
                "MA": "数学科",
                "IS": "情報科学科",
                "PH": "物理学科",
                "AS": "天文学科",
                "EP": "地球惑星物理学科",
                "EE": "地球惑星環境学科",
                "CH": "化学科",
                "BC": "生物化学科",
                "BS": "生物学科",
                "BI": "生物情報科学科",
                "CC": "理学部共通科目",
            },
            Faculty.農学部: {
                "MC": "生命化学・工学専修",
                "MB": "応用生物学専修",
                "MF": "森林生物科学専修/森林環境資源科学専修",
                "MQ": "水圏生物科学専修",
                "MA": "動物生命システム科学専修",
                "MM": "生物素材科学専修",
                "ML": "緑地環境学専修",
                "MW": "木質構造科学専修",
                "MG": "生物・環境工学専修",
                "ME": "農業・資源経済学専修",
                "MS": "フィールド科学専修",
                "MI": "国際開発農学専修",
                "MV": "獣医学専修",
                "CC": "共通",
                "CL": "応用生命科学課程",
                "CE": "環境資源学課程",
                "CV": "獣医学専修",
            },
            Faculty.経済学部: {
                "EC": "経済学",
                "ST": "統計学",
                "AS": "地域研究",
                "EH": "経済史",
                "MA": "経営学",
                "QF": "数量ファイナンス",
                "WW": "その他",
            },
            Faculty.教養学部: {
                "AA": "言語共通科目",
                "BA": "言語専門科目",
                "CA": "教養学科",
                "DA": "学際科学科",
                "EA": "統合自然科学科",
                "FA": "学融合プログラム",
                "GA": "教職科目",
                "HA": "特設科目",
                "XA": "高度教養科目",
            },
            Faculty.教育学部: {
                "IE": "総合教育科学科",
                "BT": "基礎教育学コース",
                "SS": "教育社会科学専修",
                "SO": "比較教育社会学コース",
                "PP": "教育実践・政策学コース",
                "DS": "心身発達科学専修",
                "EP": "教育心理学コース",
                "PH": "身体教育学コース",
            },
            Faculty.薬学部: {
                "SH": "薬科学科／薬学科",
                "PS": "薬科学科",
                "PH": "薬学科",
            },
            Faculty.理学系研究科: {
                "PH": "物理学専攻",
                "AS": "天文学専攻",
                "EP": "地球惑星科学専攻",
                "EE": "地球惑星環境学科",
                "CH": "化学専攻",
                "BC": "生物化学科",
                "BS": "生物科学専攻",
                "BI": "生物情報科学科",
                "CC": "理学部共通科目",
            },
            Faculty.教育学研究科: {
                "IE": "総合教育科学専攻",
                "AS": "学校教育高度化専攻",
                "ZZ": "その他",
            },
            Faculty.人文社会系研究科: {
                "GC": "基礎文化研究専攻",
                "JS": "日本文化研究専攻",
                "EA": "欧米系文化研究専攻",
                "AS": "アジア文化研究専攻",
                "SC": "社会文化研究専攻",
                "CR": "文化資源学研究専攻",
                "KS": "韓国朝鮮文化研究専攻",
                "XX": "共通科目",
            },
            Faculty.法学政治学研究科: {
                "LP": "総合法政専攻",
                "LS": "法曹養成専攻",
            },
            Faculty.経済学研究科: {
                "EC": "経済学研究科",
            },
            Faculty.総合文化研究科: {
                "LI": "言語情報科学専攻",
                "IC": "超域文化科学専攻",
                "AS": "地域文化研究専攻",
                "SI": "国際社会科学専攻",
                "LS": "広域科学専攻 生命環境科学系",
                "SS": "広域科学専攻 広域システム科学系",
                "BS": "広域科学専攻 相関基礎科学系",
                "HS": "「人間の安全保障」プログラム",
                "EU": "欧州研究プログラム",
                "GH": "グローバル共生プログラム",
                "IH": "多文化共生・統合人間学プログラム",
                "GS": "国際人材養成プログラム",
                "ES": "国際環境学プログラム",
                "GW": "グローバル・スタディーズ・イニシアティヴ国際卓越大学院",
                "WA": "先進基礎科学推進国際卓越大学院",
                "IT": "科学技術インタープリター養成プログラム",
                "IG": "日独共同大学院プログラム",
                "EE": "英語教育プログラム",
            },
            Faculty.工学系研究科: {"": ""},
            Faculty.農学生命科学研究科: {
                "CC": "共通",
                "AB": "生産・環境生物学",
                "AC": "応用生命化学",
                "BT": "応用生命工学",
                "FS": "森林科学",
                "AQ": "水圏生物科学",
                "AE": "農業・資源経済学",
                "BE": "生物・環境工学",
                "BM": "生物材料科学",
                "WA": "生物材料科学・木造建築コース",
                "GA": "農学国際",
                "IP": "農学国際・国際農業開発学コース",
                "ES": "生圏システム学",
                "AS": "応用動物科学",
                "VM": "獣医学",
                "MS": "副専攻",
            },
            Faculty.医学系研究科: {
                "MC": "分子細胞生物学",
                "FB": "機能生物学",
                "PA": "病因・病理学",
                "RB": "生体物理医学",
                "NS": "脳神経医学",
                "SM": "社会医学",
                "IM": "内科学",
                "RE": "生殖・発達・加齢医学",
                "SS": "外科学",
                "HN": "健康科学・看護学",
                "PN": "健康科学・看護学 保健師コース",
                "NU": "健康科学・看護学 専門看護師コース",
                "PE": "健康科学・看護学 保健師教育コース",
                "MW": "健康科学・看護学 助産師教育コース",
                "IH": "国際保健学",
                "MH": "医科学",
                "PH": "公共健康医学",
                "ML": "医学共通科目",
                "GP": "医学共通科目（がんプロフェショナル養成プラン）",
                "PL": "GPLLI（リーディング大学院）",
                "LS": "生命科学技術国際卓越大学院（ライフサイエンスコース）",
                "BE": "生命科学技術国際卓越大学院（生体医工学コース）",
            },
            Faculty.薬学系研究科: {
                "SH": "薬科学専攻／薬学専攻",
                "PS": "薬科学専攻",
                "PH": "薬学専攻",
                "WL": "生命科学技術国際卓越大学院 WINGS-LST",
            },
            Faculty.数理科学研究科: {"MA": "数理科学研究科"},
            Faculty.情報理工学系研究科: {
                "CS": "コンピュータ科学",
                "MA": "数理情報学",
                "IP": "システム情報学",
                "IC": "電子情報学",
                "MX": "知能機械情報学",
                "CI": "創造情報学",
                "CO": "共通科目",
            },
            Faculty.新領域創成科学研究科: {
                "OC": "全学開放科目",
                "CC": "新領域創成科学研究科共通科目",
                "EC": "環境学研究系共通科目",
                "AM": "物質系専攻",
                "AE": "先端エネルギー工学専攻",
                "CS": "複雑理工学専攻",
                "IB": "先端生命科学専攻",
                "MJ": "メディカル情報生命専攻",
                "NE": "自然環境学専攻",
                "OT": "海洋技術環境学専攻",
                "ES": "環境システム学専攻",
                "HE": "人間環境学専攻",
                "SC": "社会文化環境学専攻",
                "IS": "国際協力学専攻",
                "SS": "サステイナビリティ学グローバルリーダー養成大学院プログラム",
            },
            Faculty.学際情報学府: {
                "SC": "社会情報学コース",
                "CH": "文化・人間情報学コース",
                "ED": "先端表現情報学コース",
                "AC": "総合分析情報学コース",
                "IA": "アジア情報社会コース",
                "BS": "生物統計情報学コース",
                "RS": "学際情報学専攻（必修）",
                "CS": "学際情報学専攻（共通）",
                "WS": "学際情報学専攻（横断）",
            },
            Faculty.公共政策学教育部: {
                "DP": "国際公共政策学専攻",
                "MP": "公共政策学専攻",
            },
        }
        return d[faculty].get(department_code, department_code)


class SearchResultItem(NamedTuple):
    """Summary of a course in search results. Call `fetch_details` to get more information."""

    時間割コード: str
    共通科目コード: CommonCode
    コース名: str
    教員: str
    学期: set[Semester]
    曜限: set[tuple[Weekday, int]]
    ねらい: str


class SearchResult(NamedTuple):
    """Result of a search query."""

    items: list[SearchResultItem]
    current_items_first_index: int
    current_items_last_index: int
    current_items_count: int
    total_items_count: int
    current_page: int
    total_pages: int


class Details(NamedTuple):
    """Details of a course. Contains all available information for a course on the website.
    (UTAS may have more information)"""

    時間割コード: str
    共通科目コード: CommonCode
    コース名: str
    教員: str
    学期: set[Semester]
    曜限: set[tuple[Weekday, int]]
    ねらい: str
    教室: str
    単位数: Decimal
    他学部履修可: bool
    講義使用言語: str
    実務経験のある教員による授業科目: bool
    開講所属: Faculty
    授業計画: str | None
    授業の方法: str | None
    成績評価方法: str | None
    教科書: str | None
    参考書: str | None
    履修上の注意: str | None


T = TypeVar("T")
IterableOrType = Union[Iterable[T], T]
OptionalIterableOrType = Optional[IterableOrType[T]]


@dataclass
class SearchParams:
    """Search query parameters."""

    keyword: str | None = None
    課程: Institution = Institution.All
    開講所属: Faculty | None = None
    学年: OptionalIterableOrType[int] = None
    """AND search, not OR."""
    学期: OptionalIterableOrType[Semester] = None
    """AND search, not OR."""
    曜日: OptionalIterableOrType[Weekday] = None
    """AND search, not OR. Few courses have multiple periods."""
    時限: OptionalIterableOrType[int] = None
    """AND search, not OR. Few courses have multiple periods."""
    講義使用言語: OptionalIterableOrType[str] = None
    """AND search, not OR."""
    横断型教育プログラム: OptionalIterableOrType[str] = None
    """AND search, not OR."""
    実務経験のある教員による授業科目: OptionalIterableOrType[bool] = None
    """AND search, not OR. Do not specify [True, False] though it is valid."""
    分野_NDC: OptionalIterableOrType[str] = None
    """AND search, not OR."""

    def id(self) -> str:
        return hashlib.sha256(str(self).encode()).hexdigest()


def _format(text: str) -> str:
    """Utility function for removing unnecessary whitespaces."""
    table = str.maketrans("　", " ", " \n\r\t")
    return text.translate(table)


def _format_description(text: str) -> str:
    # delete spaces at first and last
    text = re.sub(r"^\s+", "", text)
    text = re.sub(r"\s+$", "", text)
    # table = str.maketrans("", "", "\r\n\t")
    # text = text.translate(table)
    return text


def _ensure_found(obj: object) -> Tag:
    if type(obj) is not Tag:
        raise ParserError(f"{obj} not found")
    return obj


def _parse_weekday_period(period_text: str) -> set[tuple[Weekday, int]]:
    period_text = _format(period_text)
    # if period_text == "集中":
    # Most complex case:"S1: 集中、A1: 月曜3限 他"
    if ":" in period_text:
        return set()
    # Ignore others if period_text contains "集中"
    if "集中" in period_text:
        return set()
    period_texts = period_text.split("、")

    def parse_one(period: str) -> tuple[Weekday, int] | None:
        w = Weekday([weekday in period for weekday in list("月火水木金土日")].index(True))
        reres = re.search(r"\d+", period)
        if not reres:
            # raise ValueError(f"Invalid period: {period}")
            return None
        p = int(reres.group())
        return w, p

    result = set()
    for item in period_texts:
        if not item:
            return set()
        result.add(parse_one(item))
    return result


async def _await_if_future(obj: object) -> object:
    if isawaitable(obj):
        return await obj
    return obj


class ParserError(Exception):
    pass


class UTCourseCatalog:
    """A parser for the [UTokyo Online Course Catalogue](https://catalog.he.u-tokyo.ac.jp)."""

    session: aiohttp.ClientSession | None
    _logger: Logger
    _rate_limitter: RateLimitter

    def __init__(
        self,
        logger_level: int = 0,
        min_interval: timedelta | int = 1,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.session = session
        self._logger = getLogger(__name__)
        self._logger.setLevel(logger_level)
        self._rate_limitter = RateLimitter(min_interval=min_interval)

    async def __aenter__(self) -> Self:
        if self.session is None:
            self.session = CachedSession(
                cache=SQLiteBackend(
                    cache_name="~/.cache/ut_course_catalog/cache.sqlite"
                ),
                logger=self._logger,
            )
        await self.session.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self._check_client()
        if self.session is None:
            raise RuntimeError("__aenter__ not called")

        await self.session.__aexit__(*args)

    def _check_client(self) -> None:
        if not self.session:
            raise RuntimeError("__aenter__ not called")

    async def fetch_search(self, params: SearchParams, page: int = 1) -> SearchResult:
        """Fetch search results from the website.

        Parameters
        ----------
        params : SearchParams
            Search parameters.
        page : int, optional
            page number, by default 1

        Returns
        -------
        SearchResult
            Search results.

        Raises
        ------
        ParserError
            Raises when failed to parse the website.
        """
        self._check_client()
        if self.session is None:
            raise RuntimeError("__aenter__ not called")
        # See: https://github.com/34j/ut-course-catalog-swagger/blob/master/swagger.yaml

        # build query
        _params = {
            "type": params.課程.value,
            "page": page,
        }
        if params.keyword:
            _params["q"] = params.keyword
        if params.開講所属:
            _params["faculty_id"] = params.開講所属.value

        def iterable_or_type_to_iterable(
            x: IterableOrType[T],
        ) -> Iterable[T]:
            if isinstance(x, Iterable):
                return x
            return [x]

        # build facet query
        facet: dict[str, Any] = {}
        if params.横断型教育プログラム:
            facet["uwide_cross_program_codes"] = iterable_or_type_to_iterable(
                params.横断型教育プログラム
            )
        if params.学年:
            facet["grades_codes"] = iterable_or_type_to_iterable(params.学年)
        if params.学期:
            facet["semester_codes"] = [
                s.value for s in iterable_or_type_to_iterable(params.学期)
            ]
        if params.時限:
            facet["period_codes"] = [
                x - 1 for x in iterable_or_type_to_iterable(params.時限)
            ]
        if params.曜日 is not None:
            facet["wday_codes"] = [
                x.value * 100 + 1000 for x in iterable_or_type_to_iterable(params.曜日)
            ]
        if params.講義使用言語:
            facet["course_language_codes"] = iterable_or_type_to_iterable(params.講義使用言語)
        if params.実務経験のある教員による授業科目:
            facet["operational_experience_flag"] = iterable_or_type_to_iterable(
                params.実務経験のある教員による授業科目
            )
        if params.分野_NDC:
            # subject_code is not typo, it is a typo in the API
            facet["subject_code"] = iterable_or_type_to_iterable(params.分野_NDC)
        facet = {k: [str(x) for x in v] for k, v in facet.items()}
        if facet:
            _params["facet"] = str(facet).replace("'", '"').replace(" ", "")

        # fetch website
        await self._rate_limitter.wait()
        async with self.session.get(BASE_URL + "result", params=_params) as response:
            # parse website
            soup = BeautifulSoup(await response.text(), "html.parser")

            # get page info first
            page_info_element = soup.find(class_="catalog-total-search-result")
            if not page_info_element:
                # not found
                return SearchResult(
                    items=[],
                    current_items_count=0,
                    total_items_count=0,
                    current_items_first_index=0,
                    current_items_last_index=0,
                    current_page=0,
                    total_pages=0,
                )

            page_info_text = _format(page_info_element.text)
            page_info_match: list[str] = re.findall(r"\d+", page_info_text)
            current_items_first_index = int(page_info_match[0])
            current_items_last_index = int(page_info_match[1])
            current_items_count = (
                current_items_last_index - current_items_first_index + 1
            )
            total_items_count = int(page_info_match[2])
            total_pages = math.ceil(total_items_count / 10)

            def get_items() -> Iterable[SearchResultItem]:
                """Get search result items."""
                container = soup.find(
                    "div", class_="catalog-search-result-card-container"
                )
                if container is None:
                    return
                if type(container) is not Tag:
                    raise ParserError(f"container not found: {container}")
                cards = container.find_all("div", class_="catalog-search-result-card")
                for card in cards:
                    cells_parent: Tag = card.find_all(
                        class_="catalog-search-result-table-row"
                    )[1]
                    if not cells_parent:
                        continue

                    def get_cell(name: str) -> Tag:
                        cell = cells_parent.find("div", class_=f"{name}-cell")
                        if type(cell) is not Tag:
                            raise ParserError(f"cell not found: {name}")
                        return cell

                    def get_cell_text(name: str) -> str:
                        cell = get_cell(name)
                        return _format(cell.text)

                    code_cell = _ensure_found(cells_parent.find(class_="code-cell"))
                    code_cell_children = list(code_cell.children)
                    yield SearchResultItem(
                        ねらい=_format_description(
                            card.find(
                                class_="catalog-search-result-card-body-text"
                            ).text
                        ),
                        時間割コード=code_cell_children[1].text,
                        共通科目コード=CommonCode(code_cell_children[3].text),
                        コース名=get_cell_text("name"),
                        教員=get_cell_text("lecturer"),
                        学期={
                            Semester(el.text.replace(" ", "").replace("\n", ""))
                            for el in get_cell("semester").find_all(
                                class_="catalog-semester-icon"
                            )
                        },
                        曜限=set(_parse_weekday_period(get_cell_text("period"))),
                    )

            items = list(get_items())
            if page != total_pages:
                if len(items) != 10:
                    raise ParserError("items count is not 10")
                if len(items) != current_items_count:
                    raise ParserError("items count is not current_items_count")
            if page != current_items_first_index // 10 + 1:
                raise ParserError("page number is not correct")

            return SearchResult(
                items=list(get_items()),
                total_items_count=total_items_count,
                current_items_first_index=current_items_first_index,
                current_items_last_index=current_items_last_index,
                current_items_count=current_items_count,
                total_pages=total_pages,
                current_page=page,
            )

    async def fetch_detail(
        self, code: str, year: int = current_fiscal_year()
    ) -> Details:
        """Fetch details of a course.

        Parameters
        ----------
        code : str
            Course (common) code.
        year : int, optional
            Year of the course, by default current_fiscal_year().

        Returns
        -------
        Details
            Details of the course.

        Raises
        ------
        ParserError
            Raises when the parser fails to parse the website.
        """
        self._check_client()
        if self.session is None:
            raise RuntimeError("__aenter__ not called")

        await self._rate_limitter.wait()
        async with self.session.get(
            BASE_URL + "detail", params={"code": code, "year": str(year)}
        ) as response:
            """
            We get information from 3 different types of elements:
                cells 1: cells in the smallest table in the page.
                cells 2: cells in the first card.
                cards: cards.
            """

            # parse html
            soup = BeautifulSoup(await response.text(), "html.parser")

            # utility functions to get elements and their text
            cells1_parent: Tag = soup.find_all(class_="catalog-row")[1]

            def get_cell1(name: str) -> str:
                class_ = f"{name}-cell"
                cell = cells1_parent.find("div", class_=class_)
                if not cell:
                    raise ParserError(f"Cell {name} not found")
                return _format(cell.text)

            def get_cell2(index: int) -> str:
                class_ = f"td{index // 3 + 1}-cell"
                return _format(soup.find_all(class_=class_)[index % 3].text)

            def get_cards():
                cards: ResultSet[Tag] = soup.find_all(class_="catalog-page-detail-card")
                for card in cards:
                    card_header = card.find(class_="catalog-page-detail-card-header")
                    if not card_header:
                        raise ParserError("Card header not found")
                    title = _format(card_header.text)
                    card_body = card.find(class_="catalog-page-detail-card-body-pre")
                    if not card_body:
                        raise ParserError("card_body not found")
                    if type(card_body) is not Tag:
                        raise ParserError("card_body is not Tag")
                    yield title, card_body

            cards = dict(get_cards())

            def get_card(name: str) -> Tag | None:
                return cards.get(name, None)

            def get_card_text(name: str) -> str | None:
                card = get_card(name)
                if card:
                    return _format_description(card.text)
                return None

            code_cell = _ensure_found(cells1_parent.find(class_="code-cell"))
            code_cell_children = list(code_cell.children)

            # return the result
            return Details(
                時間割コード=code_cell_children[1].text,
                共通科目コード=CommonCode(code_cell_children[3].text),
                コース名=get_cell1("name"),
                教員=get_cell1("lecturer"),
                学期={
                    Semester(el.text.replace(" ", "").replace("\n", ""))
                    for el in cells1_parent.find_all(class_="catalog-semester-icon")
                },
                曜限=_parse_weekday_period(get_cell1("period")),
                教室="N/A",  # get_cell2(0),
                単位数=Decimal(get_cell2(3)),
                他学部履修可="不可" not in get_cell2(4),
                講義使用言語=get_cell2(0),
                実務経験のある教員による授業科目="YES" in get_cell2(1),
                開講所属=Faculty.value_of(get_cell2(2)),
                授業計画=get_card_text("授業計画"),
                授業の方法=get_card_text("授業の方法"),
                成績評価方法=get_card_text("成績評価方法"),
                教科書=get_card_text("教科書"),
                参考書=get_card_text("参考書"),
                履修上の注意=get_card_text("履修上の注意"),
                ねらい=_format(
                    _ensure_found(
                        soup.find(class_="catalog-page-detail-lecture-aim")
                    ).text
                ),
            )

    async def fetch_common_code(self, 時間割コード: str) -> CommonCode:
        """Fetch common code of a course from its time table code.

        Returns
        -------
        CommonCode
            Common code of the course
        """
        result = await self.fetch_search(SearchParams(keyword=時間割コード))
        return result.items[0].共通科目コード

    async def fetch_code(self, 共通科目コード: str) -> str:
        """Fetch time table code of a course from its common code.

        Returns
        -------
        str
            Time table code of the course
        """
        result = await self.fetch_search(SearchParams(keyword=共通科目コード))
        return result.items[0].時間割コード

    def retry(self, func: WrappedFn) -> WrappedFn:
        return retry(
            stop=(stop_after_delay(10) | stop_after_attempt(3)),
            wait=wait_exponential(multiplier=1, min=4, max=16),
            before_sleep=before_sleep_log(self._logger, 30),
        )(func)

    async def fetch_search_all(
        self,
        params: SearchParams,
        *,
        use_tqdm: bool = True,
        on_initial_request: None | (Callable[[SearchResult], Awaitable | None]) = None,
    ) -> AsyncIterable[SearchResultItem]:
        """Fetch all search results by repeatedly calling `fetch_search`.

        Parameters
        ----------
        params : SearchParams
            Search parameters
        use_tqdm : bool, optional
            Whether to use tqdm, by default True
        on_initial_request : Optional[Callable[[SearchResult], Optional[Awaitable]]], optional
            Callback function to be called on the initial request, by default None

        Returns
        -------
        AsyncIterable[SearchResultItem]
            Async iterable of search results

        Yields
        ------
        Iterator[AsyncIterable[SearchResultItem]]
            Async iterable of search results
        """
        pbar = tqdm(disable=not use_tqdm)
        result = await self.fetch_search(params)
        pbar.update()

        if on_initial_request:
            await _await_if_future(on_initial_request(result))

        for item in result.items:
            yield item

        pbar.total = result.total_pages
        tasks = []
        for page in range(2, result.total_pages + 1):

            async def inner(page):
                try:
                    search = await self.retry(self.fetch_search)(params, page)
                except Exception as e:
                    self._logger.exception(e)
                    self._logger.error(f"Failed to fetch page {page}")
                    return None
                pbar.update(1)
                return search

            result_task = create_task(inner(page))
            tasks.append(result_task)
        results = await asyncio.gather(*tasks)
        for result in results:
            if result:
                for item in result.items:
                    yield item

    async def fetch_search_detail_all(
        self,
        params: SearchParams,
        *,
        year: int = current_fiscal_year(),
        use_tqdm: bool = True,
        on_initial_request: None
        | (Callable[[SearchResult], Awaitable[None] | None]) = None,
        on_detail_request: Callable[[Details], Awaitable[None] | None] | None = None,
    ) -> Iterable[Details]:
        """Fetch all search results by repeatedly calling `fetch_search` and `fetch_detail`.

        Parameters
        ----------
        params : SearchParams
            Search parameters
        year : int, optional
            Year of the course, by default current_fiscal_year()
        use_tqdm : bool, optional
            Whether to use tqdm, by default True
        on_initial_request : Optional[Callable[[SearchResult], Optional[Awaitable]]], optional
            Callback function to be called on the initial request, by default None

        Returns
        -------
        AsyncIterable[Details]
            Async iterable of details

        Yields
        ------
        Iterator[AsyncIterable[Details]]
            Async iterable of details
        """

        pbar = tqdm(disable=not use_tqdm)

        async def on_initial_request_wrapper(search_result: SearchResult):
            pbar.total = search_result.total_items_count
            if on_initial_request:
                await _await_if_future(on_initial_request(search_result))

        tasks = []
        items = [
            item
            async for item in self.fetch_search_all(
                params,
                use_tqdm=True,
                on_initial_request=on_initial_request_wrapper,
            )
        ]
        s = asyncio.Semaphore(100)
        for item in items:

            async def inner(item):
                async with s:
                    try:
                        details = await self.retry(self.fetch_detail)(item.時間割コード, year)
                    except Exception as e:
                        self._logger.error(e)
                        return None
                    pbar.update()
                    if on_detail_request:
                        await _await_if_future(on_detail_request(details))
                    return details

            detail_task = create_task(inner(item))
            tasks.append(detail_task)
        results = await asyncio.gather(*tasks)
        return results

    def get_filepath(self, params: SearchParams, filename: str | None) -> Path:
        if not filename:
            filename = params.id()
        if not filename.endswith(".pkl"):
            filename += ".pkl"
        filepath = Path(filename)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        return filepath

    async def fetch_and_save_search_detail_all(
        self,
        params: SearchParams,
        *,
        year: int = current_fiscal_year(),
        filename: str | None = None,
        use_tqdm: bool = True,
        on_initial_request: None | (Callable[[SearchResult], Awaitable | None]) = None,
    ) -> Iterable[Details]:
        """Fetch all search results by repeatedly calling `fetch_search` and `fetch_detail` and save them to a PKL file.
        The filename is params.id() + ".pkl" if not specified.

        Parameters
        ----------
        params : SearchParams
            Search parameters
        year : int, optional
            Year of the course, by default current_fiscal_year()
        filename : Optional[str], optional
            Filename to save the results, by default None. If None, the filename is params.id() + ".pkl".
        use_tqdm : bool, optional
            Whether to use tqdm, by default True
        on_initial_request : Optional[Callable[[SearchResult], Optional[Awaitable]]], optional
            Callback function to be called on the initial request, by default None

        Returns
        -------
        AsyncIterable[Details]
            Async iterable of details

        Yields
        ------
        Iterator[AsyncIterable[Details]]
            Async iterable of details
        """
        filepath = self.get_filepath(params, filename)
        self._logger.info(f"Saving to {filepath}")
        result = await self.fetch_search_detail_all(
            params,
            year=year,
            use_tqdm=use_tqdm,
            on_initial_request=on_initial_request,
        )
        try:
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(pickle.dumps(result))
        except Exception as e:
            self._logger.error(e)
            self._logger.error(f"Skipping saving to {filepath}")
        return result

    async def fetch_and_save_search_detail_all_pandas(
        self,
        params: SearchParams,
        *,
        year: int = current_fiscal_year(),
        filename: str | None = None,
        use_tqdm: bool = True,
        on_initial_request: None | (Callable[[SearchResult], Awaitable | None]) = None,
    ) -> DataFrame:
        data = await self.fetch_and_save_search_detail_all(
            params,
            year=year,
            use_tqdm=use_tqdm,
            on_initial_request=on_initial_request,
            filename=filename,
        )
        try:
            from .pandas import to_dataframe

            df = to_dataframe(data)
        except Exception as e:
            self._logger.error(e)
            self._logger.error("Returning raw data instead of pandas dataframe.")
            return data  # type: ignore
        try:
            filepath = self.get_filepath(params, filename)
            filepath = filepath.with_suffix(".pandas.pkl")
            self._logger.info(f"Saving to {filepath}")
            df.to_pickle(filepath.absolute())
        except Exception as e:
            self._logger.error(e)
            self._logger.error(f"Skipping saving to {filename}")
        return df
