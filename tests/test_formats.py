"""Exercise yt-dlp's actual format selection without downloading any media."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tubebox.cli import download_format


@unittest.skipUnless(shutil.which('yt-dlp'), 'Optional format integration checks require yt-dlp')
class FormatTests(unittest.TestCase):
    def select(self, preference, formats, permissive=False, fps=30):
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / 'info.json'
            info.write_text(json.dumps({'id': 'test', 'title': 'Synthetic formats',
                                       'extractor': 'generic', 'webpage_url': 'https://example.org/test',
                                       'formats': formats}))
            return subprocess.run([
                'yt-dlp', '--ignore-config', '--simulate', '--no-check-formats',
                '--load-info-json', str(info), '--format', download_format(preference, fps),
                *([] if permissive else ['--format-sort', 'res,vcodec:h264,acodec:aac']), '--print', 'format_id',
            ], capture_output=True, text=True, timeout=20)

    def video(self, height, ext='mp4', audio=True):
        return dict(format_id=f'{height}-{ext}', height=height, width=height * 16 // 9 if height else None,
                    ext=ext, fps=30, vcodec='h264', acodec='aac' if audio else 'none',
                    url='https://example.org/synthetic.' + ext)

    def test_frame_rate_cap_applies_to_both_download_attempts(self):
        formats = [dict(self.video(1080), format_id='30fps', fps=30),
                   dict(self.video(1080), format_id='60fps', fps=60)]
        for permissive in (False, True):
            for cap in (30, 60):
                with self.subTest(cap=cap, permissive=permissive):
                    result = self.select('1080', formats, permissive=permissive, fps=cap)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), f'{cap}fps')
        for rate in (60, None):
            result = self.select('1080', [dict(self.video(1080), fps=rate)])
            self.assertNotEqual(result.returncode, 0)

    def test_resolution_cap_and_lower_fallback(self):
        for heights, expected in [([720, 1080, 2160], '1080-mp4'), ([480, 720, 2160], '720-mp4')]:
            with self.subTest(heights=heights):
                result = self.select('1080', [self.video(h) for h in heights])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_best_still_has_1080_cap(self):
        result = self.select('best', [self.video(720), self.video(2160)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '720-mp4')

    def test_codec_preferences_and_permissive_audio(self):
        avc = dict(self.video(1080, audio=False), format_id='avc', vcodec='avc1.640028')
        av1 = dict(self.video(1080, audio=False), format_id='av1', vcodec='av01.0.08M.08')
        aac = dict(format_id='aac', ext='m4a', vcodec='none', acodec='mp4a.40.2', url='https://example.org/audio.m4a')
        opus = dict(format_id='opus-audio', ext='webm', vcodec='none', acodec='opus', url='https://example.org/audio.webm')
        result = self.select('1080', [avc, av1, aac, opus])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'avc+aac')
        result = self.select('1080', [av1, aac, opus], permissive=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'av1+opus-audio')
        result = self.select('1080', [avc, opus])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'avc+opus-audio')

    def test_higher_or_unknown_only_formats_fail(self):
        for height in (2160, None):
            with self.subTest(height=height):
                result = self.select('1080', [self.video(height)])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Requested format is not available', result.stderr)

    def test_resolution_precedes_container_with_separate_audio(self):
        formats = [self.video(720), self.video(1080, 'webm', audio=False),
                   dict(format_id='audio', ext='m4a', vcodec='none', acodec='aac',
                        url='https://example.org/synthetic.m4a')]
        result = self.select('1080', formats)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1080-webm+audio')
