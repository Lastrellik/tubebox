"""The small public CLI and yt-dlp workflow."""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import urlparse

from .storage import TubeBoxError, check_destination, config_path, initialize, load_config, resolution


def download_format(preference):
    preference = resolution(preference)
    ceiling = 1080 if preference == 'best' else min(int(preference), 1080)
    limit = f'[height<={ceiling}]'
    return f'bv*{limit}+ba/b{limit}'


def download_media(url, stage, preference):
    for attempt in range(2):
        work = stage / f'attempt-{attempt + 1}'
        work.mkdir()
        options = ['--check-formats', '--format-sort', 'res,vcodec:h264,acodec:aac'] if attempt == 0 else []
        try:
            run(['yt-dlp', '--ignore-config', '--no-cache-dir', '--no-playlist', '--no-overwrites',
                 '--socket-timeout', '20', '--format', download_format(preference), *options,
                 '--merge-output-format', 'mkv', '--write-thumbnail', '--convert-thumbnails', 'jpg',
                 '--output', 'video.%(ext)s', '--paths', str(work), '--paths', f'temp:{work}',
                 '--', url], cwd=work)
        except TubeBoxError as exc:
            if attempt == 0 and 'HTTP Error 403' in str(exc):
                print('Preferred stream returned HTTP 403; retrying once with default codec preferences.', file=sys.stderr)
                shutil.rmtree(work)
                continue
            raise
        videos = [path for path in work.glob('video.*')
                  if path.suffix in ('.mp4', '.mkv', '.webm', '.mov', '.flv', '.avi', '.ogv', '.3gp')
                  and path.stem == 'video' and path.is_file() and path.stat().st_size]
        thumb = work / 'video.jpg'
        if len(videos) != 1 or not thumb.is_file() or not thumb.stat().st_size:
            raise TubeBoxError('Download did not produce both a video and a JPEG thumbnail; nothing was added.')
        return videos[0], thumb


def resolution_argument(value):
    try:
        return resolution(value)
    except TubeBoxError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def sanitize(value):
    value = unicodedata.normalize('NFC', str(value))
    value = ''.join('_' if unicodedata.category(c).startswith('C') or c in '<>:"/\\|?*' else c for c in value)
    value = re.sub(r'\s+', ' ', value).strip(' .')
    # Leave room for episode suffixes, extensions, and artwork names on SMB.
    value = value.encode('utf-8')[:180].decode('utf-8', errors='ignore').rstrip(' .')
    if not value:
        raise TubeBoxError('Please supply a name containing letters or numbers.')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + value
    return value


def run(command, capture=False, timeout=None, cwd=None):
    environment = None
    if cwd is not None:
        environment = dict(os.environ, TMPDIR=str(cwd), TEMP=str(cwd), TMP=str(cwd))
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE, timeout=timeout, check=False,
                                cwd=cwd, env=environment)
    except subprocess.TimeoutExpired as exc:
        raise TubeBoxError(f'{command[0]} timed out.') from exc
    if result.returncode:
        detail = (result.stderr or '').strip()
        message = f'{command[0]} failed: {detail or "unknown error"}'
        if command[0] == 'yt-dlp' and 'HTTP Error 403' in detail:
            message += ('\nThe source rejected the media request (HTTP 403). '
                        'Update yt-dlp using its package manager and retry. '
                        'For a Homebrew install: brew update && brew upgrade yt-dlp deno. '
                        'This error does not mean the media destination is unavailable.')
        raise TubeBoxError(message)
    if result.stderr and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.stdout


def dependencies():
    missing = [name for name in ('yt-dlp', 'ffmpeg', 'ffprobe', 'curl') if not shutil.which(name)]
    if missing:
        raise TubeBoxError('Missing dependencies: ' + ', '.join(missing) + '. Install them and try again (see README).')


def metadata(url, channel=False, cwd=None):
    options = ['--flat-playlist', '--playlist-end', '1'] if channel else ['--no-playlist']
    raw = run(['yt-dlp', '--ignore-config', '--no-cache-dir', '--socket-timeout', '20',
               *options, '--dump-single-json', '--', url], capture=True, timeout=60, cwd=cwd)
    try:
        result = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise TubeBoxError('yt-dlp returned invalid metadata.') from exc
    if not isinstance(result, dict) or (not channel and (result.get('_type') in ('playlist', 'multi_video') or 'entries' in result)):
        raise TubeBoxError('Please provide a single video URL, not a playlist or channel.')
    if not channel and not result.get('title'):
        raise TubeBoxError('The source did not provide a video title.')
    return result


