"""Validated YouTube caption ingestion without downloading video or audio."""

from collections.abc import Iterable
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlparse

import httpx


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
MAX_TRANSCRIPT_SEGMENTS = 20_000
MAX_TRANSCRIPT_CHARACTERS = 2_000_000
MAX_VIDEO_SECONDS = 12 * 60 * 60


class YouTubeTranscriptError(RuntimeError):
    """Safe user-facing error for unavailable or invalid caption resources."""


@dataclass(frozen=True)
class YouTubeReference:
    video_id: str
    canonical_url: str


@dataclass(frozen=True)
class YouTubeMetadata:
    title: str
    thumbnail_url: str


def parse_youtube_url(value: str) -> YouTubeReference:
    """Accept only public YouTube video URL shapes and return a canonical URL."""
    if not isinstance(value, str) or len(value) > 2_000:
        raise ValueError("Enter a valid YouTube video URL.")
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError("Only HTTPS YouTube video links are supported.")

    video_id = ""
    parts = [part for part in parsed.path.split("/") if part]
    if host == "youtu.be":
        video_id = parts[0] if len(parts) == 1 else ""
    elif parsed.path == "/watch":
        candidates = parse_qs(parsed.query).get("v", [])
        video_id = candidates[0] if len(candidates) == 1 else ""
    elif len(parts) == 2 and parts[0] in {"embed", "shorts", "live"}:
        video_id = parts[1]

    if not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValueError("Enter a direct link to one YouTube video.")
    return YouTubeReference(
        video_id=video_id,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
    )


def fetch_youtube_metadata(
    reference: YouTubeReference, *, client: httpx.Client | None = None
) -> YouTubeMetadata:
    """Load public display metadata without making ingestion depend on it."""
    fallback = YouTubeMetadata(
        title=f"YouTube video {reference.video_id}",
        thumbnail_url=f"https://i.ytimg.com/vi/{reference.video_id}/hqdefault.jpg",
    )
    owns_client = client is None
    active_client = client or httpx.Client(timeout=8.0, follow_redirects=False)
    try:
        response = active_client.get(
            "https://www.youtube.com/oembed",
            params={"url": reference.canonical_url, "format": "json"},
        )
        response.raise_for_status()
        payload = response.json()
        title = " ".join(str(payload.get("title") or "").split())[:300]
        thumbnail = str(payload.get("thumbnail_url") or "").strip()
        if not title:
            return fallback
        if not thumbnail.startswith("https://"):
            thumbnail = fallback.thumbnail_url
        return YouTubeMetadata(title=title, thumbnail_url=thumbnail)
    except (httpx.HTTPError, ValueError, TypeError):
        return fallback
    finally:
        if owns_client:
            active_client.close()


class YouTubeCaptionReader:
    def __init__(self, languages: tuple[str, ...], *, client=None):
        self.languages = languages
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise YouTubeTranscriptError(
                "YouTube caption support is not installed on this server."
            ) from exc
        return YouTubeTranscriptApi()

    def fetch(self, video_id: str) -> list[dict[str, object]]:
        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise YouTubeTranscriptError("The YouTube video identifier is invalid.")
        try:
            transcript: Iterable[object] = self._get_client().fetch(
                video_id, languages=self.languages
            )
            records: list[dict[str, object]] = []
            character_count = 0
            previous_start = 0.0
            for index, snippet in enumerate(transcript, start=1):
                if index > MAX_TRANSCRIPT_SEGMENTS:
                    raise YouTubeTranscriptError(
                        "This video has too many caption segments to process safely."
                    )
                text = " ".join(str(getattr(snippet, "text", "")).split())
                start = float(getattr(snippet, "start"))
                duration = max(0.0, float(getattr(snippet, "duration")))
                end = min(MAX_VIDEO_SECONDS, start + duration)
                if not text:
                    continue
                if start < 0 or start < previous_start or start > MAX_VIDEO_SECONDS:
                    raise YouTubeTranscriptError(
                        "YouTube returned invalid caption timestamps."
                    )
                character_count += len(text)
                if character_count > MAX_TRANSCRIPT_CHARACTERS:
                    raise YouTubeTranscriptError(
                        "This video's captions are too large to process safely."
                    )
                records.append(
                    {
                        "reference_type": "timestamp",
                        "reference_number": len(records) + 1,
                        "text": text,
                        "start_seconds": round(start, 3),
                        "end_seconds": round(max(start, end), 3),
                        "has_text": True,
                        "ocr_applied": False,
                        "extraction_method": "youtube_captions",
                    }
                )
                previous_start = start
        except YouTubeTranscriptError:
            raise
        except Exception as exc:
            raise YouTubeTranscriptError(
                "Captions could not be retrieved for this YouTube video. "
                "The video may be private, restricted, or have captions disabled."
            ) from exc
        if not records:
            raise YouTubeTranscriptError(
                "No readable captions are available for this YouTube video."
            )
        return records
