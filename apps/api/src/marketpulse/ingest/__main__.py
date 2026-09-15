import asyncio

import typer

from marketpulse.config import get_settings
from marketpulse.db.session import make_engine, make_session_factory
from marketpulse.ingest.jobs import JOB_NAMES, run_source

app = typer.Typer(help="Jay Trader ingest jobs.")


async def _execute(jobs: tuple[str, ...], full: bool) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    succeeded: list[str] = []
    failed: list[str] = []
    try:
        for job in jobs:
            typer.echo(f"running {job} (full={full}) ...")
            try:
                run_id = await run_source(job, full=full, session_factory=session_factory,
                                          settings=settings)
            except Exception as exc:
                typer.echo(f"  FAILED: {exc}")
                failed.append(job)
                continue
            typer.echo(f"  ingest_run id={run_id}")
            succeeded.append(job)
    finally:
        await engine.dispose()

    typer.echo(
        f"summary: {len(succeeded)} succeeded ({', '.join(succeeded) or 'none'}), "
        f"{len(failed)} failed ({', '.join(failed) or 'none'})"
    )
    if failed:
        raise typer.Exit(code=1)


@app.command()
def backfill(
    source: str = typer.Option(..., help="Job name, or 'all' for every job."),
) -> None:
    """Load full history. Run once per source."""
    jobs = JOB_NAMES if source == "all" else (source,)
    for job in jobs:
        if job not in JOB_NAMES:
            raise typer.BadParameter(f"unknown job {job}; choose from {JOB_NAMES} or 'all'")
    asyncio.run(_execute(tuple(jobs), full=True))


@app.command()
def daily(
    source: str = typer.Option(..., help="Job name, or 'all' for every job."),
) -> None:
    """Incremental refresh. What the Cloudflare cron triggers call."""
    jobs = JOB_NAMES if source == "all" else (source,)
    for job in jobs:
        if job not in JOB_NAMES:
            raise typer.BadParameter(f"unknown job {job}; choose from {JOB_NAMES} or 'all'")
    asyncio.run(_execute(tuple(jobs), full=False))


if __name__ == "__main__":
    app()
