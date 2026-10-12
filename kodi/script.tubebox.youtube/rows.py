"""Configuration and row selection, independent of Kodi's UI."""
import json
import random
from pathlib import Path


def load_config(path):
    config = json.loads(Path(path).read_text())
    root = config.get('media_directory')
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError('media_directory must be an absolute local or mounted path')
    rows = config.get('rows')
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('Configure exactly two rows')
    for row in rows:
        if not isinstance(row, dict) or row.get('type') not in ('random', 'recently_watched'):
            raise ValueError('Row type must be random or recently_watched')
        if not isinstance(row.get('label'), str) or not row['label'].strip():
            raise ValueError('Each row needs a label')
        if type(row.get('count')) is not int or not 1 <= row['count'] <= 100:
            raise ValueError('Row count must be an integer from 1 to 100')
    return config


def build_rows(videos, configs, history=(), previous=(), rng=random):
    """Unique choices across rows; share small libraries fairly between random rows."""
    videos = list(dict.fromkeys(videos))
    available = set(videos)
    used = set()
    rows = [[] for _ in configs]
    for index, config in enumerate(configs):
        if config['type'] == 'recently_watched':
            for path in history:
                if path in available and path not in used:
                    rows[index].append(path)
                    used.add(path)
                    if len(rows[index]) == config['count']:
                        break
    previous = set(previous)
    fresh = [p for p in videos if p not in used and p not in previous]
    repeats = [p for p in videos if p not in used and p in previous]
    rng.shuffle(fresh)
    rng.shuffle(repeats)
    pool = iter(fresh + repeats)
    random_rows = [i for i, c in enumerate(configs) if c['type'] == 'random']
    while random_rows:
        for index in random_rows:
            path = next(pool, None)
            if path is None:
                return rows
            rows[index].append(path)
        random_rows = [i for i in random_rows if len(rows[i]) < configs[i]['count']]
    return rows
