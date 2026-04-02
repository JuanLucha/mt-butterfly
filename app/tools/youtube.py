"""YouTube transcript tool — downloads transcripts for one or more YouTube videos.

Also supports listing recent videos from a channel via its RSS feed.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, UTC
from pathlib import Path

import httpx

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


def extract_video_id(url_or_id: str) -> str:
    """Return the 11-character video ID from a URL or a bare ID."""
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    # Assume bare ID
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    raise ValueError(f"Cannot parse video ID from: {url_or_id!r}")


def fetch_transcript(
    video_id: str,
    languages: list[str] | None = None,
    preserve_formatting: bool = False,
) -> dict:
    """
    Fetch the transcript for a single video.

    Returns a dict with:
        video_id: str
        language: str
        language_code: str
        is_generated: bool
        text: str            — full plain-text concatenation
        segments: list[dict] — raw [{text, start, duration}, ...]
    """
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    if languages:
        transcript = transcript_list.find_transcript(languages)
    else:
        # Prefer manually created; fall back to auto-generated
        try:
            transcript = transcript_list.find_manually_created_transcript(
                [t.language_code for t in transcript_list]
            )
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(
                [t.language_code for t in transcript_list]
            )

    fetched = transcript.fetch(preserve_formatting=preserve_formatting)
    segments = [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]
    full_text = " ".join(s["text"].replace("\n", " ") for s in segments)

    return {
        "video_id": video_id,
        "language": transcript.language,
        "language_code": transcript.language_code,
        "is_generated": transcript.is_generated,
        "text": full_text,
        "segments": segments,
    }


def resolve_channel_id(channel_input: str) -> str:
    """Resolve a channel URL, handle (@name), or bare ID to a channel_id.

    Supported formats:
      - https://www.youtube.com/channel/UC...
      - https://www.youtube.com/@handle
      - @handle
      - bare channel ID (UC...)
    """
    # Direct channel ID
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_input):
        return channel_input

    # URL with /channel/UC...
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", channel_input)
    if m:
        return m.group(1)

    # Handle: @name or URL containing @name
    handle = None
    m = re.search(r"(@[\w.-]+)", channel_input)
    if m:
        handle = m.group(1)
    if not handle:
        raise ValueError(f"Cannot parse channel from: {channel_input!r}")

    # Resolve handle by fetching the channel page and extracting channel_id.
    # The SOCS cookie bypasses the EU consent page that would otherwise block scraping.
    url = f"https://www.youtube.com/{handle}"
    resp = httpx.get(url, follow_redirects=True, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": "SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODI5LjA3X3AxGgJlbiACGgYIgOupmQY",
    })
    resp.raise_for_status()

    m = re.search(r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', resp.text)
    if m:
        return m.group(1)
    raise ValueError(f"Could not resolve channel ID for {channel_input!r}")


_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def fetch_channel_videos(channel_id: str, since: timedelta | None = None) -> list[dict]:
    """Fetch recent videos from a channel's RSS feed.

    Returns a list of dicts: {video_id, title, published, url}
    sorted by published date descending.
    """
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = httpx.get(feed_url, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    cutoff = datetime.now(UTC) - since if since else None
    videos = []

    for entry in root.findall("atom:entry", _ATOM_NS):
        video_id_el = entry.find("yt:videoId", _ATOM_NS)
        title_el = entry.find("atom:title", _ATOM_NS)
        published_el = entry.find("atom:published", _ATOM_NS)

        if video_id_el is None or title_el is None or published_el is None:
            continue

        published_str = published_el.text
        # Parse ISO 8601: 2024-01-15T12:00:00+00:00
        published = datetime.fromisoformat(published_str)

        if cutoff and published < cutoff:
            continue

        videos.append({
            "video_id": video_id_el.text,
            "title": title_el.text,
            "published": published_str,
            "url": f"https://www.youtube.com/watch?v={video_id_el.text}",
        })

    return videos


def parse_since(since_str: str) -> timedelta:
    """Parse a human duration like '24h', '2d', '48h' into a timedelta."""
    m = re.fullmatch(r"(\d+)\s*(h|d)", since_str.strip().lower())
    if not m:
        raise ValueError(f"Invalid --since format: {since_str!r}. Use e.g. '24h' or '7d'.")
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


def save_transcript(result: dict, output_dir: Path, fmt: str) -> Path:
    """Save a transcript result to disk. Returns the file path written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    vid = result["video_id"]
    if fmt == "json":
        out = output_dir / f"{vid}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    else:  # txt
        out = output_dir / f"{vid}.txt"
        out.write_text(result["text"])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download transcripts from YouTube videos, or list recent videos from a channel."
    )
    parser.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="YouTube video URL(s)/ID(s), or channel URL(s)/handle(s)/@name(s) when --list-channel is used",
    )
    parser.add_argument(
        "--list-channel",
        action="store_true",
        help="List recent videos from the given channel(s) instead of downloading transcripts",
    )
    parser.add_argument(
        "--since",
        metavar="DURATION",
        default=None,
        help="Only list videos published within this duration (e.g. 24h, 7d). Only used with --list-channel.",
    )
    parser.add_argument(
        "--lang",
        nargs="+",
        metavar="LANG",
        default=None,
        help="Preferred language codes in order (e.g. --lang es en). "
             "Defaults to manually-created transcript in any language.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        metavar="DIR",
        default=".",
        help="Directory to save transcript files (default: current directory)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["txt", "json"],
        default="txt",
        help="Output format: txt (plain text) or json (with timestamps). Default: txt",
    )
    parser.add_argument(
        "--print",
        "-p",
        action="store_true",
        help="Print transcript to stdout instead of saving to a file",
    )
    args = parser.parse_args()

    if args.list_channel:
        _main_list_channel(args)
    else:
        _main_transcript(args)


