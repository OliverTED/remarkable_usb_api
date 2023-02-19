import logging
from pathlib import Path

import click
from tqdm import tqdm

from remarkable_usb_api.rest_api import Document, RemarkableREST

logger = logging.getLogger(__name__)


def _debug_enable_http_logging():
    import http.client as http_client

    http_client.HTTPConnection.debuglevel = 1

    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True


@click.group()
@click.option("--verbose/--no-verbose", type=bool)
@click.option(
    "--base-url",
    type=str,
    default="http://10.11.99.1",
    help="The url the remarkable's rest api is found at.",
)
@click.pass_context
def cli(ctx, *, verbose: bool = False, base_url: str):
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        _debug_enable_http_logging()
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("urllib3").setLevel(logging.ERROR)  # supress warnings


def _connect(ctx) -> RemarkableREST:
    ctx.ensure_object(dict)
    rm = RemarkableREST(base_url=ctx.obj["base_url"])
    return rm


@cli.command()
@click.pass_context
def ls(ctx):
    rm = _connect(ctx)

    docs = rm.get_documents(recurse=True)
    for doc in docs:
        print(f"{doc.document_id} {doc.visible_name} {doc.extension} {doc.page_count}")


@cli.command()
@click.option(
    "--output-directory",
    type=str,
    help="The directory to store files at.  Existing files are overwritten.",
)
@click.pass_context
def download(ctx, *, output_directory: str):
    """Download files from the remarkable"""
    rm = _connect(ctx)

    out = Path(output_directory)
    if out.exists():
        logger.warning("warning: output directory exists")

    out.mkdir(parents=True, exist_ok=True)

    docs = rm.get_documents(recurse=True)
    for doc in docs:
        if isinstance(doc, Document):
            out_fn = out / doc.filename

            if out_fn.exists():
                if out_fn.stat().st_size == doc.length:
                    logger.warning(f"skipping file with same size: {out_fn}")
                    continue
                else:
                    logger.info(
                        f"overwriting file with different size: {out_fn}; "
                        f"{out_fn.stat().st_size} (disc) != {doc.length} (rm)"
                    )

            print(f"downloading {out_fn} ({doc.id_}; {doc.page_count} pages)")
            rm.download_document_as_file(doc.id_, out_fn)


@cli.command()
@click.option("--directory", type=str, help="Directory to read files from.")
@click.pass_context
def upload(ctx, *, directory: str):
    """Upload a directory with files to the remarkable"""
    rm: RemarkableREST = _connect(ctx)

    out = Path(directory)

    files = []
    for fn in sorted(out.glob("**/*")):
        if fn.suffix in {".pdf"}:
            files.append(fn.relative_to(out))
        elif not fn.is_file():
            continue
        else:
            logger.warning(f"unknown filetype, skipping: {fn}")

    for fn in (pbar := tqdm(files)):
        pbar.set_description("Processing %s" % fn)
        docs = rm.get_documents(recurse=True)
        if not rm.has_file(fn, docs=docs):
            print(f"uploading {fn}")
            rm.upload_document_as_file(fn_disc=out / fn, fn_rm=fn, docs=docs)


if __name__ == "__main__":
    cli()
