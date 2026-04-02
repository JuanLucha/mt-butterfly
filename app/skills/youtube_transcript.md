# youtube-transcript

Download transcripts from YouTube videos using the project's YouTube CLI tool.

## Usage

```
mt-butterfly-youtube [options] <VIDEO> [<VIDEO> ...]
```

`<VIDEO>` can be a full YouTube URL or a bare 11-character video ID.

## Examples

Download transcript of a single video (plain text, saved to current directory):
```bash
mt-butterfly-youtube https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

Download as JSON with timestamps:
```bash
mt-butterfly-youtube dQw4w9WgXcQ --format json --output-dir /tmp/transcripts
```

Print transcript to stdout (useful for piping or reading inline):
```bash
mt-butterfly-youtube dQw4w9WgXcQ --print
```

Download multiple videos:
```bash
mt-butterfly-youtube <ID1> <ID2> <ID3> --output-dir ./transcripts
```

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `VIDEO` | — | YouTube URL(s) or video ID(s) (one or more) |
| `--output-dir` / `-o` | `.` | Directory where transcript files are saved |
| `--format` / `-f` | `txt` | Output format: `txt` (plain text) or `json` (with timestamps) |
| `--print` / `-p` | off | Print to stdout instead of writing a file |

## Output files

- **txt**: `<video_id>.txt` — plain text, all segments joined with spaces.
- **json**: `<video_id>.json` — includes `text`, `segments` (with `start`/`duration`), `language`, `language_code`, `is_generated`.

## Notes

- Do NOT pass `--lang`. The tool auto-selects the transcript language.
- Prefers manually created transcripts; falls back to auto-generated if none exist.
- Transcripts disabled or unavailable videos are reported as errors; other videos in the batch still proceed.
- Exit code is `1` if any video failed, `0` if all succeeded.
- No credentials or configuration required — works with any public video that has transcripts enabled.
