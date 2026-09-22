# TubeBox Development Instructions

## Product goal

TubeBox creates a curated, visual, kid-friendly offline Kodi
library from online videos the user is permitted to download.

The primary UX goal is simplicity.

A normal workflow should require little more than:

    tubebox add <url>

## Core behavior

- Use yt-dlp for media extraction.
- Use ffmpeg when conversion is required.
- Default folder name to the channel/creator.
- Default video name to the source title.
- Allow both defaults to be overridden.
- Download the source thumbnail.
- Store video artwork as `<video>-thumb.jpg`.
- Store folder artwork as `poster.jpg`.
- Do not redownload poster.jpg if one already exists.
- Season and episode numbers are optional.
- Do not force arbitrary videos into TV-show semantics.

## Storage

TubeBox primarily targets mounted network storage such as SMB.

Never silently fall back to local storage if the configured
network destination is unavailable.

Example:

    /mnt/kodi/YouTube/
        NASA/
            poster.jpg
            Mars Rover Overview.mp4
            Mars Rover Overview-thumb.jpg

Do not create a separate directory for every video.

Network storage is FINAL STORAGE ONLY. Run downloads, ffmpeg conversion,
and intermediate processing in local temporary directories. ffprobe may
read a source on the share, but its working directory must be local.
Copy only completed, validated output to temporary destination names and
rename on the destination filesystem; never encode directly onto SMB.

## Existing Media Normalization

- Provide `tubebox normalize <file-or-directory>` and `--dry-run`.
- Recursively inspect supported video files and process them sequentially.
- Skip compatible primary video streams without modifying the source:
  H.264/AVC, 8-bit yuv420p, width <=1920 and height <=1080.
- Normalize incompatible video using libx264, preset medium, CRF 20,
  yuv420p, and MKV output. Never upscale; preserve aspect ratio and timing.
- Copy every supported audio/subtitle stream, chapters, attachments, and
  useful metadata. Report unsupported streams before a long encode and
  retain the original when a stream cannot be preserved.
- Stage source and encoding locally. Validate completed output with
  ffprobe, including compatibility, duration, and preserved streams.
- Verify the final destination copy before replacing any original.
  Detect changed sources and never overwrite unrelated files. If rename
  cannot be confirmed, retain recovery output and report its path.
- Dry run inspects and reports only; no encoding or media modification.
- Show progress and a summary; failures preserve originals and do not
  prevent the remaining directory entries from being inspected.

## UX

Favor sensible defaults over configuration.

Interactive prompts should allow Enter to accept the default.

Keep the basic workflow usable by someone who does not understand
Kodi naming conventions, yt-dlp, ffmpeg, or SMB.

## Reliability

- Sanitize filenames.
- Check dependencies.
- Detect unavailable destinations before downloading.
- Avoid leaving broken library entries after failures.
- Handle yt-dlp failures cleanly.
- Do not overwrite existing media unexpectedly.

## Development

Prefer simple, readable implementations over clever abstractions.

Keep platform-specific filesystem behavior isolated where practical.

Do not add dependencies unless they provide a meaningful benefit.

## Legal

Do not include copyrighted example media in the repository.

Documentation examples should use clearly permitted, public-domain,
user-owned, or appropriately licensed content.

TubeBox itself should not ship downloaded media.
