"""Small deterministic chunker that never crosses citation boundaries."""

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata


MAX_CHUNK_CHARACTERS = 1_200
CHUNK_OVERLAP_CHARACTERS = 160
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class NormalizedChunk:
    chunk_id: str
    resource_id: str
    source_type: str
    reference_type: str
    reference_number: int
    chunk_index: int
    text: str
    extraction_method: str
    chunk_version: str

    def public_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "source_type": self.source_type,
            "reference_type": self.reference_type,
            "reference_number": self.reference_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "extraction_method": self.extraction_method,
            "chunk_version": self.chunk_version,
        }


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n")
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", normalized):
        clean = " ".join(paragraph.split())
        if clean:
            paragraphs.append(clean)
    return "\n\n".join(paragraphs)


def _hard_split(value: str, maximum: int) -> list[str]:
    parts: list[str] = []
    remaining = value.strip()
    while len(remaining) > maximum:
        boundary = remaining.rfind(" ", 0, maximum + 1)
        if boundary < maximum // 2:
            boundary = maximum
        parts.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _semantic_segments(text: str, maximum: int) -> list[str]:
    segments: list[str] = []
    for paragraph in text.split("\n\n"):
        if len(paragraph) <= maximum:
            segments.append(paragraph)
            continue
        sentences = _SENTENCE_BOUNDARY.split(paragraph)
        for sentence in sentences:
            if len(sentence) <= maximum:
                segments.append(sentence)
            else:
                segments.extend(_hard_split(sentence, maximum))
    return segments


def _overlap_tail(text: str, maximum: int) -> str:
    if len(text) <= maximum:
        return text
    tail = text[-maximum:]
    first_space = tail.find(" ")
    return tail[first_space + 1 :].strip() if first_space >= 0 else tail


def split_text(
    text: str,
    *,
    max_characters: int = MAX_CHUNK_CHARACTERS,
    overlap_characters: int = CHUNK_OVERLAP_CHARACTERS,
) -> list[str]:
    """Pack semantic segments into bounded chunks with a small text overlap."""
    if max_characters < 100:
        raise ValueError("Chunk size must be at least 100 characters.")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("Chunk overlap must be smaller than the chunk size.")

    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""
    for segment in _semantic_segments(normalized, max_characters):
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(segment) <= max_characters:
            current = f"{current}{separator}{segment}"
            continue

        if current:
            chunks.append(current)
            overlap = _overlap_tail(current, overlap_characters)
            separator = "\n\n" if overlap else ""
            current = f"{overlap}{separator}{segment}"
        else:
            current = segment

        if len(current) > max_characters:
            pieces = _hard_split(current, max_characters)
            chunks.extend(pieces[:-1])
            current = pieces[-1]

    if current:
        chunks.append(current)
    return chunks


def build_chunks(
    resource_id: str,
    source_type: str,
    content: list[dict[str, object]],
    chunk_version: str,
) -> list[NormalizedChunk]:
    """Create deterministic chunks while retaining page/slide/image provenance."""
    expected_reference = {"pdf": "page", "pptx": "slide", "image": "image"}.get(
        source_type
    )
    if expected_reference is None:
        raise ValueError(f"Chunking is not supported for source type: {source_type}")

    chunks: list[NormalizedChunk] = []
    for unit in content:
        reference_type = str(unit.get("reference_type", ""))
        reference_number = unit.get("reference_number")
        if (
            reference_type != expected_reference
            or type(reference_number) is not int
            or reference_number < 1
        ):
            raise ValueError("Extracted content has invalid citation provenance.")
        extraction_method = str(unit.get("extraction_method", "native"))
        for chunk_index, text in enumerate(split_text(str(unit.get("text", ""))), 1):
            identity = (
                f"{resource_id}\0{chunk_version}\0{reference_type}\0"
                f"{reference_number}\0{chunk_index}\0{text}"
            )
            chunks.append(
                NormalizedChunk(
                    chunk_id=sha256(identity.encode("utf-8")).hexdigest()[:32],
                    resource_id=resource_id,
                    source_type=source_type,
                    reference_type=reference_type,
                    reference_number=reference_number,
                    chunk_index=chunk_index,
                    text=text,
                    extraction_method=extraction_method,
                    chunk_version=chunk_version,
                )
            )
    return chunks

