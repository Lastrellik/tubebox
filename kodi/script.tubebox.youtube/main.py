import os
import time
from pathlib import Path
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from watch_history import recent_videos
from rows import load_config, build_rows

EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.ts', '.ogv'}


def discover(root):
    if not root.is_dir():
        raise OSError('The YouTube drive is unavailable')
    videos = []
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=failed, followlinks=False):
        # Downloads arrive outside Kodi; refresh its cached directory listing
        # before the image loader checks for newly added thumbnail files.
        xbmcvfs.listdir(str(directory).rstrip("/") + "/")
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if not name.startswith('.') and path.suffix.lower() in EXTENSIONS and not path.is_symlink():
                videos.append(path)
    return videos


def artwork(path, folder=False):
    candidates = [path / 'poster.jpg', path / 'folder.jpg'] if folder else [path.with_name(path.stem + '-thumb.jpg'), path.parent / 'poster.jpg']
    return str(next((p for p in candidates if p.is_file()), 'DefaultFolder.png' if folder else 'DefaultVideo.png'))


class YouTubeWindow(xbmcgui.WindowXML):
    closed = False
    browse_requested = False

    def close(self):
        if not self.closed:
            self.closed = True
            super().close()

    def onInit(self):
        if getattr(self, 'ready', False):
            self.refresh()
            return
        self.ready = True
        self.window_id = xbmcgui.getCurrentWindowId()
        self.videos = []
        self.row_paths = [[], []]
        for index, row in enumerate(CONFIG['rows'], 1):
            self.setProperty(f'Row{index}Label', row['label'])
        self.refresh(force=True)
        self.setFocusId(self.first_row_control())

    def refresh(self, force=False):
        try:
            videos = discover(ROOT)
        except OSError as exc:
            xbmc.log('TubeBox YouTube: ' + str(exc), xbmc.LOGWARNING)
            return
        if force or videos != self.videos:
            self.videos = videos
            self.fill_videos()

    def first_row_control(self):
        return next((i * 100 for i, row in enumerate(self.row_paths, 1) if row), 11)

    def video_item(self, path):
        item = xbmcgui.ListItem(label=path.stem, label2=path.parent.name, path=str(path))
        item.setArt({"thumb": artwork(path)})
        item.setProperty("video", str(path))
        return item

    def fill_videos(self):
        history = []
        if any(row['type'] == 'recently_watched' for row in CONFIG['rows']):
            try:
                history = recent_videos(xbmcvfs.translatePath('special://database/'),
                                        ROOT, self.videos, limit=200)
            except Exception as exc:
                xbmc.log('TubeBox history: ' + str(exc), xbmc.LOGWARNING)
        previous = [path for row in self.row_paths for path in row]
        self.row_paths = build_rows(self.videos, CONFIG['rows'], history, previous)
        for index, paths in enumerate(self.row_paths, 1):
            shelf = self.getControl(index * 100)
            shelf.reset()
            for path in paths:
                shelf.addItem(self.video_item(path))
            self.setProperty(f'Row{index}Available', 'true' if paths else 'false')
        if not self.row_paths[1] and xbmc.getCondVisibility('Control.HasFocus(200)'):
            self.setFocusId(self.first_row_control())

    def onClick(self, control):
        if control == 10:
            self.refresh(force=True)
            if self.videos:
                self.setFocusId(self.first_row_control())
        elif control in (100, 200):
            item = self.getControl(control).getSelectedItem()
            if item:
                path = item.getProperty('video')
                if not Path(path).is_file():
                    xbmcgui.Dialog().notification('YouTube', 'This video is unavailable')
                    return
                playing = xbmcgui.ListItem(label=Path(path).stem, path=path)
                playing.getVideoInfoTag().setTitle(Path(path).stem)
                playing.setArt({'thumb': artwork(Path(path))})
                xbmc.Player().play(path, playing)
        elif control == 11:
            # Open the browser only after this window has been torn down.
            self.browse_requested = True
            self.close()
        elif control == 12:
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216, 247):
            self.close()


if __name__ == '__main__':
    try:
        CONFIG = load_config(Path(__file__).with_name('config.json'))
        ROOT = Path(CONFIG['media_directory'])
        discover(ROOT)
        window = YouTubeWindow('YouTube.xml', xbmcaddon.Addon().getAddonInfo('path'), 'Default', '1080i')
        window.show()
        monitor = xbmc.Monitor()
        next_check = time.monotonic() + 30
        while not window.closed and not monitor.waitForAbort(1):
            if time.monotonic() < next_check:
                continue
            next_check = time.monotonic() + 30
            if (not xbmc.Player().isPlaying() and
                    xbmcgui.getCurrentWindowId() == getattr(window, 'window_id', None) and
                    xbmc.getGlobalIdleTime() >= 10):
                window.refresh()
        browse_requested = window.browse_requested
        window.close()
        del window
        if browse_requested and not monitor.abortRequested():
            path = str(ROOT).replace('"', '')
            xbmc.executebuiltin('ActivateWindow(Videos,"' + path + '/",return)')
    except Exception as exc:
        xbmc.log('TubeBox YouTube: ' + str(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().notification('YouTube', 'Could not open videos. Check configuration and the media drive.')
