from __future__ import annotations

import functools
from pathlib import Path

import typer

from recall.config import Registry, load_config
from recall.embedders import build_embedder
from recall.errors import RecallError
from recall.indexer import index_source
from recall.store.pgvector import PgVectorStore

app = typer.Typer(
    name="recall",
    help="Local-first hybrid retrieval for coding agents.",
    no_args_is_help=True,
)


def honest_failure(fn):
    """Every RecallError becomes a clean message and a non-zero exit — never a
    traceback. Centralised so no command can forget it."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RecallError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc

    return wrapper


def _build_embedder_for(config):
    """A seam, nothing more. Tests monkeypatch `recall.cli.build_embedder` to keep
    the CLI suite off the network. The shipped package must NEVER import from its
    own test tree, so there is no "fake" provider branch here."""
    return build_embedder(config)


def _store() -> PgVectorStore:
    return PgVectorStore(load_config().database_url)


@app.command()
@honest_failure
def init() -> None:
    """Create the schema. The embedding model is fixed here, for the life of the DB."""
    config = load_config()
    embedder = _build_embedder_for(config)
    store = _store()
    store.init(dim=embedder.dim, model=embedder.name, provider=config.embedding_provider)

    typer.echo(
        f"Database initialised.\n"
        f"  embedding : {embedder.name} ({embedder.dim} dimensions)\n"
        f"  lexical   : {store.lexical_ranker()}\n"
        f"The embedding model is now fixed for the life of this database. "
        f"To change it, run: recall reindex"
    )


@app.command()
@honest_failure
def register(path: Path) -> None:
    """Map a source's tag to its path on THIS machine."""
    tag = Registry.load().register(path)
    typer.echo(f"Registered {tag!r} -> {path.resolve()}")


@app.command()
@honest_failure
def index(tag: str, force: bool = typer.Option(False, "--force")) -> None:
    """Index a source. Slow and mutating, which is why it is a CLI command and
    not something an agent can trigger mid-conversation."""
    config = load_config()
    report = index_source(
        tag,
        registry=Registry.load(),
        store=_store(),
        embedder=_build_embedder_for(config),
        force=force,
    )

    typer.echo(
        f"Indexed {report.tag}: {report.chunks_written} chunks from "
        f"{report.files_indexed} files "
        f"({report.files_skipped} unchanged, {report.files_pruned} pruned)"
    )


@app.command()
@honest_failure
def reindex(tag: str) -> None:
    """Drop this source's chunks and rebuild. A rebuild is always correct."""
    store = _store()
    store.delete_source(tag)
    report = index_source(
        tag,
        registry=Registry.load(),
        store=store,
        embedder=_build_embedder_for(load_config()),
        force=True,
    )
    typer.echo(
        f"Reindexed {report.tag}: {report.chunks_written} chunks from {report.files_indexed} files"
    )


@app.command()
@honest_failure
def sources() -> None:
    """What is indexed: tag, chunk count, last indexed, and where it lives on this machine."""
    stats = _store().stats()

    registry = Registry.load()
    if not stats.sources:
        typer.echo("Nothing indexed yet. Try:  recall register <path> && recall index <tag>")
        return

    for tag, count in stats.sources.items():
        try:
            location = str(registry.path_for(tag))
        except RecallError:
            location = "(not registered on this machine)"
        ts = stats.last_indexed.get(tag)
        last_indexed = ts.strftime("%Y-%m-%d %H:%M") if ts else "never"
        typer.echo(f"{tag:16} {count:6} chunks   last indexed {last_indexed:16} {location}")


@app.command()
@honest_failure
def doctor() -> None:
    """Health check. Reports which lexical ranker is ACTUALLY live, and warns on
    the fallback. recall would rather be embarrassing than quietly wrong."""
    config = load_config()
    typer.echo(f"database  : {config.database_url}")

    store = _store()
    try:
        stats = store.stats()
    except RecallError as exc:
        typer.echo(f"postgres  : ERROR — {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo("postgres  : ok")
    typer.echo(f"embedding : {stats.embedding_model} ({stats.embedding_dim} dimensions)")
    typer.echo(f"backend   : {stats.backend}")
    typer.echo(f"lexical   : {stats.lexical_ranker}")

    if stats.lexical_ranker == "bm25":
        typer.echo("            real BM25, via the pg_search extension.")
    else:
        typer.echo(
            "            WARNING: this is NOT BM25.\n"
            "            ts_rank_cd is a cover-density ranker: no term-frequency\n"
            "            saturation, no document-length normalisation. It works, but\n"
            "            it is not what the literature means by BM25.\n"
            "            For real BM25, install ParadeDB's pg_search extension,\n"
            "            add it to shared_preload_libraries, restart Postgres, and\n"
            "            run: recall reindex"
        )

    typer.echo(f"chunks    : {stats.total_chunks} across {len(stats.sources)} source(s)")


@app.command()
@honest_failure
def serve(source: str = typer.Option(None, "--source", help="Tag of the current silo")) -> None:
    """Run the MCP server over stdio."""
    from recall.mcp_server import build_server

    server = build_server(source)
    server.run()


if __name__ == "__main__":
    app()
