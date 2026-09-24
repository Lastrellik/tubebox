import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tubebox import cli, storage


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / 'library'
        self.library.mkdir()
        self.config_path = self.root / 'config.ini'
        self.config = storage.initialize(self.config_path, self.library, local=True)
        self.args = argparse.Namespace(config=self.config_path, url='https://example.org/owned-video',
                                       folder=None, name=None, season=None, episode=None, yes=True)

    def fake_run(self, command, **kwargs):
        if '--write-thumbnail' in command:
            stage = Path(command[command.index('--paths') + 1])
            (stage / 'video.mp4').write_bytes(b'owned test video placeholder')
            (stage / 'video.jpg').write_bytes(b'owned test artwork placeholder')
        return ''

    def download(self, runner=None):
        with patch.object(cli, 'dependencies'), patch.object(cli, 'metadata', return_value={
                'title': 'Mars / Rover', 'channel': 'NASA'}), patch.object(cli, 'run', side_effect=runner or self.fake_run), redirect_stdout(io.StringIO()):
            cli.add(self.args)

    def test_saved_fps_and_per_command_override(self):
        storage.initialize(self.config_path, self.library, local=True, fps=60)
        for override, expected in ((None, 60), (30, 30)):
            self.args.fps = override
            self.args.name = f'Video {expected}'
            def check(command, **kwargs):
                self.assertIn(f'[fps<={expected}]', command[command.index('--format') + 1])
                self.fake_run(command)
            self.download(check)
        self.assertEqual(storage.load_config(self.config_path)['fps'], '60')

    def test_init_prompts_for_and_preserves_fps(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', side_effect=['', '', '60']), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--config', str(self.config_path), 'init']), 0)
        self.assertEqual(storage.load_config(self.config_path)['fps'], '60')
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', return_value=''), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--config', str(self.config_path), 'init']), 0)
        self.assertEqual(storage.load_config(self.config_path)['fps'], '60')

    def test_legacy_fps_default_and_invalid_config(self):
        original = self.config_path.read_text()
        self.config_path.write_text(original.replace('fps = 30\n', ''))
        self.assertEqual(storage.load_config(self.config_path)['fps'], '30')
        self.config_path.write_text(original.replace('fps = 30', 'fps = 45'))
        with patch.object(cli, 'metadata') as metadata, self.assertRaises(storage.TubeBoxError):
            cli.add(self.args)
        metadata.assert_not_called()

    def test_config_roundtrip_and_missing_destination(self):
        self.assertEqual(storage.load_config(self.config_path), self.config)
        self.library.rename(self.root / 'offline')
        with self.assertRaises(storage.TubeBoxError):
            storage.check_destination(self.config)
        self.assertFalse(self.library.exists())

    def test_init_write_failure_cleans_probe_and_preserves_config(self):
        previous = self.config_path.read_bytes()
        with patch.object(storage.os, 'fsync', side_effect=OSError('share write failed')):
            with self.assertRaisesRegex(OSError, 'share write failed'):
                storage.initialize(self.config_path, self.library, local=True, preferred_resolution='720')
        self.assertEqual(self.config_path.read_bytes(), previous)
        self.assertEqual(list(self.library.iterdir()), [self.library / '.tubebox-library'])

    def test_resolution_update_preserves_destination_and_local_mode(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=False), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--config', str(self.config_path), 'init', '--resolution', '720p']), 0)
        config = storage.load_config(self.config_path)
        self.assertEqual(config, dict(self.config, resolution='720'))

    def test_interactive_init_enter_preserves_resolution(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value=''), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--config', str(self.config_path), 'init']), 0)
        self.assertEqual(storage.load_config(self.config_path), self.config)

    def test_old_config_keeps_unlimited_resolution(self):
        self.config_path.write_text(self.config_path.read_text().replace('resolution = 1080\n', ''))
        self.assertEqual(storage.load_config(self.config_path)['resolution'], 'best')

    def test_invalid_saved_resolution_stops_before_download(self):
        self.config_path.write_text(self.config_path.read_text().replace('resolution = 1080', 'resolution = potato'))
        with patch.object(cli, 'metadata', side_effect=AssertionError('Network called')), self.assertRaises(storage.TubeBoxError):
            cli.add(self.args)

    def test_download_uses_saved_resolution(self):
        storage.initialize(self.config_path, self.library, local=True, preferred_resolution='720p')
        def check(command, **kwargs):
            self.assertEqual(command[command.index('--format') + 1], cli.download_format('720'))
            self.fake_run(command)
        self.download(check)

    def test_missing_destination_is_not_created(self):
        missing = self.root / 'missing'
        with self.assertRaises(storage.TubeBoxError):
            storage.initialize(self.config_path, missing)
        self.assertFalse(missing.exists())

    def test_wrong_library_identity(self):
        (self.library / '.tubebox-library').write_text('different library')
        with self.assertRaises(storage.TubeBoxError):
            storage.check_destination(self.config)

    def test_network_mount_must_still_be_mounted(self):
        config = dict(self.config, storage='network', mount=str(self.root))
        with patch.object(Path, 'is_mount', return_value=False), self.assertRaises(storage.TubeBoxError):
            storage.check_destination(config)

    def test_network_init_refuses_root_filesystem(self):
        with patch.object(storage, 'enclosing_mount', return_value=Path('/')), self.assertRaises(storage.TubeBoxError):
            storage.initialize(self.config_path, self.library)

    def test_success_and_duplicate_does_not_download(self):
        self.download()
        folder = self.library / 'NASA'
        self.assertEqual({p.name for p in folder.iterdir()}, {'Mars _ Rover.mp4', 'Mars _ Rover-thumb.jpg', 'poster.jpg'})
        with self.assertRaises(storage.TubeBoxError):
            self.download(runner=lambda *a, **k: self.fail('Duplicate download attempted'))
        self.assertFalse(any(p.is_dir() for p in self.library.glob('.tubebox-*')))

    def test_existing_poster_is_preserved_without_fetch(self):
        folder = self.library / 'NASA'
        folder.mkdir()
        (folder / 'poster.jpg').write_bytes(b'custom poster')
        with patch.object(cli, 'folder_art', side_effect=AssertionError('Fetched existing poster')):
            self.download()
        self.assertEqual((folder / 'poster.jpg').read_bytes(), b'custom poster')

    def test_ascii_ingestion_and_collision(self):
        self.args.yes = False
        output = io.StringIO()
        with patch.object(cli, 'dependencies'), patch.object(cli, 'metadata', return_value={
                'title': 'Café 🚀 Science 👩🏽‍🚀', 'channel': 'Créateur 🌍'}), \
                patch.object(cli, 'run', side_effect=self.fake_run), \
                patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', return_value='') as prompt, redirect_stdout(output):
            cli.add(self.args)
            self.assertTrue(all(call.args[0].isascii() for call in prompt.call_args_list))
            with patch.object(cli, 'download_media') as download, self.assertRaisesRegex(storage.TubeBoxError, 'already exists'):
                cli.add(self.args)
            download.assert_not_called()
        self.assertTrue(output.getvalue().isascii())
        self.assertEqual({p.name for p in (self.library / 'Createur').iterdir()},
                         {'Cafe Science.mp4', 'Cafe Science-thumb.jpg', 'poster.jpg'})

    def test_download_failure_cleans_staging(self):
        stages = []
        def fail(command, **kwargs):
            stages.append(Path(kwargs['cwd']))
            self.fake_run(command)
            raise storage.TubeBoxError('network failure')
        with self.assertRaises(storage.TubeBoxError):
            self.download(fail)
        self.assertEqual([p.name for p in self.library.iterdir()], ['.tubebox-library'])
        self.assertTrue(stages)
        self.assertTrue(all(not stage.exists() for stage in stages))

    def test_403_retries_once_without_codec_preferences_and_publishes_mkv(self):
        calls = []
        def download(command, **kwargs):
            work = Path(kwargs['cwd'])
            calls.append(work)
            self.assertNotIn('--recode-video', command)
            self.assertNotIn('--cookies', command)
            self.assertIn('[height<=1080]', command[command.index('--format') + 1])
            self.assertFalse((self.library / 'NASA').exists())
            if len(calls) == 1:
                self.assertIn('--check-formats', command)
                (work / 'video.f140.m4a.part').write_bytes(b'partial')
                raise storage.TubeBoxError('HTTP Error 403: Forbidden')
            self.assertNotIn('--format-sort', command)
            self.assertFalse(calls[0].exists())
            (work / 'video.mkv').write_bytes(b'finished mkv')
            (work / 'video.jpg').write_bytes(b'finished thumbnail')
        self.download(download)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(not p.exists() for p in calls))
        self.assertTrue((self.library / 'NASA' / 'Mars _ Rover.mkv').is_file())
        self.assertFalse(list(self.library.rglob('*.part')))

    def test_repeated_403_stops_after_two_attempts(self):
        calls = []
        def download(command, **kwargs):
            calls.append(Path(kwargs['cwd']))
            raise storage.TubeBoxError('HTTP Error 403: Forbidden')
        with self.assertRaises(storage.TubeBoxError):
            self.download(download)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(not p.exists() for p in calls))
        self.assertFalse((self.library / 'NASA').exists())

    def test_webm_is_preserved_without_transcoding(self):
        def download(command, **kwargs):
            self.fake_run(command)
            work = Path(kwargs['cwd'])
            (work / 'video.mp4').rename(work / 'video.webm')
            self.assertNotIn('--recode-video', command)
            self.assertNotIn('--remux-video', command)
        self.download(download)
        self.assertTrue((self.library / 'NASA' / 'Mars _ Rover.webm').is_file())

    def test_processing_is_local_and_cleaned_on_success(self):
        stages = []
        def download(command, **kwargs):
            stage = Path(kwargs['cwd'])
            stages.append(stage)
            self.assertFalse(stage.is_relative_to(self.library.resolve()))
            self.assertIn(f'temp:{stage}', command)
            self.assertFalse((self.library / 'NASA').exists())
            (stage / 'unfinished.part').write_bytes(b'intermediate')
            self.fake_run(command)
        self.download(download)
        self.assertTrue(stages)
        self.assertTrue(all(not stage.exists() for stage in stages))
        self.assertFalse(list(self.library.rglob('*.part')))
        self.assertFalse(list(self.library.rglob('.tubebox-transfer-*')))

    def test_cancellation_cleans_local_work(self):
        stages = []
        def interrupt(command, **kwargs):
            stages.append(Path(kwargs['cwd']))
            self.fake_run(command)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.download(interrupt)
        self.assertTrue(all(not stage.exists() for stage in stages))
        self.assertFalse((self.library / 'NASA').exists())

    def test_temp_directory_on_destination_rejected(self):
        with patch.object(cli.tempfile, 'gettempdir', return_value=str(self.library)), patch.object(cli, 'dependencies'), patch.object(cli, 'metadata') as metadata:
            with self.assertRaisesRegex(storage.TubeBoxError, 'TMPDIR'):
                cli.add(self.args)
            metadata.assert_not_called()

    def test_destination_lost_before_transfer(self):
        stages = []
        def download(command, **kwargs):
            stages.append(Path(kwargs['cwd']))
            self.fake_run(command)
        with patch.object(cli, 'check_destination', side_effect=[self.library, storage.TubeBoxError('Share disconnected')]), self.assertRaises(storage.TubeBoxError):
            self.download(download)
        self.assertTrue(all(not stage.exists() for stage in stages))
        self.assertFalse((self.library / 'NASA').exists())

    def test_empty_video_is_not_transferred(self):
        def download(command, **kwargs):
            self.fake_run(command)
            (Path(kwargs['cwd']) / 'video.mp4').write_bytes(b'')
        with self.assertRaises(storage.TubeBoxError):
            self.download(download)
        self.assertFalse((self.library / 'NASA').exists())

    def test_creator_artwork_commands_use_local_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            thumb = stage / 'video.jpg'
            thumb.write_bytes(b'thumb')
            def process(command, **kwargs):
                self.assertEqual(kwargs['cwd'], stage)
                self.assertNotIn(str(self.library), ' '.join(command))
                if command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'poster')
            with patch.object(cli, 'metadata', return_value={'thumbnail': 'https://example.org/art'}) as metadata, patch.object(cli, 'run', side_effect=process):
                poster = cli.folder_art({'channel_url': 'https://example.org/channel'}, stage, thumb)
                metadata.assert_called_once_with('https://example.org/channel', channel=True, cwd=stage)
                self.assertEqual(poster.read_bytes(), b'poster')

    def test_missing_artwork_does_not_publish_video(self):
        def missing(command, **kwargs):
            self.fake_run(command)
            stage = Path(command[command.index('--paths') + 1])
            (stage / 'video.jpg').unlink()
        with self.assertRaises(storage.TubeBoxError):
            self.download(missing)
        self.assertFalse((self.library / 'NASA').exists())

    def test_publish_failure_rolls_back_artwork(self):
        original = cli.copy_exclusive
        def fail(source, target):
            if target.suffix == '.mp4':
                raise OSError('disk full')
            original(source, target)
        with patch.object(cli, 'copy_exclusive', side_effect=fail), self.assertRaises(OSError):
            self.download()
        self.assertFalse((self.library / 'NASA').exists())

    def test_partial_copy_is_removed(self):
        source, target = self.root / 'source', self.root / 'target'
        source.write_bytes(b'test')
        def fail(content, output):
            output.write(b'partial')
            raise OSError('disk full')
        with patch.object(cli.shutil, 'copyfileobj', side_effect=fail), self.assertRaises(OSError):
            cli.copy_exclusive(source, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.tubebox-transfer-*')))

    def test_copy_uses_hidden_name_then_renames(self):
        source, target = self.root / 'source', self.root / 'target'
        source.write_bytes(b'complete media')
        def copy(content, output):
            self.assertFalse(target.exists())
            self.assertEqual(len(list(self.root.glob('.tubebox-transfer-*.tmp'))), 1)
            output.write(content.read())
        with patch.object(cli.shutil, 'copyfileobj', side_effect=copy):
            cli.copy_exclusive(source, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse(list(self.root.glob('.tubebox-transfer-*')))

    def test_rename_failure_rolls_back_and_cleans_transfers(self):
        with patch.object(Path, 'replace', side_effect=OSError('SMB rename failed')), self.assertRaises(OSError):
            self.download()
        self.assertFalse((self.library / 'NASA').exists())

    def test_exclusive_copy_preserves_existing_file(self):
        source, target = self.root / 'source', self.root / 'target'
        source.write_bytes(b'new')
        target.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            cli.copy_exclusive(source, target)
        self.assertEqual(target.read_bytes(), b'old')

    def test_episode_overrides(self):
        self.args.folder, self.args.name = 'Space 🌍', 'Science 🚀'
        self.args.season, self.args.episode = 1, 4
        self.download()
        self.assertTrue((self.library / 'Space' / 'Science - S01E04.mp4').is_file())

    def test_symlink_folder_rejected(self):
        (self.library / 'NASA').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(storage.TubeBoxError):
            self.download()

    def test_destination_checked_before_network(self):
        (self.library / '.tubebox-library').unlink()
        with patch.object(cli, 'metadata', side_effect=AssertionError('Network called')), self.assertRaises(OSError):
            cli.add(self.args)


class CliTests(unittest.TestCase):
    def test_successful_command_preserves_warnings(self):
        with patch.object(cli.subprocess, 'run') as process, redirect_stderr(io.StringIO()) as error:
            process.return_value.returncode = 0
            process.return_value.stdout = '{}'
            process.return_value.stderr = 'WARNING: source format unavailable\n'
            self.assertEqual(cli.run(['yt-dlp'], capture=True), '{}')
        self.assertIn('source format unavailable', error.getvalue())

    def test_403_error_has_update_guidance_and_full_diagnostics(self):
        with patch.object(cli.subprocess, 'run') as process:
            process.return_value.returncode = 1
            process.return_value.stderr = 'WARNING: important diagnostic\n' + 'x' * 2100 + '\nHTTP Error 403: Forbidden'
            with self.assertRaises(storage.TubeBoxError) as error:
                cli.run(['yt-dlp'])
        self.assertIn('important diagnostic', str(error.exception))
        self.assertIn('brew upgrade yt-dlp deno', str(error.exception))

    def test_subprocess_temp_environment_and_cwd_are_local(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            with patch.object(cli.subprocess, 'run') as process:
                process.return_value.returncode = 0
                process.return_value.stderr = ''
                cli.run(['ffmpeg', '-version'], cwd=stage)
                kwargs = process.call_args.kwargs
                self.assertEqual(kwargs['cwd'], stage)
                for name in ('TMPDIR', 'TEMP', 'TMP'):
                    self.assertEqual(kwargs['env'][name], str(stage))
                self.assertEqual(kwargs['env']['PATH'], os.environ['PATH'])

    def test_resolution_validation(self):
        for value, expected in [('1080p', '1080'), ('720', '720'), (' BEST ', 'best'), ('2160P', '2160')]:
            self.assertEqual(storage.resolution(value), expected)
        for value in ('0', '-1', '1080.5', '1080pp', 'banana', ''):
            with self.subTest(value=value), self.assertRaises(storage.TubeBoxError):
                storage.resolution(value)

    def test_sanitization(self):
        for value in ('../../hello', 'a/b\\c:d*e?f"g<h>i|j', 'a\x00b'):
            result = cli.sanitize(value)
            self.assertNotRegex(result, r'[/\\<>:"|?*\x00]')
            self.assertFalse(result.startswith('.'))
        self.assertEqual(cli.sanitize('CON.txt'), '_CON.txt')
        self.assertLessEqual(len(cli.sanitize('é' * 200).encode()), 180)
        self.assertEqual(cli.sanitize('Café 👩🏽‍🚀 — “Space”…'), 'Cafe - _Space_')
        for value in ('...', '🌙' * 200, '👩🏽‍🚀', '日本語'):
            with self.subTest(value=value), self.assertRaises(storage.TubeBoxError):
                cli.sanitize(value)

    def test_playlist_rejected(self):
        with patch.object(cli, 'run', return_value='{"_type":"playlist", "entries":[]}'), self.assertRaises(storage.TubeBoxError):
            cli.metadata('https://example.org/playlist')

    def test_subprocess_error_has_useful_message(self):
        with self.assertRaisesRegex(storage.TubeBoxError, 'failed: example failure'):
            cli.run([__import__('sys').executable, '-c', 'import sys; sys.stderr.write("example failure"); sys.exit(1)'])

    def test_missing_dependencies(self):
        with patch.object(cli.shutil, 'which', return_value=None), self.assertRaisesRegex(storage.TubeBoxError, 'yt-dlp, ffmpeg'):
            cli.dependencies()

    def test_default_prompt(self):
        with patch('builtins.input', return_value=''):
            self.assertEqual(cli.ask('Folder', 'NASA'), 'NASA')

    def test_uninitialized_cli_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as error:
            status = cli.main(['--config', str(Path(directory) / 'absent'), 'add', 'https://example.org/video'])
        self.assertEqual(status, 1)
        self.assertIn('tubebox init', error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())


if __name__ == '__main__':
    unittest.main()
