"""Inspect and safely normalize existing media for Raspberry Pi 3 playback."""
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .storage import TubeBoxError, enclosing_mount, install_normalized, file_identity, known_local_mount, load_config, fps_limit

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.m4v', '.mov', '.avi', '.webm', '.mpg', '.mpeg', '.ts', '.m2ts', '.mts', '.wmv', '.flv', '.ogv', '.vob', '.3gp'}
COPY_SUBTITLES = {'subrip', 'ass', 'ssa', 'webvtt', 'dvd_subtitle', 'dvb_subtitle', 'hdmv_pgs_subtitle'}
SCALE = "scale=w='trunc(iw*min(1,min(1920/iw,1080/ih))/2)*2':h='trunc(ih*min(1,min(1920/iw,1080/ih))/2)*2'"


def environment(work):
    return dict(os.environ, TMPDIR=str(work), TEMP=str(work), TMP=str(work))


def probe(path, work):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-show_chapters', '-of', 'json', str(path)],
                            cwd=work, env=environment(work), capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise TubeBoxError(f'ffprobe failed: {result.stderr.strip()[-2000:]}')
    try:
        info = json.loads(result.stdout)
        primary_video(info)
        return info
    except (ValueError, TypeError, KeyError) as exc:
        raise TubeBoxError('ffprobe returned invalid video information.') from exc


def primary_video(info):
    videos = [s for s in info.get('streams', []) if s.get('codec_type') == 'video'
              and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise TubeBoxError('No video stream found.')
    return next((s for s in videos if s.get('disposition', {}).get('default')), videos[0])


def frame_rate(stream):
    # r_frame_rate may describe a container time base, especially for short clips.
    for key in ('avg_frame_rate', 'r_frame_rate'):
        rate = ratio(stream.get(key))
        if math.isfinite(rate) and rate > 0:
            return rate
    raise TubeBoxError('Cannot determine video frame rate safely; original will be preserved.')


def reasons(stream, fps=30):
    result = []
    if stream.get('codec_name') != 'h264':
        result.append(stream.get('codec_name', 'unknown codec').upper())
    if stream.get('pix_fmt') != 'yuv420p':
        result.append(stream.get('pix_fmt', 'unknown pixel format'))
    width, height = stream.get('width', 0), stream.get('height', 0)
    if not width or not height:
        raise TubeBoxError('Video dimensions are missing.')
    if width > 1920 or height > 1080:
        result.append(f'{width}x{height} exceeds 1920x1080')
    rate = frame_rate(stream)
    if rate > fps_limit(fps):
        result.append(f'{rate:.3f} fps exceeds {fps} fps')
    return result


def duration(info):
    stream = primary_video(info)
    for value in (stream.get('duration'), info.get('format', {}).get('duration')):
        try:
            value = float(value)
            if math.isfinite(value) and value > 0:
                return value
        except (TypeError, ValueError):
            pass
    raise TubeBoxError('Cannot determine duration safely; original will be preserved.')


def stream_plan(info):
    """Preserve all audio/attachments and supported subtitles, explaining omissions."""
    video = primary_video(info)
    maps = ['-map', f'0:{video["index"]}', '-map', '0:a?', '-map', '0:t?']
    conversions, warnings = [], []
    subtitle_codecs = []
    for stream in info.get('streams', []):
        kind, codec = stream.get('codec_type'), stream.get('codec_name')
        if kind == 'subtitle':
            if codec in COPY_SUBTITLES or codec == 'mov_text':
                maps += ['-map', f'0:{stream["index"]}']
                if codec == 'mov_text':
                    conversions += [f'-c:s:{len(subtitle_codecs)}', 'srt']
                subtitle_codecs.append('subrip' if codec == 'mov_text' else codec)
            else:
                warnings.append(f'Subtitle stream {stream["index"]} ({codec}) is unsupported in MKV; keeping the original too.')
        elif kind == 'video' and stream['index'] != video['index']:
            warnings.append(f'Additional video/cover stream {stream["index"]} is not normalized; keeping the original too.')
        elif kind not in ('video', 'audio', 'attachment', 'subtitle'):
            warnings.append(f'Stream {stream["index"]} ({kind}) cannot be preserved; keeping the original too.')
    return maps, conversions, subtitle_codecs, warnings


def encode_command(source, output, info, preview=False, encoder='cpu', fps=30):
    maps, conversions, _, _ = stream_plan(info)
    if encoder == 'nvenc':
        video_options = ['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq',
                         '-rc', 'vbr', '-cq', '20', '-b:v', '0']
    elif encoder == 'cpu':
        video_options = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '20']
    else:
        raise TubeBoxError(f'Unknown encoder: {encoder}')
    filters = SCALE
    if frame_rate(primary_video(info)) > fps_limit(fps):
        filters += f',fps=fps={fps_limit(fps)}'
    command = ['ffmpeg', '-nostdin', '-hide_banner', '-xerror', '-noautorotate', '-i', str(source),
               *maps, '-map_metadata', '0', '-map_chapters', '0', '-c', 'copy',
               *video_options, '-pix_fmt', 'yuv420p',
               '-vf', filters, '-fps_mode:v', 'passthrough', '-c:a', 'copy', '-c:s', 'copy', *conversions]
    if preview:
        command += ['-t', '1']
    return command + ['-f', 'matroska', '-n', str(output)]


