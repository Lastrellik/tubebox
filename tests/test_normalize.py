import argparse
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tubebox import cli, normalize as n, storage


def media(codec='hevc', pixel='yuv420p10le', width=1920, height=808):
    return {'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': codec, 'pix_fmt': pixel,
                         'width': width, 'height': height, 'avg_frame_rate': '24000/1001',
                         'sample_aspect_ratio': '1:1', 'disposition': {'default': 1}}],
            'format': {'duration': '100'}, 'chapters': []}


class CompatibilityTests(unittest.TestCase):
    def test_codec_pixel_and_size_classification(self):
        for codec, pixel, width, height, compatible in [
            ('h264', 'yuv420p', 1920, 1080, True), ('h264', 'yuv420p', 640, 360, True),
            ('hevc', 'yuv420p', 1920, 1080, False), ('hevc', 'yuv420p10le', 1920, 808, False),
            ('vp9', 'yuv420p', 1280, 720, False), ('av1', 'yuv420p', 1280, 720, False),
            ('h264', 'yuv420p', 3840, 2160, False), ('h264', 'yuv420p10le', 1920, 1080, False),
            ('h264', 'yuv444p', 640, 360, False)]:
            with self.subTest(codec=codec, pixel=pixel, width=width):
                self.assertEqual(not n.reasons(n.primary_video(media(codec, pixel, width, height))), compatible)

    def test_all_audio_subtitles_attachments_metadata_and_timestamps_mapped(self):
        info = media()
        info['streams'] += [dict(index=1, codec_type='audio', codec_name='aac'),
                            dict(index=2, codec_type='audio', codec_name='ac3'),
                            dict(index=3, codec_type='subtitle', codec_name='subrip'),
                            dict(index=4, codec_type='subtitle', codec_name='mov_text')]
        command = n.encode_command(Path('/local/in.mp4'), Path('/local/out.mkv'), info)
        self.assertIn('0:a?', command)
        self.assertIn('0:t?', command)
        self.assertIn('0:3', command)
        self.assertIn('0:4', command)
        self.assertIn('-map_metadata', command)
        self.assertIn('-map_chapters', command)
        self.assertEqual(command[command.index('-c:a') + 1], 'copy')
        self.assertEqual(command[command.index('-c:s:1') + 1], 'srt')
        self.assertEqual(command[command.index('-fps_mode:v') + 1], 'passthrough')
        self.assertNotIn('-r', command)
        self.assertIn('min(1,', command[command.index('-vf') + 1])

    def test_unknown_subtitle_is_reported_before_encode(self):
        info = media()
        info['streams'].append(dict(index=1, codec_type='subtitle', codec_name='unknown'))
        maps, _, subtitles, warnings = n.stream_plan(info)
        self.assertNotIn('0:1', maps)
        self.assertEqual(subtitles, [])
        self.assertIn('keeping the original', warnings[0])

    def test_validation_rejects_bad_output(self):
        original = media()
        good = media('h264', 'yuv420p')
        n.validate_output(original, good)
        for field, value in [('codec_name', 'hevc'), ('pix_fmt', 'yuv420p10le'),
                             ('width', 3840), ('avg_frame_rate', '60/1'), ('height', 1080)]:
            bad = deepcopy(good)
            bad['streams'][0][field] = value
            with self.subTest(field=field), self.assertRaises(storage.TubeBoxError):
                n.validate_output(original, bad)
        bad = deepcopy(good)
        bad['format']['duration'] = '10'
        with self.assertRaises(storage.TubeBoxError):
            n.validate_output(original, bad)

    def test_attached_picture_not_primary(self):
        info = media()
        info['streams'].insert(0, dict(index=9, codec_type='video', disposition={'attached_pic': 1}))
        self.assertEqual(n.primary_video(info)['index'], 0)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Movie.mkv'
        self.original = b'original-media'
        self.source.write_bytes(self.original)
        self.input = media()
        self.output = media('h264', 'yuv420p')
        self.workspaces = []

    def fake_encode(self, command, work, *args, **kwargs):
        self.workspaces.append(work)
        self.assertFalse(work.is_relative_to(self.root))
        input_path = Path(command[command.index('-i') + 1])
        self.assertEqual(input_path.parent, work)
        self.assertEqual(input_path.read_bytes(), self.original)
        Path(command[-1]).write_bytes(b'normalized-media')

    def run_file(self, dry=False, encoder=None, probe_info=None):
        with patch.object(n, 'probe', side_effect=probe_info or [self.input, self.output]), patch.object(n, 'encode', side_effect=encoder or self.fake_encode), redirect_stdout(io.StringIO()):
            return n.normalize_file(self.source, dry_run=dry)

    def test_compatible_is_untouched(self):
        identity = storage.file_identity(self.source)
        with patch.object(n, 'encode') as encode:
            self.assertEqual(self.run_file(probe_info=[self.output]), 'compatible')
            encode.assert_not_called()
        self.assertEqual(storage.file_identity(self.source), identity)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_local_processing_validated_and_replaced(self):
        self.assertEqual(self.run_file(), 'normalized')
        self.assertEqual(self.source.read_bytes(), b'normalized-media')
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.assertTrue(all(not work.exists() for work in self.workspaces))

    def test_network_source_uses_local_processing(self):
        with patch.object(n, 'enclosing_mount', side_effect=[self.root, Path('/')]):
            self.assertEqual(self.run_file(), 'normalized')
        self.assertTrue(self.workspaces)
        self.assertTrue(all(not work.is_relative_to(self.root) for work in self.workspaces))

    def test_uppercase_mkv_keeps_exact_filename(self):
        self.source = self.source.rename(self.root / 'Movie.MKV')
        self.run_file()
        self.assertEqual(self.source.read_bytes(), b'normalized-media')

    def test_failed_encode_preserves_source_and_cleans_work(self):
        calls = []
        def fail(command, work, *args, **kwargs):
            calls.append(work)
            Path(command[-1]).write_bytes(b'partial')
            raise storage.TubeBoxError('encoding failed')
        with self.assertRaises(storage.TubeBoxError):
            self.run_file(encoder=fail)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(all(not work.exists() for work in calls))

    def test_failed_validation_preserves_source(self):
        self.output['format']['duration'] = '5'
        with self.assertRaises(storage.TubeBoxError):
            self.run_file()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_dry_run_modifies_nothing(self):
        before = storage.file_identity(self.source)
        with patch.object(n, 'install_normalized', side_effect=AssertionError('install called')):
            self.assertEqual(self.run_file(dry=True), 'would normalize')
        self.assertEqual(self.workspaces, [])
        self.assertEqual(storage.file_identity(self.source), before)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_non_mkv_keeps_stem_and_removes_source_only_after_success(self):
        target = self.source
        self.source = self.source.rename(self.root / 'Movie.mp4')
        self.run_file()
        self.assertFalse(self.source.exists())
        self.assertEqual(target.read_bytes(), b'normalized-media')

    def test_existing_output_is_never_overwritten(self):
        self.source = self.source.rename(self.root / 'Movie.mp4')
        target = self.root / 'Movie.mkv'
        target.write_bytes(b'unrelated')
        with self.assertRaises(storage.TubeBoxError):
            self.run_file()
        self.assertEqual(target.read_bytes(), b'unrelated')
        self.assertEqual(self.workspaces, [])

    def test_unsupported_subtitle_keeps_original(self):
        self.input['streams'].append(dict(index=1, codec_type='subtitle', codec_name='unknown'))
        self.run_file()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual((self.root / 'Movie.normalized.mkv').read_bytes(), b'normalized-media')

    def test_failed_destination_copy_preserves_original(self):
        with patch.object(storage.shutil, 'copyfileobj', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.run_file()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_destination_hash_mismatch_preserves_original(self):
        with patch.object(storage, 'file_digest', side_effect=[b'bad-copy', b'good-output']), self.assertRaisesRegex(storage.TubeBoxError, 'verification failed'):
            self.run_file()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_failed_rename_keeps_verified_copy_and_source(self):
        with patch.object(storage.os, 'replace', side_effect=OSError('rename unsupported')), self.assertRaisesRegex(storage.TubeBoxError, 'completed copy'):
            self.run_file()
        self.assertEqual(self.source.read_bytes(), self.original)
        copies = list(self.root.glob('.tubebox-normalized-*.mkv'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), b'normalized-media')

    def test_source_changed_during_encode_is_preserved(self):
        def change(command, work, *args, **kwargs):
            self.fake_encode(command, work, *args, **kwargs)
            self.source.write_bytes(b'changed-by-user')
        with self.assertRaises(storage.TubeBoxError):
            self.run_file(encoder=change)
        self.assertEqual(self.source.read_bytes(), b'changed-by-user')

    def test_recursive_discovery_skips_symlinks_and_hidden_transfers(self):
        child = self.root / 'child'
        child.mkdir()
        (child / 'other.MP4').write_bytes(b'video')
        (child / '.tubebox-normalized-test.mkv').write_bytes(b'transfer')
        (child / 'link.mkv').symlink_to(self.source)
        self.assertEqual(set(n.discover(self.root)), {self.source, child / 'other.MP4'})

    def test_directory_continues_after_failure(self):
        other = self.root / 'second.mkv'
        other.write_bytes(b'video')
        args = argparse.Namespace(path=self.root, dry_run=False, verbose=False)
        with patch.object(n.shutil, 'which', return_value='/tool'), patch.object(n, 'normalize_file', side_effect=[storage.TubeBoxError('bad'), 'compatible']) as run, redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(n.normalize(args), 1)
            self.assertEqual(run.call_count, 2)
            self.assertIn('1 failed', output.getvalue())

    def test_missing_dependencies_reported_without_init(self):
        with patch.object(n.shutil, 'which', return_value=None), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(cli.main(['normalize', str(self.source)]), 1)
        self.assertIn('ffmpeg, ffprobe', output.getvalue())
