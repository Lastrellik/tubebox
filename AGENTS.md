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
