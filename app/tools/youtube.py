"""YouTube transcript tool — downloads transcripts for one or more YouTube videos."""

import argparse
import json
import re
import sys
from pathlib import Path

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
        description="Download transcripts from YouTube videos."
    )
    parser.add_argument(
        "videos",
        nargs="+",
        metavar="VIDEO",
        help="YouTube URL(s) or video ID(s)",
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

    output_dir = Path(args.output_dir)
    errors = []

    for video_input in args.videos:
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