def ask(label, default=''):
    value = input(f'{label}' + (f' [{default}]' if default else ' (optional)') + ': ').strip()
    return value or default


def number(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Use a non-negative whole number.') from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError('Use a non-negative whole number.')
    return parsed


def ensure_free(folder, stem):
    # Include alternate extensions and incomplete artwork from older/manual imports.
    for path in folder.iterdir():
        if path.name.casefold() == f'{stem}-thumb.jpg'.casefold() or path.stem.casefold() == stem.casefold():
            raise TubeBoxError(f'An entry named "{stem}" already exists. Choose another --name.')


def copy_exclusive(source, target):
    # Copy only completed files to a hidden sibling, closing it before rename.
    # Reserve the final name exclusively so existing files are never replaced.
    # SMB need not support hard links for this to work.
    descriptor, name = tempfile.mkstemp(prefix='.tubebox-transfer-', suffix='.tmp', dir=target.parent)
    temporary = Path(name)
    reserved = False
    try:
        with os.fdopen(descriptor, 'wb') as output:
            with source.open('rb') as content:
                shutil.copyfileobj(content, output)
        if temporary.stat().st_size != source.stat().st_size:
            raise TubeBoxError(f'Incomplete transfer: {target}')
        with target.open('xb'):
            reserved = True
        temporary.replace(target)
    except BaseException:
        if reserved:
            target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def folder_art(info, stage, thumb):
    result = stage / 'poster.jpg'
    channel_url = info.get('channel_url') or info.get('uploader_url')
    if channel_url:
        try:
            channel = metadata(channel_url, channel=True, cwd=stage)
            thumbnails = channel.get('thumbnails') or []
            url = channel.get('thumbnail') or next((t['url'] for t in reversed(thumbnails) if t.get('url')), None)
            if url:
                source = stage / 'channel-image'
                run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '30',
                     '--proto', '=http,https', '--proto-redir', '=http,https', '--output', str(source), url], cwd=stage)
                run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), '-frames:v', '1', '-y', str(result)], cwd=stage)
                return result
        except TubeBoxError as exc:
            print(f'Channel artwork unavailable; using the video thumbnail. {exc}', file=sys.stderr)
    shutil.copyfile(thumb, result)
    return result


