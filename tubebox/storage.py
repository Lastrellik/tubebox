"""Destination checks kept separate from download and CLI behavior."""
import configparser
import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
import tempfile
import uuid


class TubeBoxError(Exception):
    pass


def file_identity(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise TubeBoxError('Source is no longer a regular file; refusing replacement.')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.digest()


def install_normalized(output, source, target, identity, keep_source=False):
    """Copy, verify, then rename on the destination filesystem. Never copy over source."""
    if file_identity(source) != identity:
        raise TubeBoxError('Source changed while encoding; refusing replacement.')
    lock = source.parent / '.tubebox-normalize-lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise TubeBoxError(f'Folder is busy. If no normalization is running, remove {lock} and retry.') from None
    temporary = None
    retain_copy = False
    reserved = False
    try:
        if target != source and os.path.lexists(target):
            raise TubeBoxError('Output already exists; refusing to overwrite it.')
        descriptor, name = tempfile.mkstemp(prefix='.tubebox-normalized-', suffix='.mkv', dir=source.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, 'wb') as destination:
            with output.open('rb') as content:
                shutil.copyfileobj(content, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if temporary.stat().st_size != output.stat().st_size or file_digest(temporary) != file_digest(output):
            raise TubeBoxError('Destination copy verification failed; original preserved.')
        temporary.chmod(stat.S_IMODE(source.stat().st_mode))
        if file_identity(source) != identity:
            raise TubeBoxError('Source changed during transfer; original preserved.')
        if target != source:
            with target.open('xb'):
                reserved = True
        try:
            # Both paths are on the same filesystem. No destructive copy fallback.
            os.replace(temporary, target)
        except OSError as exc:
            retain_copy = True
            raise TubeBoxError(f'Could not confirm atomic replacement. Inspect {target}; '
                               f'completed copy may remain at {temporary}. Original was not explicitly deleted.') from exc
        if target != source and not keep_source:
            try:
                if file_identity(source) != identity:
                    return f'Normalized file saved: {target}; source changed and was retained: {source}'
                source.unlink()
            except OSError:
                return f'Normalized file saved: {target}; could not remove original, retained: {source}'
        return f'Complete: {target}' + (f'; original retained: {source}' if keep_source else '')
    finally:
        # Keep a fully verified copy on rename failure; never discard useful recovery media.
        if temporary is not None and temporary.exists() and not retain_copy:
            temporary.unlink()
        if reserved and target.exists() and target.stat().st_size == 0:
            target.unlink()
        lock.rmdir()


def resolution(value):
    value = str(value).strip().lower()
    if value == 'best':
        return value
    if not re.fullmatch(r'[1-9][0-9]*p?', value):
        raise TubeBoxError('Resolution must be a positive height such as 720p or 1080p, or best (capped at 1080p).')
    return value.removesuffix('p')


def fps_limit(value):
    value = str(value).strip()
    if value not in ('30', '60'):
        raise TubeBoxError('Frame rate cap must be 30 or 60 fps.')
    return int(value)


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'tubebox' / 'config.ini'


def enclosing_mount(path):
    for candidate in (path, *path.parents):
        if candidate.is_mount():
            return candidate
    raise TubeBoxError('Cannot determine the destination mount.')


def known_local_mount(mount):
    """Recognize Linux local mounts; keep conservative behavior when unknown."""
    try:
        entries = Path('/proc/self/mountinfo').read_text().splitlines()
    except OSError:
        return False
    for entry in reversed(entries):
        fields = entry.split()
        mount_path = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
        if Path(mount_path) == mount:
            filesystem = fields[fields.index('-') + 1]
            return filesystem in {'tmpfs', 'ramfs', 'ext2', 'ext3', 'ext4', 'btrfs',
                                  'xfs', 'zfs', 'f2fs', 'vfat', 'exfat', 'ntfs3', 'overlay'}
    return False


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
        config['fps'] = str(fps_limit(config.get('fps', '30')))
    except (KeyError, ValueError) as exc:
        raise TubeBoxError(f'Invalid configuration: {exc}. Run tubebox init again.') from exc
    return config


def initialize(path, destination, local=False, preferred_resolution='1080', fps=30):
    preferred_resolution = resolution(preferred_resolution)
    fps = fps_limit(fps)
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
                  mount=str(mount), library_id=library_id, resolution=preferred_resolution, fps=str(fps))
    check_destination(config)
    # Probe actual writes; access() is unreliable on network filesystems.
    # SMB servers may refuse unlinking an open file (TemporaryFile does this).
    descriptor, name = tempfile.mkstemp(prefix='.tubebox-probe-', dir=destination)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(b'TubeBox write check\n')
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        Path(name).unlink()
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
