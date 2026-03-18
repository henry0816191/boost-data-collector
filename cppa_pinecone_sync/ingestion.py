"""
Pinecone ingestion module for document indexing and vector storage.

Handles Pinecone index creation, document chunking, and vector operations
(upsert, update, delete). Uses Pinecone integrated cloud embeddings for
hybrid search (dense + sparse).

Adapted from old files/ingestion.py; uses Django settings instead of a
standalone config module.
"""

from __future__ import annotations

import hashlib
import logging
import re
from enum import Enum
from typing import Any, Optional

from django.conf import settings


class PineconeInstance(str, Enum):
    """Selects which Pinecone API key to use."""

    PUBLIC = "public"
    PRIVATE = "private"


try:
    from pinecone import Pinecone
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document
except ImportError as e:
    Pinecone = None  # type: ignore[assignment,misc]
    RecursiveCharacterTextSplitter = None  # type: ignore[assignment,misc]
    Document = None  # type: ignore[assignment,misc]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None

logger = logging.getLogger(__name__)


class PineconeIngestion:
    """Handles Pinecone index creation, document chunking, and vector operations."""

    def __init__(self, instance: PineconeInstance = PineconeInstance.PUBLIC) -> None:
        """Initialize with configuration from Django settings.

        Args:
            instance: Which Pinecone API key to use (public or private).
                Default is public.
        """
        self._validate_imports()

        self.instance = instance
        self._api_key: str = getattr(settings, "PINECONE_API_KEY", "")
        self._private_api_key: str = getattr(settings, "PINECONE_PRIVATE_API_KEY", "")
        self.index_name: str = getattr(settings, "PINECONE_INDEX_NAME", "")
        self.environment: str = getattr(settings, "PINECONE_ENVIRONMENT", "us-east-1")
        self.cloud: str = getattr(settings, "PINECONE_CLOUD", "aws")
        self.batch_size: int = int(getattr(settings, "PINECONE_BATCH_SIZE", 96))
        self.chunk_size: int = int(getattr(settings, "PINECONE_CHUNK_SIZE", 1000))
        self.chunk_overlap: int = int(getattr(settings, "PINECONE_CHUNK_OVERLAP", 200))
        self.min_text_length: int = int(
            getattr(settings, "PINECONE_MIN_TEXT_LENGTH", 50)
        )
        self.min_words: int = int(getattr(settings, "PINECONE_MIN_WORDS", 5))
        self.dense_model: str = getattr(
            settings, "PINECONE_DENSE_MODEL", "multilingual-e5-large"
        )
        self.sparse_model: str = getattr(
            settings, "PINECONE_SPARSE_MODEL", "pinecone-sparse-english-v0"
        )

        self._setup_client()
        self._initialize_text_splitter()
        self._setup_indexes()

        logger.info(
            "PineconeIngestion: dense_model=%s, sparse_model=%s, instance=%s",
            self.dense_model,
            self.sparse_model,
            self.instance.value,
        )

    @property
    def _active_api_key(self) -> str:
        """Return the API key for the selected instance."""
        if self.instance == PineconeInstance.PRIVATE:
            return self._private_api_key
        return self._api_key

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Ensure required Pinecone settings are set; raise ValueError with clear message if not."""
        if not (self.index_name or "").strip():
            raise ValueError(
                "PINECONE_INDEX_NAME is not set or is empty. "
                "Set PINECONE_INDEX_NAME in .env (e.g. PINECONE_INDEX_NAME=boost-dashboard) "
                "to enable Pinecone sync."
            )
        active_key = self._active_api_key
        if not (active_key or "").strip():
            key_name = (
                "PINECONE_PRIVATE_API_KEY"
                if self.instance == PineconeInstance.PRIVATE
                else "PINECONE_API_KEY"
            )
            raise ValueError(
                f"{key_name} is not set or is empty. "
                f"Set {key_name}=pc-xxxx in .env to enable Pinecone sync."
            )

    @staticmethod
    def _validate_imports() -> None:
        """Validate required imports are available."""
        if _IMPORT_ERROR is not None:
            raise ImportError(
                "Missing dependencies for Pinecone ingestion. "
                "Install with: pip install pinecone langchain-text-splitters langchain-core"
            ) from _IMPORT_ERROR

    def _setup_client(self) -> None:
        self.pc: Optional[Pinecone] = None
        self._pc_initialized = False

    def _initialize_text_splitter(self) -> None:
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            add_start_index=True,
        )

    def _setup_indexes(self) -> None:
        self.dense_index: Optional[Any] = None
        self.sparse_index: Optional[Any] = None
        self._dense_index_initialized = False
        self._sparse_index_initialized = False

    # ------------------------------------------------------------------
    # Client / index management
    # ------------------------------------------------------------------

    def _ensure_pinecone_client(self) -> None:
        """Initialize Pinecone client if needed."""
        if not self._pc_initialized:
            try:
                self.pc = Pinecone(api_key=self._active_api_key)
                self._pc_initialized = True
                logger.info(
                    "Pinecone client initialized (instance: %s)",
                    self.instance.value,
                )
            except Exception as e:
                logger.error("Failed to initialize Pinecone client: %s", e)
                raise ConnectionError(
                    f"Cannot connect to Pinecone. Check API key. Error: {e}"
                ) from e

    def _get_or_create_indexes(self) -> None:
        """Get existing indexes or create new ones."""
        self._validate_config()

        if self._dense_index_initialized and self._sparse_index_initialized:
            return

        self._ensure_pinecone_client()
        if self.pc is None:
            raise RuntimeError("Pinecone client not initialized")

        existing_indexes = {idx.name for idx in self.pc.list_indexes()}
        dense_name = self.index_name
        sparse_name = f"{self.index_name}-sparse"

        if dense_name in existing_indexes and sparse_name in existing_indexes:
            self._connect_to_existing_indexes(dense_name, sparse_name)
        else:
            self._create_new_indexes(existing_indexes, dense_name, sparse_name)

        self._dense_index_initialized = True
        self._sparse_index_initialized = True

    def _connect_to_existing_indexes(self, dense_name: str, sparse_name: str) -> None:
        logger.info("Using existing indexes: %s and %s", dense_name, sparse_name)
        self.dense_index = self.pc.Index(dense_name)  # type: ignore[union-attr]
        self.sparse_index = self.pc.Index(sparse_name)  # type: ignore[union-attr]

    def _create_new_indexes(
        self, existing_indexes: set, dense_name: str, sparse_name: str
    ) -> None:
        logger.info(
            "Creating indexes: %s (dense) and %s (sparse)",
            dense_name,
            sparse_name,
        )
        if self.pc is None:
            raise RuntimeError("Pinecone client not initialized")
        try:
            if dense_name not in existing_indexes:
                self._create_pinecone_index(dense_name, self.dense_model)
            if sparse_name not in existing_indexes:
                self._create_pinecone_index(sparse_name, self.sparse_model)
            self.dense_index = self.pc.Index(dense_name)
            self.sparse_index = self.pc.Index(sparse_name)
        except Exception as e:
            error_msg = str(e)
            if "NOT_FOUND" in error_msg or "not found" in error_msg.lower():
                raise ValueError(
                    f"Invalid Pinecone region: '{self.environment}'. Error: {e}"
                ) from e
            raise

    def _create_pinecone_index(self, index_name: str, model_name: str) -> None:
        logger.info("Creating index '%s' with model: %s", index_name, model_name)
        if self.pc is None:
            raise RuntimeError("Pinecone client not initialized")
        self.pc.create_index_for_model(
            name=index_name,
            cloud=self.cloud,
            region=self.environment,
            embed={
                "model": model_name,
                "field_map": {"text": "chunk_text"},
            },
        )

    def _ensure_indexes_ready(self) -> None:
        if not self._dense_index_initialized or not self._sparse_index_initialized:
            self._get_or_create_indexes()
        if self.dense_index is None or self.sparse_index is None:
            raise RuntimeError("Pinecone indexes not initialized")

    @staticmethod
    def _empty_upsert_result() -> dict[str, Any]:
        """Return result dict when there are no documents to upsert."""
        return {
            "upserted": 0,
            "total": 0,
            "errors": [],
            "failed_documents": [],
        }

    @staticmethod
    def _empty_update_result() -> dict[str, Any]:
        """Return result dict when there are no documents to update."""
        return {
            "updated": 0,
            "total": 0,
            "errors": [],
            "failed_documents": [],
        }

    # ------------------------------------------------------------------
    # Chunk validation
    # ------------------------------------------------------------------

    def _is_valid_chunk(self, text: str) -> bool:
        """Check if a text chunk is valid for upserting."""
        if not text or len(text) < self.min_text_length:
            return False
        if self._is_table_separator(text):
            return False
        if self._is_mostly_formatting(text):
            return False
        words = re.findall(r"\b[a-zA-Z0-9]+\b", text)
        if len(words) < self.min_words:
            return False
        non_space = re.findall(r"[^\s]", text)
        punct = len(re.findall(r"[^\w\s]", text))
        if non_space and punct / len(non_space) > 0.5:
            return False
        return True

    @staticmethod
    def _is_table_separator(text: str) -> bool:
        return bool(re.match(r"^\|[\s\-:]+\|[\s\-:]*\|?[\s\-:]*\|?.*$", text))

    @staticmethod
    def _is_mostly_formatting(text: str) -> bool:
        formatting = len(re.findall(r"[|\-\s:]", text))
        return len(text) > 0 and formatting / len(text) > 0.7

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_documents(
        self,
        documents: list[Document],
        namespace: Optional[str] = None,
        is_chunked: bool = False,
    ) -> dict[str, Any]:
        """Upsert documents to Pinecone indexes. Returns statistics dict.

        Args:
            documents: List of langchain Document objects.
            namespace: Pinecone namespace.
            is_chunked: If True, skip text splitting (documents are already chunked).

        Returns:
            dict with keys: upserted, total, errors, failed_documents, failed_count.
        """
        if not documents:
            logger.warning("No documents to upsert")
            return self._empty_upsert_result()

        self._ensure_indexes_ready()
        chunked = (
            documents if is_chunked else self.text_splitter.split_documents(documents)
        )
        total_upserted, errors, failed_docs = self._upsert_all_batches(
            chunked, namespace
        )
        return {
            "upserted": total_upserted,
            "total": len(documents),
            "errors": errors,
            "failed_documents": failed_docs,
        }

    def _upsert_all_batches(
        self,
        documents: list[Document],
        namespace: Optional[str],
    ) -> tuple[int, list[str], list[dict[str, Any]]]:
        total_upserted, errors, failed_docs = 0, [], []

        for i in range(0, len(documents), self.batch_size):
            batch = documents[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            try:
                records = self._prepare_batch_records(batch, i)
                if not records:
                    logger.warning("Batch %d: no valid records", batch_num)
                    continue
                self._upsert_batch(records, namespace, batch_num)
                total_upserted += len(records)
                logger.info(
                    "Upserted batch %d: %d/%d documents",
                    batch_num,
                    len(records),
                    len(batch),
                )
            except Exception as e:
                error_msg = f"Error upserting batch {batch_num}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                failed_docs.extend(self._mark_batch_failed(batch, e))

        return total_upserted, errors, failed_docs

    def _prepare_batch_records(
        self, batch: list[Document], batch_start_idx: int
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for doc in batch:
            text = doc.page_content.strip() if doc.page_content else ""
            if not self._is_valid_chunk(text):
                continue

            metadata = doc.metadata or {}
            if metadata.get("title"):
                text = f"Title: {metadata['title']}\n\n{text}"
            doc_id = self._build_hashed_doc_id(
                metadata=metadata,
                text=text,
                batch_start_idx=batch_start_idx,
                record_idx=len(records),
            )
            record: dict[str, Any] = {"id": doc_id, "chunk_text": text}
            record.update(metadata)
            record.pop("table_ids", None)
            records.append(record)
        return records

    @staticmethod
    def _build_hashed_doc_id(
        metadata: dict[str, Any],
        text: str,
        batch_start_idx: int,
        record_idx: int,
    ) -> str:
        original_doc_id = metadata.get(
            "doc_id",
            metadata.get("url", f"doc_{batch_start_idx}_{record_idx}"),
        )
        if "start_index" in metadata:
            original_doc_id = f"{original_doc_id}_{metadata['start_index']}"
        else:
            original_doc_id = f"{original_doc_id}_{text[:50]}_{len(text)}"

        return hashlib.md5(original_doc_id.encode()).hexdigest()

    @staticmethod
    def _mark_batch_failed(
        batch: list[Document], error: Exception
    ) -> list[dict[str, Any]]:
        failed: list[dict[str, Any]] = []
        for doc in batch:
            meta = doc.metadata or {}
            failed.append(
                {
                    "ids": meta.get("table_ids", ""),
                    "reason": f"Batch upsert failed: {error}",
                }
            )
        return failed

    def _upsert_batch(
        self,
        records: list[dict[str, Any]],
        namespace: Optional[str],
        batch_num: int,
    ) -> None:
        self._ensure_indexes_ready()
        self._upsert_to_index(self.dense_index, records, namespace, batch_num, "dense")
        self._upsert_to_index(
            self.sparse_index, records, namespace, batch_num, "sparse"
        )

    # ------------------------------------------------------------------
    # Metadata update
    # ------------------------------------------------------------------

    def update_documents(
        self,
        documents: list[Document],
        namespace: Optional[str] = None,
        is_chunked: bool = False,
    ) -> dict[str, Any]:
        """Update metadata for existing documents in Pinecone indexes.

        Args:
            documents: List of langchain Document objects.
            namespace: Pinecone namespace.
            is_chunked: If True, skip text splitting (documents are already chunked).

        Returns:
            dict with keys: updated, total, errors, failed_documents.
        """
        if not documents:
            logger.warning("No documents to update metadata")
            return self._empty_update_result()

        self._ensure_indexes_ready()
        chunked = (
            documents if is_chunked else self.text_splitter.split_documents(documents)
        )
        updated_count, errors, failed_docs = self._update_all_batches(
            chunked, namespace
        )
        return {
            "updated": updated_count,
            "total": len(documents),
            "errors": errors,
            "failed_documents": failed_docs,
        }

    def _update_all_batches(
        self,
        documents: list[Document],
        namespace: Optional[str],
    ) -> tuple[int, list[str], list[dict[str, Any]]]:
        updated_count, errors, failed_docs = 0, [], []

        for i in range(0, len(documents), self.batch_size):
            batch = documents[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1

            batch_updates = self._prepare_batch_updates(batch, i)
            if not batch_updates:
                logger.warning("Update batch %d: no valid records", batch_num)
                continue

            batch_failed_count = 0
            for update in batch_updates:
                try:
                    self._update_single_record(update, namespace)
                    updated_count += 1
                except Exception as e:
                    error_msg = (
                        f"Error updating metadata for batch {batch_num} "
                        f"record {update['id']}: {e}"
                    )
                    logger.error(error_msg)
                    errors.append(error_msg)
                    failed_docs.append(
                        {
                            "ids": update.get("ids", ""),
                            "reason": f"Metadata update failed: {e}",
                        }
                    )
                    batch_failed_count += 1

            logger.info(
                "Updated metadata for batch %d: %d/%d documents",
                batch_num,
                len(batch_updates) - batch_failed_count,
                len(batch_updates),
            )

        return updated_count, errors, failed_docs

    def _prepare_batch_updates(
        self, batch: list[Document], batch_start_idx: int
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        for doc in batch:
            text = doc.page_content.strip() if doc.page_content else ""
            if not self._is_valid_chunk(text):
                continue

            metadata = dict(doc.metadata or {})
            if metadata.get("title"):
                text = f"Title: {metadata['title']}\n\n{text}"

            doc_id = self._build_hashed_doc_id(
                metadata=metadata,
                text=text,
                batch_start_idx=batch_start_idx,
                record_idx=len(updates),
            )

            source_ids = metadata.get("table_ids", "")
            metadata.pop("table_ids", None)
            updates.append({"id": doc_id, "set_metadata": metadata, "ids": source_ids})

        return updates

    def _update_single_record(
        self, update: dict[str, Any], namespace: Optional[str]
    ) -> None:
        self._ensure_indexes_ready()
        record_id = update["id"]
        set_metadata = update["set_metadata"]

        self._update_index_record(
            self.dense_index, record_id, set_metadata, namespace, "dense"
        )
        self._update_index_record(
            self.sparse_index, record_id, set_metadata, namespace, "sparse"
        )

    @staticmethod
    def _update_index_record(
        index: Any,
        record_id: str,
        set_metadata: dict[str, Any],
        namespace: Optional[str],
        index_type: str,
    ) -> None:
        try:
            index.update(id=record_id, set_metadata=set_metadata, namespace=namespace)
        except Exception as e:
            logger.error(
                "Failed to update metadata in %s index for id=%s: %s",
                index_type,
                record_id,
                e,
            )
            raise

    @staticmethod
    def _upsert_to_index(
        index: Any,
        records: list[dict[str, Any]],
        namespace: Optional[str],
        batch_num: int,
        index_type: str,
    ) -> None:
        try:
            index.upsert_records(records=records, namespace=namespace)
        except Exception as e:
            record_ids = [r.get("id", "unknown") for r in records]
            logger.error(
                "Failed to upsert batch %d to %s index: %s. Records: %s",
                batch_num,
                index_type,
                e,
                record_ids,
            )
            raise

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_documents(
        self,
        ids: list[str],
        namespace: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delete documents from Pinecone indexes by IDs."""
        if not ids:
            logger.warning("No document IDs to delete")
            return {"deleted": 0, "total": 0, "errors": []}

        self._ensure_indexes_ready()
        total_deleted, errors = 0, []

        for i in range(0, len(ids), self.batch_size):
            batch_ids = ids[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            try:
                self._delete_batch(batch_ids, namespace, batch_num)
                total_deleted += len(batch_ids)
            except Exception as e:
                error_msg = f"Error deleting batch {batch_num}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        result = {
            "deleted": total_deleted,
            "total": len(ids),
            "errors": errors,
        }
        logger.info(
            "Delete complete: %d/%d documents",
            result["deleted"],
            result["total"],
        )
        return result

    def _delete_batch(
        self,
        ids: list[str],
        namespace: Optional[str],
        batch_num: int,
    ) -> None:
        self._ensure_indexes_ready()
        self._delete_from_index(self.dense_index, ids, namespace, batch_num, "dense")
        self._delete_from_index(self.sparse_index, ids, namespace, batch_num, "sparse")
        logger.info("Deleted batch %d: %d documents", batch_num, len(ids))

    @staticmethod
    def _delete_from_index(
        index: Any,
        ids: list[str],
        namespace: Optional[str],
        batch_num: int,
        index_type: str,
    ) -> None:
        try:
            index.delete(ids=ids, namespace=namespace)
        except Exception as e:
            logger.error(
                "Failed to delete batch %d from %s index: %s",
                batch_num,
                index_type,
                e,
            )
            raise

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @staticmethod
    def _format_single_index_stats(
        stats_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Format one index's describe_index_stats() into a standard dict."""
        return {
            "total_vectors": stats_dict.get("total_vector_count", 0),
            "dimension": stats_dict.get("dimension", 0),
            "index_fullness": stats_dict.get("index_fullness", 0),
            "namespaces": stats_dict.get("namespaces", {}),
        }

    def get_index_stats(self) -> dict[str, Any]:
        """Get statistics about the Pinecone indexes."""
        try:
            self._ensure_indexes_ready()
            dense_stats = self.dense_index.describe_index_stats()  # type: ignore[union-attr]
            sparse_stats = self.sparse_index.describe_index_stats()  # type: ignore[union-attr]
            return {
                "dense_index": self._format_single_index_stats(dense_stats),
                "sparse_index": self._format_single_index_stats(sparse_stats),
            }
        except Exception as e:
            logger.error("Error getting index stats: %s", e)
            empty = self._format_single_index_stats({})
            return {
                "error": str(e),
                "dense_index": dict(empty),
                "sparse_index": dict(empty),
            }