def add(args):
    config = load_config(args.config)
    destination = check_destination(config)
    dependencies()
    if urlparse(args.url).scheme not in ('http', 'https'):
        raise TubeBoxError('Please provide an http or https video URL.')
    # Probe write access without placing downloader work files on the share.
    with tempfile.TemporaryDirectory(prefix='.tubebox-probe-', dir=destination):
        pass
    local_temp = Path(tempfile.gettempdir()).resolve()
    if (local_temp.is_relative_to(destination.resolve()) or
            (config['storage'] == 'network' and local_temp.is_relative_to(Path(config['mount']).resolve()))):
        raise TubeBoxError('The temporary directory is on media storage. Set TMPDIR to a local directory and retry.')
    with tempfile.TemporaryDirectory(prefix='tubebox-', dir=local_temp) as temporary:
        stage = Path(temporary)
        info = metadata(args.url, cwd=stage)
        creator = info.get('channel') or info.get('uploader') or info.get('creator') or 'Videos'
        print(f'Title:   {info["title"]}\nChannel: {creator}')
        folder_name, name = args.folder or creator, args.name or info['title']
        season, episode = args.season, args.episode
        if not args.yes and sys.stdin.isatty():
            folder_name = args.folder or ask('Folder', folder_name)
            name = args.name or ask('Video name', name)
            if season is None:
                answer = ask('Season number')
                season = number(answer) if answer else None
            if episode is None:
                answer = ask('Episode number')
                episode = number(answer) if answer else None
        stem = sanitize(name)
        if season is not None or episode is not None:
            stem += ' - ' + (f'S{season:02d}' if season is not None else '') + (f'E{episode:02d}' if episode is not None else '')
        folder = destination / sanitize(folder_name)
        if folder.is_symlink():
            raise TubeBoxError('The selected folder is a symbolic link. Choose a folder inside the library.')
        if folder.exists():
            ensure_free(folder, stem)
        print(f'Downloading: {stem}')
        video, thumb = download_media(args.url, stage, config['resolution'])
        poster = None if (folder / 'poster.jpg').exists() else folder_art(info, stage, thumb)
        if poster is not None and (not poster.is_file() or not poster.stat().st_size):
            raise TubeBoxError('Folder artwork is empty or missing; nothing was added.')
        check_destination(config)
        created_folder = not folder.exists()
        folder.mkdir(exist_ok=True)
        if folder.is_symlink():
            raise TubeBoxError('The selected folder became a symbolic link.')
        # Serialize TubeBox writers per folder. A hard crash leaves a visible recovery hint.
        lock = folder / '.tubebox-lock'
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise TubeBoxError(f'Folder is busy. If no TubeBox process is running, remove {lock} and retry.') from exc
        published = []
        try:
            ensure_free(folder, stem)
            print(f'Transferring completed files to: {folder}')
            pairs = [(thumb, folder / f'{stem}-thumb.jpg')]
            if poster is not None and not (folder / 'poster.jpg').exists():
                pairs.append((poster, folder / 'poster.jpg'))
            pairs.append((video, folder / f'{stem}{video.suffix}'))
            for source, target in pairs:
                copy_exclusive(source, target)
                published.append(target)
        except BaseException:
            for path in reversed(published):
                path.unlink(missing_ok=True)
            raise
        finally:
            lock.rmdir()
            if created_folder and not any(folder.iterdir()):
                folder.rmdir()
        print(f'Added: {folder / (stem + video.suffix)}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a visual offline video library for Kodi.')
    parser.add_argument('--config', type=Path, default=config_path(), help='Configuration file path')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Save your library destination')
    init.add_argument('destination', nargs='?', type=Path)
    init.add_argument('--local', action='store_true', default=None, help='Explicitly allow local storage instead of a mounted share')
    init.add_argument('--resolution', type=resolution_argument,
                      help='Maximum video height, e.g. 720p or 1080p (all downloads capped at 1080p)')
    download = commands.add_parser('add', help='Download one permitted video with artwork')
    download.add_argument('url')
    download.add_argument('--folder', help='Override the creator folder')
    download.add_argument('--name', help='Override the video title')
    download.add_argument('--season', type=number)
    download.add_argument('--episode', type=number)
    download.add_argument('-y', '--yes', action='store_true', help='Accept defaults without prompts')
    normalizer = commands.add_parser('normalize', help='Normalize existing videos for Pi 3 playback')
    normalizer.add_argument('path', type=Path, help='Video file or directory to scan recursively')
    normalizer.add_argument('--dry-run', action='store_true', help='Inspect and report without modifying media')
    normalizer.add_argument('--verbose', action='store_true', help='Show ffmpeg diagnostic output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            existing = load_config(args.config) if args.config.exists() else {}
            destination = args.destination
            if destination is None:
                default = existing.get('destination', '')
                if not sys.stdin.isatty() and not default:
                    raise TubeBoxError('Supply a destination: tubebox init /path/to/library')
                answer = (input(f'Library destination' + (f' [{default}]' if default else '') + ': ').strip() or default
                          if sys.stdin.isatty() else default)
                if not answer:
                    raise TubeBoxError('A library destination is required.')
                destination = Path(answer)
            preference = args.resolution or existing.get('resolution', '1080')
            if args.resolution is None and sys.stdin.isatty():
                preference = resolution(ask('Maximum resolution (up to 1080p)', preference))
            same_destination = bool(existing) and destination.expanduser().resolve() == Path(existing['destination'])
            local = args.local if args.local is not None else same_destination and existing.get('storage') == 'local'
            config = initialize(args.config, destination, local, preference)
            display_resolution = str(1080 if preference == 'best' else min(int(preference), 1080)) + 'p'
            print(f'Saved configuration: {args.config}\nLibrary: {config["destination"]}\nResolution: {display_resolution}')
        elif args.command == 'normalize':
            from .normalize import normalize
            return normalize(args)
        else:
            add(args)
    except (TubeBoxError, OSError, configparser.Error, argparse.ArgumentTypeError) as exc:
        print(f'tubebox: {exc}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\ntubebox: Cancelled.', file=sys.stderr)
        return 130
    return 0
