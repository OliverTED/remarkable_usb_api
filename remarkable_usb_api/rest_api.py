import logging
from pathlib import Path
from typing import Callable, List, Optional, Union

from attr import define

from remarkable_usb_api.rm_rest_api_types import (
    RemarkableRESTRaw,
    RMApiDocument,
    RMApiDocuments,
)

logger = logging.getLogger(__name__)


@define
class Document:
    id_: str
    folder: "Optional[Folder]"
    visible_name: str
    length: int
    extension: str
    page_count: int
    parent_id: Optional[str]
    raw_: RMApiDocument

    @property
    def filename(self) -> Path:
        if self.folder is None:
            return Path(self.visible_name)

        return self.folder.filename / f"{self.visible_name}.{self.extension}"


@define
class Folder:
    id_: str
    folder: "Optional[Folder]"
    visible_name: str
    parent_id: Optional[str]
    raw_: RMApiDocument

    @property
    def filename(self) -> Path:
        if self.folder is None:
            return Path(self.visible_name)

        return self.folder.filename / self.visible_name


@define
class DownloadedDocument:
    id_: str
    get_data: Callable[[], bytes]
    write_to_file: Callable[[Path], None]


def _find_doc(
    name: str,
    *,
    parent_id: Optional[str],
    docs: List[Union[Document, Folder]],
) -> Union[None, Folder, Document]:

    if name.endswith(".pdf"):
        name = name[:-4]

    res = []
    for d in docs:
        if d.visible_name == name and d.parent_id == parent_id:
            res.append(d)
    if len(res) > 0:
        return res[0]
    return None


class RemarkableREST:
    def __init__(self, *, base_url: Optional[str]):
        self.raw = RemarkableRESTRaw(base_url=base_url)

    def get_documents(
        self,
        *,
        folder_id: Optional[str] = None,
        retries: int = 3,
        recurse: bool,
        parent: Optional[Folder] = None,
    ) -> List[Union[Document, Folder]]:
        """Read documents & folder meta info available on the remarkable.

        :param recurse      If true, read folders recursively.
        :param folder_id    The id of the folder to read, or None if root folder shall be read.
        :param retries      Number of times to retry.
        :param parent       parent's folder
        """

        docs: RMApiDocuments = self.raw.read_folder(
            folder_id=folder_id, retries=retries
        )
        docs_: List[Union[Folder, Document]] = []
        for raw in docs.documents:
            if raw.Type == "DocumentType":
                assert raw.sizeInBytes is not None
                assert raw.pageCount is not None
                docs_.append(
                    Document(
                        raw_=raw,
                        id_=raw.ID,
                        folder=parent,
                        visible_name=raw.VissibleName,
                        length=int(raw.sizeInBytes),
                        extension="pdf",
                        page_count=raw.pageCount,
                        parent_id=raw.Parent if raw.Parent != "" else None,
                    )
                )
            elif raw.Type == "CollectionType":
                docs_.append(
                    Folder(
                        raw_=raw,
                        id_=raw.ID,
                        folder=parent,
                        visible_name=raw.VissibleName,
                        parent_id=raw.Parent if raw.Parent != "" else None,
                    )
                )
            else:
                logger.warning(f"skipping {raw.VissibleName}/{raw.Type}")

        if recurse:
            subs = []
            for doc in docs_:
                if isinstance(doc, Folder):
                    subs += self.get_documents(
                        folder_id=doc.id_, retries=retries, recurse=recurse, parent=doc
                    )
            docs_ += subs
        return docs_

    def download_document_as_file(
        self, document_id: str, filename: Path, *, retries: int = 3
    ):
        """Store a document from the remarkable as a local file.

        :param document_id  the id of the document to read
        :param filename     the local filename to store the document to.
        :param retries      Number of times to retry.
        """

        self.raw.download_document_as_file(
            document_id=document_id, retries=retries, write_to_file=filename
        )

    def find_file(
        self, fn: Path, *, docs: Optional[List[Union[Document, Folder]]]
    ) -> Union[None, Folder, Document]:
        """Find the meta information of the file.

        :param fn   The file to check its presence
        :param docs The meta-informations of all files.  If none it is retrieved (slow).
        """

        if docs is None:
            docs = self.get_documents(recurse=True)

        parent_id = None
        if fn.parent != Path("."):
            parent = self.find_file(fn.parent, docs=docs)
            if parent is None:
                return None
            parent_id = parent.id_

        return _find_doc(fn.name, parent_id=parent_id, docs=docs)

    # @typechecked
    def has_file(
        self, fn: Path, *, docs: Optional[List[Union[Document, Folder]]]
    ) -> bool:
        """Checks if the file is present on the remarkable.

        :param fn   The file to check its presence
        :param docs The meta-informations of all files.  If none it is retrieved (slow).
        """

        return self.find_file(fn, docs=docs) is not None

    def mkdir(
        self,
        fn: Path,
        *,
        exists_ok: bool,
        parents: bool,
        docs: Optional[List[Union[Document, Folder]]],
    ) -> Folder:
        """This is a dummy function.  It should create a folder on the remarkable, though
        I am not aware how that is possible with the current api.  So it just checks if
        a folder with the name exists.  If not it raises an error, so that the user
        can create the folder.

        :param fn        The folder to create.
        :param exists_ok If False and the folder exists, raise an error.
        :param parents   If True, also create parent directories.

        :param docs The meta-informations of all files.  If none it is retrieved (slow).
        """

        if docs is None:
            docs = self.get_documents(recurse=True)

        parent_id = None
        if fn.parent != Path("."):
            if parents:
                parent = self.mkdir(fn.parent, exists_ok=True, parents=True, docs=docs)
                parent_id = parent.id_
            else:
                parent_ = self.find_file(fn.parent, docs=docs)
                if parent_ is None:
                    raise RuntimeError("parent does not exist")
                parent_id = parent_.id_

        folder = _find_doc(fn.name, parent_id=parent_id, docs=docs)
        if folder is not None and not exists_ok:
            raise RuntimeError("folder already exists")

        if isinstance(folder, Document):
            raise RuntimeError(f"mkdir: document of same name exists '{fn}'")
        elif isinstance(folder, Folder):
            if not exists_ok:
                raise RuntimeError("folder already exists")
            return folder
        elif folder is None:
            return self.raw.mkdir(fn)  # not implemented (yet?), raises exception
        else:
            raise RuntimeError("invalid case")

    def upload_document_as_file(
        self,
        *,
        fn_disc: Path,
        fn_rm: Path,
        docs: Optional[List[Union[Document, Folder]]],
    ):
        """Upload a local file to the remarkable.

        :param fn_disc   The local filename to upload.  Must be a pdf file.
        :param fn_rm     The filename on the remarkable, including the folder.

        :param docs      The meta-informations of all files.  If none it is retrieved (slow).
        """

        assert fn_disc.suffix == ".pdf", "currently only uploading of pdfs is supported"
        assert fn_rm.suffix == ".pdf", "currently only uploading of pdfs is supported"

        if docs is None:
            docs = self.get_documents(recurse=True)

        parent_id = None
        if fn_rm.parent != Path("."):
            parent_id = self.mkdir(
                fn_rm.parent, exists_ok=True, parents=True, docs=docs
            ).id_

        self.raw.upload_document_as_file(
            fn_disc=fn_disc, fn_rm=fn_rm, folder_id=parent_id
        )
