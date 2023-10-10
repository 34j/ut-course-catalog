import asyncio
from datetime import datetime, timedelta

import click

import ut_course_catalog.ja as utcc


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option(
    "-m",
    "--min-interval",
    default=0.5,
    help="Minimum interval between calls in seconds.",
)
def download(min_interval: float) -> None:
    """Download the entire course catalog."""
    asyncio.run(_download(min_interval))


@cli.command()
@click.argument("name", type=str)
def convert(name: str) -> None:
    import pickle  # nosec
    from pathlib import Path

    from ut_course_catalog.analysis import to_perfect_isolated_dataframe

    path = Path(name)
    with path.open("rb") as f:
        df = pickle.load(f)  # nosec
        df = to_perfect_isolated_dataframe(df)
        df.to_csv(path.with_suffix(".csv"))


async def _download(min_interval: float) -> None:
    params = utcc.SearchParams()
    async with utcc.UTCourseCatalog(
        min_interval=timedelta(seconds=min_interval)
    ) as catalog:
        t = datetime.now().strftime("%Y%m%d%H%M%S")
        await catalog.fetch_and_save_search_detail_all_pandas(
            params, filename=f"all_{t}.pkl"
        )
