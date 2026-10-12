import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest


ADDON = Path(__file__).resolve().parents[1] / 'kodi/script.tubebox.youtube'
spec = importlib.util.spec_from_file_location('kodi_rows', ADDON / 'rows.py')
rows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rows)


class KodiRowsTests(unittest.TestCase):
    def setUp(self):
        self.config = rows.load_config(ADDON / 'config.json')['rows']

    def test_default_fifty_unique_choices(self):
        result = rows.build_rows(list(range(200)), self.config, rng=random.Random(1))
        self.assertEqual([len(row) for row in result], [25, 25])
        self.assertEqual(len(set(result[0] + result[1])), 50)

    def test_small_and_empty_libraries(self):
        for size in (0, 1, 2, 7, 49):
            result = rows.build_rows(list(range(size)), self.config)
            self.assertEqual(set(result[0] + result[1]), set(range(size)))
            self.assertEqual(sum(map(len, result)), size)
            self.assertLessEqual(abs(len(result[0]) - len(result[1])), 1)

    def test_refresh_prefers_unseen_videos(self):
        first = rows.build_rows(list(range(100)), self.config)
        old = first[0] + first[1]
        second = rows.build_rows(list(range(100)), self.config, previous=old)
        self.assertFalse(set(old) & set(second[0] + second[1]))

    def test_different_sizes_and_history_do_not_duplicate(self):
        config = [{'type': 'random', 'count': 3}, {'type': 'random', 'count': 8}]
        result = rows.build_rows(list(range(30)), config)
        self.assertEqual([len(row) for row in result], [3, 8])
        config[1]['type'] = 'recently_watched'
        result = rows.build_rows(list(range(30)), config, history=[99, 5, 5, 6, 7])
        self.assertEqual(result[1], [5, 6, 7])
        self.assertFalse(set(result[0]) & set(result[1]))

    def test_invalid_config_rejected(self):
        base = json.loads((ADDON / 'config.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for count in (0, 101, True, '25'):
                base['rows'][0]['count'] = count
                path.write_text(json.dumps(base))
                with self.assertRaises(ValueError):
                    rows.load_config(path)


if __name__ == '__main__':
    unittest.main()
