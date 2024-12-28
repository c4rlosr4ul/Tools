
#!/usr/bin/env python3
import yt_dlp
import os

PLAYLIST_URL = "https://www.youtube.com/playlist?list=OLAK5uy_mkmnsZpl3TSbi57HeQfv3dBfLIQiYuJmw"

OUTPUT_FOLDER = "./Johann-Strauss-II-Waltzes-Polkas-&-Overtures"

def my_hook(d):
    """
    A simple hook function to print download/conversion progress in the console.
    """
    if d['status'] == 'downloading':
        title = d['info_dict'].get('title', 'Unknown Title')
        percentage = d['_percent_str']
        speed = d['_speed_str']
        print(f"Downloading: {title} [{percentage} at {speed}]")
    elif d['status'] == 'finished':
        title = d['info_dict'].get('title', 'Unknown Title')
        print(f"Done downloading, now converting: {title}")

def download_playlist(playlist_url, out_folder):
    """
    Downloads the best audio from a YouTube playlist using yt-dlp,
    converts it to MP3 (up to 320kbps).
    """
    # Ensure output directory exists
    os.makedirs(out_folder, exist_ok=True)

    # Options for best audio download + MP3 conversion
    ydl_opts = {
        'format': 'bestaudio/best',  # best available audio format from YouTube
        'outtmpl': f'{out_folder}/%(title)s.%(ext)s',
        'ignoreerrors': True,       # skip any videos that cause errors
        'progress_hooks': [my_hook],
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                # Tells ffmpeg to use up to 320 kbps for the MP3 track.
                'preferredquality': '320',
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([playlist_url])

if __name__ == "__main__":
    download_playlist(PLAYLIST_URL, OUTPUT_FOLDER)
    print("\nDownload(s) complete! The files are located in:", os.path.abspath(OUTPUT_FOLDER))

