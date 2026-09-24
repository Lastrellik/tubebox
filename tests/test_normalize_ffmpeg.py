"""Local synthetic media only; no downloads or copyrighted fixtures."""
from contextlib import redirect_stdout
import io
import os
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

    def test_real_60fps_cap_preserves_duration_audio_and_lower_rates(self):
        self.check_fps_cap(local=False)

    def test_real_local_60fps_cap_preserves_duration_and_audio(self):
        self.check_fps_cap(local=True)

    def check_fps_cap(self, local):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'High fps.mkv'
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=96x64:rate=60:duration=2',
                             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)])
            original = n.probe(source, root)
            def audio_packets():
                result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a',
                                         '-show_packets', '-show_data_hash', 'sha256',
                                         '-show_entries', 'packet=pts_time,duration_time,data_hash',
                                         '-of', 'json', str(source)], capture_output=True, text=True, check=True)
                return result.stdout
            packets = audio_packets()
            before = source.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(n.normalize_file(source, fps=60), 'compatible')
                self.assertEqual(n.normalize_file(source, fps=30, dry_run=True), 'would normalize')
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(n.normalize_file(source, encoder='cpu', fps=30, local=local), 'normalized')
            result = n.probe(source, root)
            self.assertEqual(n.primary_video(result)['avg_frame_rate'], '30/1')
            self.assertLess(abs(n.duration(original) - n.duration(result)), 0.05)
            self.assertEqual(audio_packets(), packets)
            n.validate_output(original, result, fps=30)
            before = source.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(n.normalize_file(source, fps=60), 'compatible')
            self.assertEqual(source.read_bytes(), before)

    def test_real_multistream_10bit_frame_rate_chapters_and_metadata(self):
        self.check_multistream('cpu')

    def test_real_local_multistream_preservation(self):
        self.check_multistream('cpu', local=True)

    @unittest.skipUnless(os.environ.get('TUBEBOX_TEST_NVENC') == '1', 'Set TUBEBOX_TEST_NVENC=1 to test a real NVIDIA GPU')
    def test_real_nvenc_multistream_10bit_frame_rate_chapters_and_metadata(self):
        self.check_multistream('nvenc')

    def check_multistream(self, encoder, local=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Movie.mkv'
            subtitle = root / 'captions.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nGenerated test caption\n')
            metadata = root / 'chapters.txt'
            metadata.write_text(';FFMETADATA1\ntitle=Synthetic movie\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Start\n')
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24000/1001:duration=1.2',
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
                self.assertEqual(n.normalize_file(source, encoder=encoder, local=local), 'normalized')
            result = n.probe(source, root)
            n.validate_output(original, result)
            video = n.primary_video(result)
            self.assertEqual((video['width'], video['height']), (320, 180))
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
        self.check_4k('cpu')

    @unittest.skipUnless(os.environ.get('TUBEBOX_TEST_NVENC') == '1', 'Set TUBEBOX_TEST_NVENC=1 to test a real NVIDIA GPU')
    def test_real_nvenc_4k_downscale_preserves_shape(self):
        self.check_4k('nvenc')

    def check_4k(self, encoder):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Large.mkv'
            self.run_ffmpeg(['-f', 'lavfi', '-i', 'color=size=3840x1600:rate=1:duration=1',
                             '-c:v', 'ffv1', str(source)])
            with redirect_stdout(io.StringIO()):
                n.normalize_file(source, encoder=encoder)
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
                n.normalize_file(source, encoder='cpu')
            self.assertFalse(source.exists())
            result = n.probe(source.with_suffix('.mkv'), root)
            self.assertEqual([s['codec_name'] for s in result['streams']], ['h264', 'subrip'])
