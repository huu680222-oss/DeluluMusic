import os
from os import path
import yt_dlp
from yt_dlp.utils import DownloadError


def get_cookie_path():
    for p in ["SONALI_MUSIC/assets/cookies.txt", "cookies/cookies.txt"]:
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    return None


_base_opts = {
    "outtmpl": "downloads/%(id)s.%(ext)s",
    "format": "bestaudio[ext=m4a]",
    "geo_bypass": True,
    "nocheckcertificate": True,
}
_cookie_path = get_cookie_path()
if _cookie_path:
    _base_opts["cookiefile"] = _cookie_path

ytdl = yt_dlp.YoutubeDL(_base_opts)


def download(url: str, my_hook) -> str:       
    ydl_optssx = {
        'format' : 'bestaudio[ext=m4a]',
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "geo_bypass": True,
        "nocheckcertificate": True,
        'quiet': True,
        'no_warnings': True,
    }
    cookie_path = get_cookie_path()
    if cookie_path:
        ydl_optssx["cookiefile"] = cookie_path
    info = ytdl.extract_info(url, False)
    try:
        x = yt_dlp.YoutubeDL(ydl_optssx)
        x.add_progress_hook(my_hook)
        dloader = x.download([url])
    except Exception as y_e:
        return print(y_e)
    else:
        dloader
    xyz = path.join("downloads", f"{info['id']}.{info['ext']}")
    return xyz
