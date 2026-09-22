"""Destination checks kept separate from download and CLI behavior."""
import configparser
import os
import re
from pathlib import Path
import tempfile
import uuid


class TubeBoxError(Exception):
    pass


def resolution(value):
    value = str(value).strip().lower()
    if value == 'best':
        return value
    if not re.fullmatch(r'[1-9][0-9]*p?', value):
        raise TubeBoxError('Resolution must be a positive height such as 720p or 1080p, or best (capped at 1080p).')
    return value.removesuffix('p')


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'tubebox' / 'config.ini'


def enclosing_mount(path):
    for candidate in (path, *path.parents):
        if candidate.is_mount():
            return candidate
    raise TubeBoxError('Cannot determine the destination mount.')


def check_destination(config):
    destination = Path(config['destination'])
    if not destination.is_absolute() or not destination.is_dir():
        raise TubeBoxError(f'Destination unavailable: {destination}. Mount your storage and try again.')
    if config['storage'] == 'network':
        mount = Path(config['mount'])
        if mount == Path(mount.anchor) or not mount.is_mount() or not destination.is_relative_to(mount):
            raise TubeBoxError(f'Network mount unavailable: {mount}. Mount your storage and try again.')
    marker = destination / '.tubebox-library'
    if marker.read_text().strip() != config['library_id']:
        raise TubeBoxError('Destination identity changed. Run tubebox init for this library.')
    return destination


def load_config(path):
    parser = configparser.ConfigParser(interpolation=None)
    if not path.is_file():
        raise TubeBoxError('Run tubebox init first to choose your library destination.')
    parser.read(path)
    try:
        config = dict(parser['library'])
        for key in ('destination', 'storage', 'mount', 'library_id'):
            if key not in config:
                raise ValueError(f'missing {key}')
        if config['storage'] not in ('network', 'local'):
            raise ValueError('storage must be network or local')
        # Accept older configurations; the downloader enforces its 1080p ceiling.
        config['resolution'] = resolution(config.get('resolution', 'best'))
    except (KeyError, ValueError) as exc:
        raise TubeBoxError(f'Invalid configuration: {exc}. Run tubebox init again.') from exc
    return config


def initialize(path, destination, local=False, preferred_resolution='1080'):
    preferred_resolution = resolution(preferred_resolution)
    destination = destination.expanduser().resolve()
    # Never create a missing destination: it may be an unmounted share.
    if not destination.is_dir():
        raise TubeBoxError(f'Destination must already exist: {destination}. Mount storage and create the library folder first.')
    mount = enclosing_mount(destination)
    if not local and mount == Path(mount.anchor):
        raise TubeBoxError('No separate mount found. Mount your network share first, or use --local for intentional local storage.')
    marker = destination / '.tubebox-library'
    try:
        with marker.open('x') as handle:
            handle.write(str(uuid.uuid4()) + '\n')
    except FileExistsError:
        pass
    library_id = marker.read_text().strip()
    if not library_id:
        raise TubeBoxError(f'Empty library marker: {marker}')
    config = dict(destination=str(destination), storage='local' if local else 'network',
                  mount=str(mount), library_id=library_id, resolution=preferred_resolution)
    check_destination(config)
    # Probe actual writes; access() is unreliable on network filesystems.
    with tempfile.TemporaryFile(dir=destination):
        pass
    parser = configparser.ConfigParser(interpolation=None)
    parser['library'] = config
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            parser.write(handle)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return config