def select_encoder(source, info, work, total, requested, verbose=False, fps=30):
    """Test the actual input and stream mappings, not just advertised encoders."""
    if requested not in ('auto', 'cpu', 'nvenc'):
        raise TubeBoxError(f'Unknown encoder: {requested}')
    candidates = ('nvenc', 'cpu') if requested == 'auto' else (requested,)
    preview = work / 'preview.mkv'
    for candidate in candidates:
        print(f'      Checking {candidate} encoder and stream/container compatibility...', flush=True)
        try:
            encode(encode_command(source, preview, info, preview=True, encoder=candidate, fps=fps),
                   work, total, verbose, progress=False)
            return candidate
        except TubeBoxError as exc:
            if requested == 'auto' and candidate == 'nvenc':
                print(f'      NVIDIA encoding unavailable for this file; falling back to CPU. {exc}', file=sys.stderr)
            elif candidate == 'nvenc':
                raise TubeBoxError(f'NVIDIA encoding failed; original preserved. '
                                   f'Use --encoder auto or --encoder cpu to allow CPU encoding. {exc}') from exc
            else:
                raise
        finally:
            preview.unlink(missing_ok=True)


def encode(command, work, total, verbose=False, progress=True):
    log = work / 'ffmpeg.log'
    options = ['-loglevel', 'info' if verbose else 'error', '-nostats', '-stats_period', '2', '-progress', 'pipe:1']
    with log.open('w+') as errors:
        process = subprocess.Popen([command[0], *options, *command[1:]], cwd=work,
                                   env=environment(work), stdout=subprocess.PIPE,
                                   stderr=None if verbose else errors, text=True)
        last_report, fields = 0, {}
        try:
            for line in process.stdout:
                key, _, value = line.strip().partition('=')
                fields[key] = value
                if key != 'progress' or not progress:
                    continue
                now = time.monotonic()
                if not sys.stdout.isatty() and now - last_report < 30 and value != 'end':
                    continue
                last_report = now
                try:
                    elapsed = max(0, int(fields.get('out_time_us', 0)) / 1_000_000)
                    speed = float(fields.get('speed', '0x').rstrip('x'))
                    eta = max(0, total - elapsed) / speed if speed > 0 else None
                    percent = min(100, elapsed / total * 100)
                    message = f'      {percent:5.1f}%  {elapsed:.0f}/{total:.0f}s  {speed:.2f}x'
                    if eta is not None:
                        message += f'  ETA {eta / 60:.1f} min'
                    print(message, end='\r' if sys.stdout.isatty() else '\n', flush=True)
                except (ValueError, ZeroDivisionError):
                    pass
            code = process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            process.stdout.close()
            if progress and sys.stdout.isatty():
                print()
        if code:
            errors.flush()
            errors.seek(max(0, errors.tell() - 4000))
            raise TubeBoxError(f'ffmpeg failed: {errors.read().strip() or "see verbose output"}')


