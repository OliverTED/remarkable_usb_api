import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import requests
from attr import define
from cattrs import ClassValidationError, Converter

logger = logging.getLogger(__name__)


@define
class RMApiDocument:
    Bookmarked: bool
    ID: str
    ModifiedClient: str
    Parent: str
    Type: Literal["DocumentType", "CollectionType"]
    Version: int
    tags: List[str]
    VissibleName: str

    CurrentPage: Optional[int] = None
    coverPageNumber: Optional[int] = None
    documentMetadata: Optional[Dict[str, str]] = None
    dummyDocument: Optional[bool] = None
    extraMetadata: Optional[Dict[Any, Any]] = None
    fileType: Optional[Literal["pdf", "notebook", "epub"]] = None
    fontName: Optional[str] = None
    formatVersion: Optional[int] = None
    lineHeight: Optional[int] = None
    margins: Optional[int] = None
    orientation: Optional[str] = None
    originalPageCount: Optional[int] = None
    pageCount: Optional[int] = None
    pageTags: Optional[List[str]] = None
    pages: Optional[List[str]] = None
    sizeInBytes: Optional[str] = None
    textAlignment: Optional[str] = None
    textScale: Optional[int] = None
    redirectionPageMap: Optional[List[int]] = None


@define
class RMApiDocuments:
    documents: List[RMApiDocument]


_converter = Converter(forbid_extra_keys=False)


def _parse_documents(documents) -> RMApiDocuments:
    try:
        return _converter.structure(documents, RMApiDocuments)
    except ClassValidationError:
        print(json.dumps(documents, indent=4))
        raise


class RemarkableRESTRaw:
    def __init__(self, *, base_url: Optional[str]):
        if base_url is None:
            base_url = "http://10.11.99.1"
        self.base_url = base_url

    def read_folder(
        self,
        *,
        folder_id: Optional[str] = None,
        retries: int = 3,
    ) -> RMApiDocuments:
        """Read documents & folder meta info available on the remarkable.

        :param folder_id The id of the folder to read, or None if root folder shall be read.
        :param retries      Number of times to retry.
        """
        if folder_id is None:
            folder_id = ""
        res = requests.post(f"{self.base_url}/documents/{folder_id}")

        if not res.ok and retries > 0:
            return self.read_folder(folder_id=folder_id, retries=retries - 1)

        assert res.ok, res
        res = res.json()
        docs: RMApiDocuments = _parse_documents(dict(documents=res))
        return docs

    def download_document_as_file(
        self,
        document_id: str,
        *,
        write_to_file: Optional[Path],
        retries: int = 3,
    ):
        url = f"{self.base_url}/download/{document_id}/placeholder"

        if write_to_file is not None:
            res = requests.get(url, stream=True)
        else:
            res = requests.head(url)

        if not res.ok and retries > 0:
            return self.download_document_as_file(
                document_id=document_id,
                write_to_file=write_to_file,
                retries=retries - 1,
            )

        assert res.ok, res

        # headers = {k.lower(): v for k, v in res.headers.items()}

        if write_to_file is not None:
            if write_to_file.exists():
                write_to_file.unlink()
            write_to_file.parent.mkdir(parents=True, exist_ok=True)

            with write_to_file.open("wb") as fd:
                for chunk in res.iter_content(chunk_size=4096):
                    fd.write(chunk)

    def mkdir(
        self,
        fn: Path,
    ):
        """This is a dummy function.  It should create a folder on the remarkable, though
        I am not aware how that is possible with the current api.  So it just checks if
        a folder with the name exists.  If not it raises an error, so that the user
        can create the folder.

        :param fn        The folder to create.
        """

        # TODO Find api and implement
        raise RuntimeError(
            f"mkdir: not implemented; please create the following folder on the remarkable: ({fn})"
        )

    def upload_document_as_file(
        self, *, fn_disc: Path, fn_rm: Path, folder_id: Optional[str]
    ):
        """Upload a local file to the remarkable.

        :param fn_disc   The local filename to upload.  Must be a pdf file.
        :param fn_rm     The filename on the remarkable, including the folder.
        :param folder_id The Folder to put the file into.  If 'None' the files goes to the root folder.
        """

        assert fn_disc.suffix == ".pdf", "currently only uploading of pdfs is supported"
        assert fn_rm.suffix == ".pdf", "currently only uploading of pdfs is supported"

        self.read_folder(folder_id=folder_id)

        url = f"{self.base_url}/upload"

        logger.debug(f"upload filename: {fn_rm.name}")
        content = fn_disc.read_bytes()
        res = requests.post(url, files=dict(file=(fn_rm.name, content)))
        if not res.ok:
            raise RuntimeError(f"error uploading {fn_disc} to {fn_rm}")