def _main_list_channel(args) -> None:
    since = parse_since(args.since) if args.since else None
    errors = []

    for target in args.targets:
        try:
            channel_id = resolve_channel_id(target)
        except (ValueError, httpx.HTTPError) as e:
            print(f"[ERROR] {target}: {e}", file=sys.stderr)
            errors.append(target)
            continue

        try:
            videos = fetch_channel_videos(channel_id, since=since)
        except httpx.HTTPError as e:
            print(f"[ERROR] Failed to fetch feed for {channel_id}: {e}", file=sys.stderr)
            errors.append(target)
            continue

        if args.format == "json":
            print(json.dumps({"channel_id": channel_id, "videos": videos}, ensure_ascii=False, indent=2))
        else:
            if not videos:
                label = f" (since {args.since})" if args.since else ""
                print(f"[INFO] No videos found for {channel_id}{label}")
            for v in videos:
                print(f"{v['video_id']}  {v['published']}  {v['title']}")

    if errors:
        sys.exit(1)


def _main_transcript(args) -> None:
    output_dir = Path(args.output_dir)
    errors = []

    for video_input in args.targets:
        try:
            video_id = extract_video_id(video_input)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            errors.append(video_input)
            continue

        try:
            result = fetch_transcript(video_id, languages=args.lang)
        except VideoUnavailable:
            print(f"[ERROR] Video unavailable: {video_id}", file=sys.stderr)
            errors.append(video_id)
            continue
        except TranscriptsDisabled:
            print(f"[ERROR] Transcripts disabled: {video_id}", file=sys.stderr)
            errors.append(video_id)
            continue
        except NoTranscriptFound as e:
            print(f"[ERROR] No transcript found for {video_id}: {e}", file=sys.stderr)
            errors.append(video_id)
            continue

        if args.print:
            if args.format == "json":
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result["text"])
        else:
            path = save_transcript(result, output_dir, args.format)
            lang_info = f"{result['language']} ({'auto' if result['is_generated'] else 'manual'})"
            print(f"[OK] {video_id} → {path}  [{lang_info}]")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
