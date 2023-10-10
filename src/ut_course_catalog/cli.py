"""Console script for ut_course_catalog."""
import asyncio
from datetime import datetime, timedelta

import click

import ut_course_catalog.ja as utcc


@click.command()
@click.option(
    "-m",
    "--min-interval",
    default=0.5,
    help="Minimum interval between calls in seconds.",
)
def cli(min_interval: float) -> None:
    asyncio.run(_main(min_interval))


async def _main(min_interval: float) -> None:
    params = utcc.SearchParams()
    async with utcc.UTCourseCatalog(
        min_interval=timedelta(seconds=min_interval)
    ) as catalog:
        t = datetime.now().strftime("%Y%m%d%H%M%S")
        await catalog.fetch_and_save_search_detail_all_pandas(
            params, filename=f"All_{t}.pkl"
        )
