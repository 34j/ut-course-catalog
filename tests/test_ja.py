from unittest import IsolatedAsyncioTestCase

import pandas as pd
from rich.console import Console

import ut_course_catalog.ja as utcc
from ut_course_catalog import Weekday


class TestJa(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.console = Console()
        self.catalog = utcc.UTCourseCatalog()
        await self.catalog.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.catalog.__aexit__(None, None, None)

    async def test_detail(self) -> None:
        await self.catalog.fetch_detail("060320623", 2022)
        # self.console.print(detail)

    async def test_search(self) -> None:
        results = await self.catalog.fetch_search(
            utcc.SearchParams(keyword="量子力学", 曜日=[Weekday.Mon])
        )
        # self.console.print(results)
        df = pd.DataFrame([x._asdict() for x in results.items])
        self.assertTrue(df["曜限"].str.contains("Mon").all())

    async def test_common_code(self) -> None:
        code = utcc.CommonCode("FSC-MA2301L1")
        self.assertEqual(code.institution, utcc.Institution.学部後期課程)
        self.assertEqual(code.faculty, utcc.Faculty.理学部)
        self.assertEqual(code.department_code, "MA")
        self.assertEqual(code.level, "2")
        self.assertEqual(code.reference_number, "301")
        self.assertEqual(code.class_form, utcc.ClassForm.講義)
        self.assertEqual(code.language, utcc.Language.Japanese)

    async def test_fetch_common_code(self) -> None:
        common_code = await self.catalog.fetch_common_code("0505001")
        self.assertEqual("FSC-MA2301L1", common_code)

    async def test_fetch_code(self) -> None:
        code = await self.catalog.fetch_code("FSC-MA2301L1")
        self.assertEqual("0505001", code)
