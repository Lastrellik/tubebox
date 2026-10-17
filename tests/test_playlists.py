"""Playlist orchestration without network access or media downloads."""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tubebox import cli
from tubebox.storage import TubeBoxError


class PlaylistTests(unittest.TestCase):
    url = 'https://www.youtube.com/watch?v=lLI75agf2Hs&list=PLexample&index=9'
    ids = ['lLI75agf2Hs', 'FYv4AtCz2Js', 'CCGRe3RFA-U']

    def run_playlist(self, entries=None, add_effect=None, extra=()):
        data = {'title': 'Permitted playlist', 'entries': entries if entries is not None else [
            {'id': video_id, 'title': f'Video {index}'} for index, video_id in enumerate(self.ids)]}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli, 'load_config', return_value={}), \
                patch.object(cli, 'check_destination'), patch.object(cli, 'dependencies'), \
                patch.object(cli, 'run', return_value=json.dumps(data)) as run, \
                patch.object(cli, 'add', side_effect=add_effect) as add, \
                redirect_stdout(out), redirect_stderr(err):
            status = cli.main(['add', self.url, '--playlist', *extra])
        return status, add, run, out.getvalue(), err.getvalue()

    def test_sequential_order_defaults_and_canonical_urls(self):
        events = []
        def download(args):
            events.extend([('start', args.url), ('complete', args.url)])
            self.assertTrue(args.yes)
            self.assertIsNone(args.folder)
            self.assertIsNone(args.name)
            self.assertIsNone(args.season)
            self.assertIsNone(args.episode)
        status, add, run, out, _ = self.run_playlist(add_effect=download, extra=['--use-defaults'])
        self.assertEqual(status, 0)
        urls = [f'https://www.youtube.com/watch?v={video_id}' for video_id in self.ids]
        self.assertEqual(events, [event for url in urls for event in [('start', url), ('complete', url)]])
        self.assertEqual(add.call_count, 3)
        command = run.call_args.args[0]
        self.assertIn('--flat-playlist', command)
        self.assertEqual(command[-1], 'https://www.youtube.com/playlist?list=PLexample')
        self.assertTrue(Path(run.call_args.kwargs['cwd']).is_absolute())
        self.assertIn('3 added, 0 failed', out)

    def test_failures_continue_and_return_nonzero(self):
        status, add, _, out, err = self.run_playlist(add_effect=[None, TubeBoxError('private video'), None])
        self.assertEqual(status, 1)
        self.assertEqual(add.call_count, 3)
        self.assertIn('2 added, 1 failed', out)
        self.assertIn(self.ids[1], err)
        self.assertIn('private video', err)

    def test_missing_entries_are_reported_and_do_not_stop_later_videos(self):
        status, add, _, out, err = self.run_playlist(entries=[None, {'id': 'bad'}, {'id': self.ids[0]}])
        self.assertEqual(status, 1)
        self.assertEqual(add.call_count, 1)
        self.assertIn('1 added, 2 failed', out)
        self.assertIn('no valid YouTube video ID', err)

    def test_interrupt_stops_remaining_entries(self):
        status, add, _, _, _ = self.run_playlist(add_effect=KeyboardInterrupt())
        self.assertEqual(status, 130)
        self.assertEqual(add.call_count, 1)

    def test_single_video_is_default_and_defaults_aliases_work(self):
        for flag in ['--use-defaults', '--yes', '-y']:
            with self.subTest(flag=flag), patch.object(cli, 'add') as add, patch.object(cli, 'add_playlist') as playlist:
                self.assertEqual(cli.main(['add', self.url, flag]), 0)
                self.assertTrue(add.call_args.args[0].yes)
                self.assertEqual(add.call_args.args[0].url, self.url)
                playlist.assert_not_called()

    def test_playlist_preserves_interactive_mode_and_shared_options(self):
        status, add, _, _, _ = self.run_playlist(extra=['--folder', 'Science', '--season', '2', '--fps', '60'])
        self.assertEqual(status, 0)
        for call in add.call_args_list:
            self.assertFalse(call.args[0].yes)
            self.assertEqual(call.args[0].folder, 'Science')
            self.assertEqual(call.args[0].season, 2)
            self.assertEqual(call.args[0].fps, 60)

    def test_empty_playlist_and_conflicting_options_fail_before_download(self):
        status, add, _, _, _ = self.run_playlist(entries=[])
        self.assertEqual(status, 1)
        add.assert_not_called()
        for flags in [['--name', 'Same name'], ['--episode', '1']]:
            status, add, run, _, _ = self.run_playlist(extra=flags)
            self.assertEqual(status, 1)
            add.assert_not_called()
            run.assert_not_called()

    def test_mount_failure_prevents_playlist_network_request(self):
        with patch.object(cli, 'load_config', return_value={}), \
                patch.object(cli, 'check_destination', side_effect=TubeBoxError('offline')), \
                patch.object(cli, 'run') as run, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['add', self.url, '--playlist']), 1)
            run.assert_not_called()

    def test_invalid_json_is_clean_error(self):
        with patch.object(cli, 'load_config', return_value={}), patch.object(cli, 'check_destination'), \
                patch.object(cli, 'dependencies'), patch.object(cli, 'run', return_value='invalid'), \
                redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(['add', self.url, '--playlist']), 1)
            self.assertIn('invalid playlist metadata', error.getvalue())

    def test_only_youtube_playlist_urls_are_accepted(self):
        for url in ['https://example.org/?list=abc', 'https://youtube.com.evil.org/?list=abc',
                    'https://youtube.com/watch?v=lLI75agf2Hs', 'ftp://youtube.com/?list=abc']:
            with self.subTest(url=url), patch.object(cli, 'run') as run, redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['add', url, '--playlist']), 1)
                run.assert_not_called()