def ratio(value):
    try:
        return float(Fraction(str(value).replace(':', '/')))
    except (ValueError, ZeroDivisionError):
        return 0


def validate_output(source, output, fps=30):
    original, video = primary_video(source), primary_video(output)
    if reasons(video, fps):
        raise TubeBoxError('Output did not meet the H.264 / yuv420p / 1080p / frame rate target.')
    before, after = duration(source), duration(output)
    if abs(before - after) > max(2, before * 0.01):
        raise TubeBoxError('Output duration differs from the source; refusing replacement.')
    if video['width'] > original['width'] or video['height'] > original['height']:
        raise TubeBoxError('Output was upscaled; refusing replacement.')
    src_rate, dst_rate = frame_rate(original), frame_rate(video)
    expected_rate = min(src_rate, fps_limit(fps))
    if abs(expected_rate - dst_rate) > max(0.1, expected_rate * 0.01):
        raise TubeBoxError('Output frame rate differs from the expected rate; refusing replacement.')
    src_aspect = original['width'] / original['height'] * (ratio(original.get('sample_aspect_ratio')) or 1)
    dst_aspect = video['width'] / video['height'] * (ratio(video.get('sample_aspect_ratio')) or 1)
    if abs(src_aspect - dst_aspect) > src_aspect * 0.01:
        raise TubeBoxError('Output aspect ratio differs from the source; refusing replacement.')
    for kind in ('audio', 'attachment'):
        before_codecs = [s.get('codec_name') for s in source['streams'] if s.get('codec_type') == kind]
        after_codecs = [s.get('codec_name') for s in output['streams'] if s.get('codec_type') == kind]
        if before_codecs != after_codecs:
            raise TubeBoxError(f'Output {kind} streams differ; refusing replacement.')
    actual_subtitles = [s.get('codec_name') for s in output['streams'] if s.get('codec_type') == 'subtitle']
    if actual_subtitles != stream_plan(source)[2]:
        raise TubeBoxError('Output subtitles differ; refusing replacement.')
    if len(source.get('chapters', [])) != len(output.get('chapters', [])):
        raise TubeBoxError('Output chapters are missing; refusing replacement.')


