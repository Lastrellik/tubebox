"""Read recent local playback from Kodi without modifying its database."""
import sqlite3
from pathlib import Path


def recent_videos(database_dir, root, videos, limit=10):
    databases = [p for p in Path(database_dir).glob('MyVideos*.db')
                 if p.stem[8:].isdigit()]
    if not databases:
        return []
    database = max(databases, key=lambda p: int(p.stem[8:]))
    available = {str(p.resolve()): p for p in videos}
    roots = {str(root), str(root.resolve())}
    patterns = [p.rstrip('/') + '/*' for p in sorted(roots)]
    query = '''SELECT p.strPath, f.strFilename
               FROM files f JOIN path p ON p.idPath = f.idPath
               WHERE f.lastPlayed IS NOT NULL AND f.lastPlayed != ''
                 AND (''' + ' OR '.join('p.strPath GLOB ?' for _ in patterns) + ''')
               ORDER BY f.lastPlayed DESC, f.idFile DESC'''
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0.2)
    try:
        result, seen = [], set()
        for directory, filename in connection.execute(query, patterns):
            key = str((Path(directory) / filename).resolve())
            if key in available and key not in seen:
                result.append(available[key])
                seen.add(key)
                if len(result) >= limit:
                    break
        return result
    finally:
        connection.close()
