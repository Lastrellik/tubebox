import os
import random
import time
from pathlib import Path
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from watch_history import recent_videos

ROOT = Path('/media/MyDrive/Kids/YouTube')
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
            self.refresh_history()
            return
        self.ready = True
        self.window_id = xbmcgui.getCurrentWindowId()
        self.videos = []
        self.history = None
        self.refresh(force=True)
        self.setFocusId(100 if self.videos else 11)

    def refresh(self, force=False):
        try:
            videos = discover(ROOT)
        except OSError as exc:
            xbmc.log('TubeBox YouTube: ' + str(exc), xbmc.LOGWARNING)
            return
        if force or videos != self.videos:
            self.videos = videos
            self.fill_videos()
        self.refresh_history()

    def refresh_history(self):
        try:
            history = recent_videos(xbmcvfs.translatePath("special://database/"), ROOT, self.videos)
        except Exception as exc:
            xbmc.log("TubeBox history: " + str(exc), xbmc.LOGWARNING)
            return
        if history == self.history:
            return
        shelf = self.getControl(200)
        selected = shelf.getSelectedItem() if self.history else None
        selected_path = selected.getProperty("video") if selected else None
        self.history = history
        shelf.reset()
        for path in history:
            shelf.addItem(self.video_item(path))
        if history:
            position = next((i for i, path in enumerate(history) if str(path) == selected_path), 0)
            shelf.selectItem(position)
        self.setProperty("HistoryAvailable", "true" if history else "false")
        if not history and xbmc.getCondVisibility('Control.HasFocus(200)'):
            self.setFocusId(100 if self.videos else 11)

    def video_item(self, path):
        item = xbmcgui.ListItem(label=path.stem, label2=path.parent.name, path=str(path))
        item.setArt({"thumb": artwork(path)})
        item.setProperty("video", str(path))
        return item

    def fill_videos(self):
        shelf = self.getControl(100)
        shelf.reset()
        for path in random.sample(self.videos, min(10, len(self.videos))):
            shelf.addItem(self.video_item(path))

    def onClick(self, control):
        if control == 10:
            self.refresh(force=True)
            if self.videos:
                self.setFocusId(100)
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
        discover(ROOT)
        window = YouTubeWindow('YouTube.xml', xbmcaddon.Addon().getAddonInfo('path'), 'Default', '1080i')
        window.show()
        monitor = xbmc.Monitor()
        next_history_check = time.monotonic() + 5
        next_check = time.monotonic() + 30
        while not window.closed and not monitor.waitForAbort(1):
            if (time.monotonic() >= next_history_check and
                    not xbmc.Player().isPlaying() and
                    xbmcgui.getCurrentWindowId() == getattr(window, 'window_id', None)):
                window.refresh_history()
                next_history_check = time.monotonic() + 5
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
        xbmcgui.Dialog().notification('YouTube', 'Could not open videos. Check the media drive.')
