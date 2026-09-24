# TubeBox

TubeBox is a command-line tool for downloading permitted online videos into
an offline Kodi library. It uses yt-dlp to download videos, groups them by
creator, and saves thumbnails and folder artwork alongside the media.
Downloads and processing run locally before completed files are copied to
your library, including libraries on mounted SMB shares.

```bash
tubebox add "<permitted-video-url>"
```

## Install and Set Up

TubeBox runs on macOS and Linux with Python 3.10 or newer. Install
`yt-dlp`, `ffmpeg` (which includes `ffprobe`), and `curl` first.

On macOS with Homebrew:

```bash
brew install python yt-dlp ffmpeg curl deno
```

On Debian/Ubuntu or Raspberry Pi OS:

```bash
sudo apt update
sudo apt install python3 python3-venv ffmpeg curl pipx
pipx install yt-dlp
pipx ensurepath
```

Open a new terminal after `pipx ensurepath` so `yt-dlp` is on your PATH.
Use an up-to-date yt-dlp: source websites change frequently. See the
[official yt-dlp installation instructions](https://github.com/yt-dlp/yt-dlp#installation)
for other platforms and any additional requirements for your source site.
YouTube also needs a supported JavaScript runtime and yt-dlp's EJS component;
see the [official EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
The Homebrew setup above includes Deno; pipx users should install
`pipx install 'yt-dlp[default]'` instead of the plain yt-dlp package and
install a runtime following that guide.

From this repository, install TubeBox into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
tubebox --help
```

Activate this environment in each new terminal. Alternatively, if you use
`pipx`, run `pipx install .` to make `tubebox` available without activation.
TubeBox itself has no third-party Python runtime dependencies.

Mount your network share and create your library folder on it, then run:

```bash
tubebox init /Volumes/Kodi/YouTube
# Linux example:
# tubebox init /mnt/kodi/YouTube
```

You can also run `tubebox init` and enter the path when prompted. The folder
must already exist. TubeBox does not mount SMB shares or store SMB credentials;
mount the share using your operating system first.

For an intentionally local library, use:

```bash
mkdir -p ~/Videos/TubeBox
tubebox init --local ~/Videos/TubeBox
```

Setup saves `~/.config/tubebox/config.ini` (or
`$XDG_CONFIG_HOME/tubebox/config.ini` when set). It stores the destination,
storage mode, mount path, library identifier, and preferred resolution. A small `.tubebox-library`
marker in the destination identifies the configured library. Rerun `init`
to change the destination; no source code edits are needed.

For a separate configuration, put `--config` before the command:

```bash
tubebox --config ./family.ini init /Volumes/Kodi/YouTube
tubebox --config ./family.ini add "<permitted-video-url>"
```

## Preferred Resolution

Choose a resolution during interactive setup, or save it directly:

```bash
tubebox init /Volumes/Kodi/YouTube --resolution 1080p
# Update the existing library's preference:
tubebox init --resolution 720p
# Use the highest available resolution up to 1080p:
tubebox init --resolution best
```

Every subsequent `tubebox add` uses this setting. New configurations default
to **1080p**. All downloads are capped at 1080p, including older configurations
set to `best` or a higher resolution. Lower configured limits still apply. Enter accepts the current value
during setup. Updating the existing library preserves its destination and
local/network storage mode.

The preference is a maximum video height: `1080p` selects the best available
format up to 1080 pixels high, falling back to a lower resolution when needed.
It does not upscale or resize videos. If all formats exceed the limit or
their heights are unknown, the download fails instead of exceeding the limit;
choose a source with a known resolution within the limit. Existing downloaded videos are not changed.

You can also edit `resolution = 1080` in the `[library]` section of your
config file. Values such as `720`, `1080p`, `1440p`, `2160p`, and `best` are
accepted.

## Frame Rate Cap

`tubebox init` prompts for a maximum frame rate of **30 or 60 fps** and saves
it alongside the resolution preference. Press Enter to keep the displayed
value. The default is **30 fps**, including configurations created before
this setting existed.

Both `add` and `normalize` use the saved cap automatically:

```bash
tubebox init                       # choose the cap interactively
tubebox add "<permitted-video-url>"
tubebox normalize /Volumes/Kodi/YouTube --dry-run
```

For noninteractive setup, use `tubebox init --fps 30`. Override the cap for
one command without changing the saved setting:

```bash
tubebox add "<permitted-video-url>" --fps 60
tubebox normalize movie.mkv --fps 30
```

`add` selects an available source format within both the resolution and frame
rate limits, including on retries. Formats with unknown frame rates are
excluded; if no suitable format exists, the download fails.

`normalize` reduces videos above the cap by dropping frames, preserving
playback speed and copying audio without re-encoding. Videos below the cap
keep their frame rate. Without a configuration file, normalization uses
30 fps; `--config` selects an alternate configuration for either command.
Normalization does not require the configured download destination to be
mounted.

## Example

To add a video you have permission to download:

```bash
tubebox add "https://www.youtube.com/watch?v=..."
```

TubeBox uses the source title and creator as defaults:

```text
Title:   Mars Rover Overview
Channel: NASA

Folder [NASA]:
Video name [Mars Rover Overview]:
Season number (optional):
Episode number (optional):
```

Press Enter to accept the defaults.

TubeBox then creates:

```text
YouTube/
└── NASA/
    ├── poster.jpg
    ├── Mars Rover Overview.mp4
    └── Mars Rover Overview-thumb.jpg
```

The titles shown above are illustrative examples.

## Library Layout

Videos share a creator folder by default. Use `--folder` to group them by
collection or category instead. Each folder has a `poster.jpg`, and each
video has a matching `<video>-thumb.jpg` for browsing in Kodi.

## Automatic Artwork

TubeBox uses artwork exposed by the source whenever possible.

For each video, TubeBox can:

- Download the video's thumbnail
- Convert it to JPEG
- Rename it using Kodi's `-thumb.jpg` convention

For creator/channel folders, TubeBox tries to retrieve available channel artwork and saves it as:

```text
poster.jpg
```

Existing folder artwork is preserved rather than downloaded repeatedly.
If the source does not expose usable creator artwork, TubeBox uses the
video thumbnail for the folder poster. If the video thumbnail cannot be
downloaded and converted, the video is not added.

## Optional Episodes

Season and episode numbers are optional. Without them, files use the video title:

```text
Mars Rover Overview.mp4
Mars Rover Overview-thumb.jpg
```

With `--season 1 --episode 4`, the names include an episode suffix:

```text
Space Science - S01E04.mp4
Space Science - S01E04-thumb.jpg
```

## Local Processing and Network Storage

TubeBox prepares videos locally, then transfers completed files to mounted
network storage.

For example:

```text
/mnt/kodi/YouTube
```

or on macOS:

```text
/Volumes/Kodi/YouTube
```

A Raspberry Pi or other media server can expose its storage over SMB, and TubeBox treats the mounted share like a normal directory.

`tubebox add` handles both processing and transfer automatically. yt-dlp,
ffmpeg, and artwork downloads run entirely inside a local temporary working
directory. They never use the configured media destination as a working
filesystem, avoiding issues with download and conversion operations on
macOS-mounted SMB volumes.

If the configured destination is unavailable, TubeBox fails rather than silently downloading files somewhere else.

In network mode, TubeBox checks that the configured mount is present and
that the library marker matches before downloading and before publishing.
Local mode still requires the existing destination and matching marker.
Network mode expects a separate filesystem mount, as with normal SMB mounts
on macOS and Linux; unusual bind-mount or automount arrangements may need
to be mounted explicitly before setup.

Local working directories use Python's system temporary location (normally
the macOS user temporary directory or `/tmp` on Linux). Keep this location
on local storage; TubeBox rejects a temporary location inside the configured
media destination or its network mount. Local storage needs enough free space
for the video, audio, artwork, and merging/conversion intermediates.

Only after the final video and thumbnail are present and non-empty does
TubeBox create the creator/category directory and transfer files. Copies use
hidden `.tubebox-transfer-*.tmp` names in that directory. After each copy closes
and its size is checked, TubeBox reserves the final name without overwriting
existing files and renames the completed copy into place on the same share.
The rename is atomic on filesystems that support atomic rename; failures
abort the transfer rather than falling back to copying into the final name.

Ordinary download or transfer failures clean up local work and temporary
destination copies and roll back newly added files. Existing video names
are rejected; choose a different `--name` to keep both versions. yt-dlp partial
downloads and ffmpeg intermediate files are never transferred to the share.

An abrupt process kill, power loss, or disconnected share can prevent
cleanup. After checking that no TubeBox process is running, remove any
leftover local `tubebox-*` working directories, destination
`.tubebox-transfer-*.tmp` files, and the affected folder's `.tubebox-lock`
directory. Inspect any empty reserved final filenames before retrying.
Keep the `.tubebox-library` marker. Filesystem writes across video and
artwork are not a single atomic transaction.

## Dependencies

TubeBox uses:

- `yt-dlp`
- `ffmpeg` and `ffprobe`
- Python 3.10+
- `curl`

`yt-dlp` handles media extraction and metadata, while `ffmpeg` handles media and image conversion where necessary.

TubeBox checks for all four external executables before contacting a
video source. Installation commands are in **Install and Set Up** above.

## CLI

The primary interface is:

```bash
tubebox add <url>
```

Accept the creator and title defaults without prompts:

```bash
tubebox add "<permitted-video-url>" --yes
```

Override names or add optional episode numbers:

```bash
tubebox add "<permitted-video-url>" --folder "Space" --name "My Telescope Tour"
tubebox add "<permitted-video-url>" --name "My Astronomy Series" --season 1 --episode 4
```

Season and episode numbers may also be supplied individually. Enter skips
optional numbers in interactive use. Piped/noninteractive commands use
defaults automatically. Playlists and channel URLs are rejected: add one
video at a time. Video URLs must use HTTP or HTTPS.

TubeBox keeps yt-dlp's normal best-video-plus-audio selection with a strict
1080p ceiling (or your lower configured limit). It prefers H.264/AVC video
and AAC audio using codec sorting, and checks selected formats for download
availability. These are preferences, not requirements: Opus and other codecs
remain eligible. Availability checks cannot catch every mid-download failure.

If the preferred download fails with HTTP 403, TubeBox retries once in a
fresh local directory without codec sorting preferences, retaining the same
resolution ceiling. This lets yt-dlp select its normal audio choice, including
Opus. No format IDs, browser cookies, or YouTube login are required.

Separate video/audio streams are merged into MKV by ffmpeg using stream
copying. Already combined videos keep their original container, including
MP4 or WebM. TubeBox does not transcode video or audio or force MP4 output;
Kodi/LibreELEC can use the resulting codecs and containers. TubeBox uses its own
yt-dlp options, ignoring global yt-dlp configuration for predictable
output. Titles, creator folder names, and artwork filenames are converted to
ASCII: emojis are removed and accented letters such as `é` become `e`. This
also applies to custom names and prompt defaults. If cleanup leaves an empty
name, supply `--name` or `--folder` using ASCII letters or numbers. Names are
sanitized for common SMB and Windows restrictions; existing entries are never
overwritten when cleaned names collide.

## Normalize Existing Media for Raspberry Pi 3

Inspect and convert an existing file or recursively process a directory:

```bash
tubebox normalize movie.mkv
tubebox normalize /Volumes/MyDrive/Kids/Movies --dry-run
tubebox normalize /Volumes/MyDrive/Kids
```

This command needs only `ffmpeg` (with libx264) and `ffprobe`; it does not
require `tubebox init`, yt-dlp, or a configured download destination.
It processes files sequentially and reports compatible, normalized, and
failed counts. A failed file does not stop the remaining files. Any failures
produce a nonzero command exit status. Symlinked files/directories and hidden
transfer files are excluded from recursive discovery.

The compatibility target is **H.264/AVC, 8-bit yuv420p, no wider than 1920 pixels
and no taller than 1080 pixels**, within the saved frame rate cap. If the primary video stream already meets
that target, the file is left untouched, regardless of container. Otherwise,
TubeBox explains the incompatibility and automatically tries NVIDIA GPU
encoding (`h264_nvenc`). It tests a one-second preview of the actual staged
input, so having an encoder listed by ffmpeg alone is not enough. If that
preview fails, it reports the reason and retries with CPU encoding (`libx264`).
No GPU model lookup, `nvidia-smi`, or extra Python packages are required.
Other GPU vendors currently use the CPU fallback.

Use an explicit encoder when desired:

```bash
tubebox normalize /mnt/kodi/Movies --encoder nvenc  # Require NVIDIA; fail safely if unavailable
tubebox normalize /mnt/kodi/Movies --encoder cpu    # Always use CPU
```

NVIDIA encoding requires a working NVIDIA driver and ffmpeg built with
`h264_nvenc`. It uses preset `p5`, HQ tuning, VBR with target CQ 20, and no
fixed average bitrate. CPU encoding retains preset `medium` and CRF 20.
CQ and CRF are different quality controls; GPU output can differ in size
and quality from CPU output. The GPU performs video encoding; decoding,
resizing, and pixel format conversion remain on the CPU.
See [NVIDIA's FFmpeg guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html).

Both encoders produce 8-bit `yuv420p` H.264 in MKV. TubeBox preserves
frame timing when within the cap, retains display aspect ratio,
and scales down only as needed (rounding dimensions down to even pixels).
It does not upscale or perform HDR-to-SDR tone mapping.

`--dry-run` reports the requested encoder without testing the GPU or encoding.
Compatible files are skipped without initializing an encoder. Automatic
fallback happens during the preview only: a failure during the full encode
preserves the source and is reported, without starting another long encode.

All audio streams are copied without re-encoding. Supported subtitle streams
(SRT, ASS/SSA, WebVTT, DVD, DVB, and PGS) are copied; MP4 `mov_text` captions
are converted to SRT, which preserves text but can lose styling. Subtitles
are never burned in. Chapters, attachments, language tags, and useful metadata
are carried over. Unsupported subtitle/data streams or extra video/cover
streams are reported, and the source is retained alongside a
`Movie.normalized.mkv` output rather than discarded. A one-second local
encoding/muxing check detects common stream/container problems before the
full encode; unsupported audio muxing fails safely without re-encoding it.

The normal replacement flow is:

1. Inspect the source with ffprobe, using a local working directory.
2. Copy incompatible input to a local temporary workspace and encode there.
3. Probe the finished result: check codec, pixel format, dimensions, duration,
   frame rate, aspect ratio, audio/subtitle tracks, attachments, and chapters.
4. Copy the validated file to a temporary sibling at the destination,
   flush it, and verify its size and SHA-256 checksum.
5. Recheck that the source has not changed, then rename the copy into place.

`Movie.mkv` keeps its filename. Other containers become `Movie.mkv`; the
old file is removed only after installation succeeds. Existing unrelated
output files cause a safe failure. Folder artwork and sidecar files are
untouched. A folder lock prevents simultaneous TubeBox normalizers from
replacing files in the same directory. Avoid editing or moving files with
other programs while normalization runs.

Network storage remains **final storage only**. Neither ffmpeg nor its
intermediates run on SMB, and ffprobe runs with a local working directory.
Local temporary storage needs room for the source copy plus encoded output.
Working files are cleaned up on success, ordinary failures, and Ctrl-C.

Encoding, validation, or copy failures preserve the original. Same-directory
replacement uses filesystem rename semantics; TubeBox never falls back to
copying over the original. If a rename fails or its result cannot be confirmed
(for example, a dropped SMB connection), TubeBox reports the relevant paths
and retains the verified copy where possible for recovery. Inspect both files
before retrying. A hard kill or power loss can leave a local workspace,
`.tubebox-normalize-lock`, or a `.tubebox-normalized-*.mkv` transfer/recovery file;
check that no normalizer is running before cleaning these up.

`--dry-run` probes everything and reports proposed outputs without copying
sources, encoding, or changing media. During conversion, progress includes
percentage, encoded time, speed, and ETA when ffmpeg provides them. Use
`--verbose` to show raw ffmpeg diagnostics.

## Troubleshooting

If both download attempts fail with `HTTP Error 403: Forbidden`, the source
rejected the requests. Changing the library path or rerunning `init` will not fix that
response. Update your downloader and retry. For Homebrew installations:

```bash
brew update
brew upgrade yt-dlp deno
```

TubeBox displays yt-dlp warnings, including warnings from metadata retrieval.
If the problem persists after updating, those diagnostics help distinguish
source restrictions from extractor problems. TubeBox does not automatically
read browser cookies or change your installed tools.

## Development and Tests

Run directly from the checkout without installing TubeBox:

```bash
python3 -m tubebox --help
python3 -m unittest discover -s tests -v
```

The tests use Python's standard library and simulated downloader output;
they require no network access or downloaded media. They cover config,
unavailable mounts, library identity, naming, duplicate protection,
artwork preservation, resolution configuration, and cleanup after failures.
When yt-dlp is installed, additional tests exercise its real format selection
using synthetic metadata, without network access or media downloads; otherwise
those tests are skipped. They do not replace
an end-to-end check with your actual mounted share and a video you own
or are permitted to download.

Normalization tests cover compatibility, stream preservation, dry runs,
source safety, and transfer failures. When ffmpeg/ffprobe are installed,
additional tests generate tiny synthetic videos locally to verify real
10-bit conversion, downscaling, fractional frame rates, multiple audio and
subtitle tracks, chapters, metadata, and `mov_text` conversion. These temporary
fixtures are deleted after each test and are never shipped with TubeBox.

To include real NVIDIA GPU tests (synthetic local media only):

```bash
TUBEBOX_TEST_NVENC=1 python3 -m unittest discover -s tests -v
```

## Kodi

Point Kodi at the library directory or its network share to browse and play
the downloaded videos. TubeBox prepares the files and artwork; Kodi handles
playback.

## Content and Copyright

TubeBox is a media-management tool. It does not include or distribute downloaded media.

TubeBox is intended for content that the user has the right or permission to download and store, such as:

- Content created by the user
- Public-domain content
- Appropriately licensed content
- Content for which the copyright holder has granted permission
- Other content the user is legally entitled to download and store

Users are responsible for determining whether they have permission to download particular content and for complying with applicable laws, licenses, and service terms.

Examples in this README are illustrative and do not imply that every video hosted by a particular service, channel, or organization has the same copyright or licensing status.

## License

TubeBox is licensed under the MIT License.
