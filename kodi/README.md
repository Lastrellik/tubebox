# TubeBox Kodi add-on

`script.tubebox.youtube/` contains the installed custom Kodi app copied from
the LibreELEC Pi on 2026-10-11. It includes its Python source, window layout,
and logo. Old source backups, Python caches, playback databases, and media
are excluded.

The preserved version has a random-video row, a recently viewed row, and
buttons to refresh the choices or browse the media folders.
`watch_history.py` reads Kodi's local playback database; it contains no
viewing-history data itself.

## Configuration

The media location is currently set by `ROOT` in `main.py`:

```python
ROOT = Path('/media/MyDrive/Kids/YouTube')
```

Change that path for a different installation. The app requires Kodi's
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
