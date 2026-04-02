# youtube-transcript

Download transcripts from YouTube videos, or list recent videos from a channel.

## List recent videos from a channel

```bash
mt-butterfly-youtube --list-channel <CHANNEL> [--since <DURATION>] [--format json]
```

`<CHANNEL>` can be a YouTube channel URL, a handle (`@name`), or a bare channel ID (`UC...`).

### Examples

List videos from a channel published in the last 24 hours:
```bash
mt-butterfly-youtube --list-channel @ThePrimeagen --since 24h
```

List videos from the last 7 days in JSON format:
```bash
mt-butterfly-youtube --list-channel https://www.youtube.com/@firaborrego --since 7d --format json
```

List videos from multiple channels:
```bash
mt-butterfly-youtube --list-channel @channel1 @channel2 --since 48h
```

Output (text mode): one line per video with `video_id  published_date  title`.

### Typical workflow for summarizing recent channel videos

1. **List** recent videos: `mt-butterfly-youtube --list-channel @channel --since 24h`
2. **Download** transcripts for the video IDs from step 1: `mt-butterfly-youtube <ID1> <ID2> --print`
3. **Summarize** the transcripts and send via email.

## Download transcripts

```
mt-butterfly-youtube [options] <VIDEO> [<VIDEO> ...]
```

`<VIDEO>` can be a full YouTube URL or a bare 11-character video ID.

### Examples

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

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `TARGET` | — | Video URL(s)/ID(s), or channel URL(s)/handle(s) with `--list-channel` |
| `--list-channel` | off | List recent videos from channel(s) instead of downloading transcripts |
| `--since` | — | Filter videos by recency (e.g. `24h`, `7d`). Only with `--list-channel` |
| `--output-dir` / `-o` | `.` | Directory where transcript files are saved |
| `--format` / `-f` | `txt` | Output format: `txt` or `json` |
| `--print` / `-p` | off | Print to stdout instead of writing a file |

## Notes

- Do NOT pass `--lang`. The tool auto-selects the transcript language.
- The RSS feed returns the ~15 most recent videos per channel.
- No API key or credentials required — works with public channels and videos.
- Exit code is `1` if any target failed, `0` if all succeeded.