def discover(path):
    if path.is_symlink():
        raise TubeBoxError('Pass a real file or directory, not a symbolic link.')
    if path.is_file():
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise TubeBoxError('Unsupported video file extension.')
        return [path]
    if not path.is_dir():
        raise TubeBoxError(f'Path unavailable: {path}. Mount your storage first.')
    files = []
    def walk_error(error):
        raise error
    for directory, dirs, names in os.walk(path, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            candidate = Path(directory) / name
            if not name.startswith('.') and candidate.suffix.lower() in VIDEO_EXTENSIONS and not candidate.is_symlink():
                files.append(candidate)
    return files


def normalize_file(source, dry_run=False, verbose=False, encoder='auto', fps=30, local=False):
    source = source.absolute()
    temp_root = Path(tempfile.gettempdir()).resolve()
    source_mount = enclosing_mount(source)
    if (temp_root.is_relative_to(source.parent) or
            (source_mount != Path(source_mount.anchor) and enclosing_mount(temp_root) == source_mount
             and not known_local_mount(source_mount))):
        raise TubeBoxError('Temporary storage must be local and separate from the media folder. Set TMPDIR to a local directory.')
    with tempfile.TemporaryDirectory(prefix='tubebox-normalize-', dir=temp_root) as directory:
        work = Path(directory)
        identity = file_identity(source)
        info = probe(source, work)
        video = primary_video(info)
        why = reasons(video, fps)
        print(f'      {video.get("codec_name", "unknown").upper()} / {video.get("pix_fmt", "unknown")} / {video["width"]}x{video["height"]}')
        if not why:
            print('      Already Pi 3 compatible; skipped')
            return 'compatible'
        print('      Requires normalization: ' + ', '.join(why))
        if frame_rate(video) > fps_limit(fps):
            print(f'      Reducing video to {fps} fps; playback speed and audio are preserved.')
        _, conversions, _, warnings = stream_plan(info)
        for message in warnings:
            print('      ' + message)
        if conversions:
            print('      Converting mov_text subtitles to SRT (text retained; styling may change).')
        target = (source.with_name(source.stem + '.normalized.mkv') if warnings else
                  source if source.suffix.lower() == '.mkv' else source.with_suffix('.mkv'))
        if target != source and os.path.lexists(target):
            raise TubeBoxError(f'Output already exists: {target}. Original preserved.')
        total = duration(info)
        print(f'      -> {target}' + (' (original retained)' if warnings else ' (replaces original)'))
        if dry_run:
            if local:
                print('      Local mode: read source directly; no input copy')
            print(f'      Encoder: {encoder}' + (' (NVIDIA availability checked when encoding; CPU fallback)' if encoder == 'auto' else ''))
            return 'would normalize'
        if local:
            print('      Reading local source directly (no input copy)...', flush=True)
            local_source = source
        else:
            print('      Copying source to local workspace...', flush=True)
            local_source = work / ('source' + source.suffix)
            shutil.copyfile(source, local_source)
            if file_identity(source) != identity or local_source.stat().st_size != identity[2]:
                raise TubeBoxError('Source changed during copying; original preserved.')
        selected = select_encoder(local_source, info, work, total, encoder, verbose, fps=fps)
        output = work / 'normalized.mkv'
        print(f'      Encoding with {"NVIDIA GPU (h264_nvenc)" if selected == "nvenc" else "CPU (libx264)"}...', flush=True)
        encode(encode_command(local_source, output, info, encoder=selected, fps=fps), work, total, verbose)
        if not output.is_file() or not output.stat().st_size:
            raise TubeBoxError('ffmpeg produced no output; original preserved.')
        print('      Validating...', flush=True)
        validate_output(info, probe(output, work), fps)
        print('      Transferring validated output...', flush=True)
        message = install_normalized(output, source, target, identity, keep_source=bool(warnings))
        print('      ' + message)
        return 'normalized'


def normalize(args):
    missing = [tool for tool in ('ffmpeg', 'ffprobe') if not shutil.which(tool)]
    if missing:
        raise TubeBoxError('Missing dependencies: ' + ', '.join(missing) + '. Install ffmpeg (which includes ffprobe).')
    config_file = getattr(args, 'config', None)
    config = load_config(config_file) if config_file is not None and config_file.exists() else {}
    fps = fps_limit(getattr(args, 'fps', None) or config.get('fps', '30'))
    print(f'Frame rate cap: {fps} fps')
    path = args.path.expanduser().absolute()
    files = discover(path)
    print(f'Scanning {len(files)} videos...' + (' (dry run)' if args.dry_run else ''))
    counts = dict(compatible=0, normalized=0, failed=0)
    planned = 0
    for index, source in enumerate(files, 1):
        print(f'\n[{index}/{len(files)}] {source}', flush=True)
        try:
            result = normalize_file(source, args.dry_run, args.verbose, args.encoder, fps=fps, local=args.local)
            if result == 'would normalize':
                planned += 1
            else:
                counts[result] += 1
        except (TubeBoxError, OSError, subprocess.SubprocessError) as exc:
            counts['failed'] += 1
            print(f'      Failed: {exc}', file=sys.stderr)
    print(f'\nSummary:\n  {len(files)} files scanned\n  {counts["compatible"]} already compatible\n'
          f'  {counts["normalized"]} normalized\n  {counts["failed"]} failed')
    if args.dry_run:
        print(f'  {planned} would be normalized; no media modified')
    return 1 if counts['failed'] else 0
