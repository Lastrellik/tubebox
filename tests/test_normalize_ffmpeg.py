"""Local synthetic media only; no downloads or copyrighted fixtures."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tubebox import normalize as n


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Requires ffmpeg and ffprobe')
class FFmpegNormalizationTests(unittest.TestCase):
    def run_ffmpeg(self, args):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_multistream_10bit_frame_rate_chapters_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Movie.mkv'
            subtitle = root / 'captions.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nGenerated test caption\n')
            metadata = root / 'chapters.txt'
            metadata.write_text(';FFMETADATA1\ntitle=Synthetic movie\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Start\n')
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=24000/1001:duration=1.2',
                             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.2', '-i', str(subtitle),
                             '-f', 'ffmetadata', '-i', str(metadata),
                             '-map', '0:v', '-map', '1:a', '-map', '1:a', '-map', '2:s', '-map', '2:s',
                             '-map_metadata', '3', '-map_chapters', '3',
                             '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=fra',
                             '-metadata:s:s:0', 'language=eng', '-metadata:s:s:1', 'language=fra',
                             '-c:v', 'ffv1', '-pix_fmt', 'yuv420p10le', '-c:a', 'aac', '-c:s', 'srt',
                             '-t', '1.2', str(source)])
            original = n.probe(source, root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(n.normalize_file(source), 'normalized')
            result = n.probe(source, root)
            n.validate_output(original, result)
            video = n.primary_video(result)
            self.assertEqual((video['width'], video['height']), (96, 64))
            self.assertEqual(video['pix_fmt'], 'yuv420p')
            self.assertEqual(video['avg_frame_rate'], '24000/1001')
            self.assertEqual(result['format']['tags']['title'], 'Synthetic movie')
            for kind in ('audio', 'subtitle'):
                streams = [s for s in result['streams'] if s['codec_type'] == kind]
                self.assertEqual(len(streams), 2)
                self.assertEqual([s['tags']['language'] for s in streams], ['eng', 'fra'])
            self.assertEqual(len(result['chapters']), 1)
            before = source.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(n.normalize_file(source), 'compatible')
            self.assertEqual(source.read_bytes(), before)

    def test_real_4k_downscale_preserves_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Large.mkv'
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'color=size=3840x1600:rate=1:duration=1',
                             '-c:v', 'ffv1', str(source)])
            with redirect_stdout(io.StringIO()):
                n.normalize_file(source)
            video = n.primary_video(n.probe(source, root))
            self.assertEqual((video['width'], video['height']), (1920, 800))
            self.assertEqual(video['avg_frame_rate'], '1/1')

    def test_real_mov_text_subtitles_convert_to_srt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Subtitle Movie.mp4'
            subtitle = root / 'captions.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nSynthetic subtitle\n')
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=25:duration=1',
                             '-i', str(subtitle), '-map', '0:v', '-map', '1:s',
                             '-c:v', 'mpeg4', '-c:s', 'mov_text', str(source)])
            with redirect_stdout(io.StringIO()):
                n.normalize_file(source)
            self.assertFalse(source.exists())
            result = n.probe(source.with_suffix('.mkv'), root)
            self.assertEqual([s['codec_name'] for s in result['streams']], ['h264', 'subrip'])
