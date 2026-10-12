# TubeBox Kodi add-on

`script.tubebox.youtube/` contains the installed custom Kodi app copied from
the LibreELEC Pi on 2026-10-11. It includes its Python source, window layout,
and logo. Old source backups, Python caches, playback databases, and media
are excluded.

The app defaults to two random-video rows with 25 videos each, plus buttons
to refresh the choices or browse folders. Videos do not repeat across rows.
Small libraries are shared between the rows without padding with duplicates.
**More choices** reshuffles both rows, favoring videos outside the previous
selection. Choices remain stable during playback and ordinary browsing;
opening the app again creates a fresh selection. This is variety within a
session, not a persistent rule excluding every previously watched video.

## Configuration

Edit `script.tubebox.youtube/config.json`, then deploy and reopen the app:

```json
{
  "media_directory": "/media/MyDrive/Kids/YouTube",
  "rows": [
    {"type": "random", "label": "Pick a video", "count": 25},
    {"type": "random", "label": "More to explore", "count": 25}
  ]
}
```

The layout supports exactly two rows. Each has a label, a count from 1 to
100, and a type: `random` or `recently_watched`. Both default to `random`;
the playback database is not queried in this configuration. If enabled,
history is read when rebuilding the rows (opening the app, pressing More
choices, or discovering library changes). History picks are reserved before
random picks to prevent duplicates. Configuration lives alongside the code,
not in Kodi's Settings UI; replacing the add-on also replaces this file.

Change the media path for a different installation. The app requires Kodi's
Python APIs and cannot run as a standalone desktop Python program.
An unavailable media directory produces a notification, not a local fallback.

## Package and install

From this directory, create an installable ZIP with the add-on directory
at its root:

```sh
mkdir -p ../dist
zip -r ../dist/script.tubebox.youtube.zip script.tubebox.youtube \
  -x '*/__pycache__/*' '*.pyc' '*.pyo'
```

Install using Kodi's **Add-ons → Install from zip file**. The installed
directory on LibreELEC is:

```text
/storage/.kodi/addons/script.tubebox.youtube/
```

For future changes, edit the repository copy first and deploy the changed
files to that directory after backing up the installed version. Close and
reopen the custom app to load updated source/layout files; copying this
snapshot into the repository does not modify the running Pi.
