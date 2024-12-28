
#!/usr/bin/env python3
import os
import re
import shutil
import time
import urllib.request

import requests
import spotipy
from moviepy.editor import AudioFileClip
from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3
from pytube import YouTube
from rich.console import Console
from spotipy.oauth2 import SpotifyClientCredentials

# ------------- GLOBALS & SETUP -------------
console = Console()
file_exists_action = ""  # Tracks how to handle existing files globally
SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET")

# Validate that we have credentials
if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    console.print("[red]Error:[/red] SPOTIPY_CLIENT_ID or SPOTIPY_CLIENT_SECRET not set.")
    console.print(
        "Please set the environment variables [yellow]SPOTIPY_CLIENT_ID[/yellow] and "
        "[yellow]SPOTIPY_CLIENT_SECRET[/yellow] before running."
    )
    raise SystemExit(1)

client_credentials_manager = SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET
)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Ensure needed directories exist
os.makedirs("../music/tmp", exist_ok=True)


def main():
    """
    Main entry point. Prompts user for a Spotify URL (track or playlist),
    downloads each track from YouTube, sets metadata, and saves to ../music.
    """
    try:
        spotify_url = input("Enter a Spotify [track or playlist] URL: ").strip()
        url = validate_spotify_url(spotify_url)

        # Build list of track metadata
        if "track" in url:
            songs = [get_track_info(url)]
        elif "playlist" in url:
            songs = get_playlist_info(url)
        else:
            raise ValueError("URL must point to a Spotify 'track' or 'playlist'.")

        start_time = time.time()
        downloaded_count = 0
        total_songs = len(songs)

        # Download each track in the list
        for i, track_info in enumerate(songs, start=1):
            search_term = f"{track_info['artist_name']} {track_info['track_title']} audio"
            console.print(
                f"\n[magenta]({i}/{total_songs})[/magenta] Searching YouTube for:"
                f" [cyan]{search_term}[/cyan]"
            )

            try:
                yt_link = find_youtube(search_term)
            except Exception as e:
                console.print(f"[red]Failed to find YouTube link:[/red] {e}")
                continue

            console.print(
                f"[green]Downloading '[/green][cyan]{track_info['artist_name']} - "
                f"{track_info['track_title']}[/cyan][green]'...[/green]"
            )

            audio_path = download_yt(yt_link)
            if audio_path:
                # We have an MP3 file. Embed metadata & artwork.
                set_metadata(track_info, audio_path)
                # Move final MP3 to ../music
                final_path = os.path.join("../music", os.path.basename(audio_path))
                os.replace(audio_path, final_path)
                console.print("[blue]--------------------------------------------------[/blue]")
                downloaded_count += 1
            else:
                console.print("[yellow]File skipped or error occurred.[/yellow]")

        # Cleanup
        shutil.rmtree("../music/tmp", ignore_errors=True)
        total_time = round(time.time() - start_time)

        # Final summary
        console.print(f"\n[b]Download location:[/b] {os.path.abspath('../music')}")
        console.print(
            f"DOWNLOAD COMPLETED: {downloaded_count}/{total_songs} song(s) downloaded",
            style="on green",
        )
        console.print(f"Total time taken: {total_time} sec", style="on white")

    except KeyboardInterrupt:
        console.print("\n[red]Canceled by user (CTRL+C).[/red]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


# ------------- SPOTIFY FUNCTIONS -------------
def validate_spotify_url(sp_url: str) -> str:
    """
    Ensure the URL is a valid open.spotify.com link for a track or playlist.
    Raises ValueError if invalid.
    """
    pattern = r"^(https?://)?open\.spotify\.com/(playlist|track)/.+$"
    if re.search(pattern, sp_url):
        return sp_url
    raise ValueError("Invalid Spotify URL format.")


def get_track_info(track_url: str) -> dict:
    """
    Fetch metadata from a single Spotify track.
    Raises ValueError if response is invalid.
    """
    resp = requests.get(track_url)
    if resp.status_code != 200:
        raise ValueError("Invalid Spotify track URL or track not accessible.")

    track = sp.track(track_url)
    track_metadata = {
        "artist_name": track["artists"][0]["name"],
        "track_title": track["name"],
        "track_number": track["track_number"],
        "isrc": track["external_ids"].get("isrc", ""),
        "album_art": track["album"]["images"][1]["url"]
        if len(track["album"]["images"]) > 1
        else track["album"]["images"][0]["url"],
        "album_name": track["album"]["name"],
        "release_date": track["album"]["release_date"],
        "artists": [artist["name"] for artist in track["artists"]],
    }
    return track_metadata


def get_playlist_info(playlist_url: str) -> list:
    """
    Fetch metadata for every track in a Spotify playlist.
    Only works on public playlists.
    """
    resp = requests.get(playlist_url)
    if resp.status_code != 200:
        raise ValueError("Invalid or inaccessible Spotify playlist URL.")

    playlist_data = sp.playlist(playlist_url)
    if not playlist_data["public"]:
        raise ValueError("Cannot download from a private playlist. Make it public first.")

    # Paginate through all tracks
    tracks_info = []
    offset = 0
    while True:
        pl_tracks = sp.playlist_items(playlist_url, offset=offset)
        items = pl_tracks["items"]
        if not items:
            break

        for item in items:
            track = item["track"]
            if not track:  # sometimes items can be None
                continue
            track_id = track.get("id")
            if track_id:
                track_url = f"https://open.spotify.com/track/{track_id}"
                track_metadata = get_track_info(track_url)
                tracks_info.append(track_metadata)

        offset += len(items)
        if not pl_tracks["next"]:  # no more pages
            break

    return tracks_info


# ------------- YOUTUBE / DOWNLOAD FUNCTIONS -------------
def find_youtube(query: str) -> str:
    """
    Searches YouTube by 'query' string, returns the first video link found.
    Raises ValueError if search fails or no results.
    """
    phrase = query.replace(" ", "+")
    search_url = "https://www.youtube.com/results?search_query=" + phrase

    # Attempt up to 3 times for unstable connections
    attempts = 0
    while attempts < 3:
        try:
            response = urllib.request.urlopen(search_url)
            break
        except:
            attempts += 1
            time.sleep(1)
    else:
        raise ValueError("Failed to reach YouTube. Check internet connection.")

    search_html = response.read().decode()
    search_results = re.findall(r"watch\?v=(\S{11})", search_html)
    if not search_results:
        raise ValueError("No YouTube results found for query.")

    first_video = "https://www.youtube.com/watch?v=" + search_results[0]
    return first_video


def prompt_file_exists_action() -> bool:
    """
    Ask user how to handle a file that already exists:
      - replace(R) once
      - replace all(RA)
      - skip(S)
      - skip all(SA)
    Returns True if file should be replaced, False if file is skipped.
    """
    global file_exists_action
    if file_exists_action in ["SA", "RA"]:
        # If user already chose 'skip all' or 'replace all', use that
        return file_exists_action == "RA"

    console.print("This file already exists.")
    while True:
        resp = input("replace[R] | replace all[RA] | skip[S] | skip all[SA]: ").upper().strip()
        if resp in ("R", "RA"):
            if resp == "RA":
                file_exists_action = "RA"
            return True
        elif resp in ("S", "SA"):
            if resp == "SA":
                file_exists_action = "SA"
            return False
        console.print("[red]Invalid response.[/red] Please choose: R / RA / S / SA")


def download_yt(yt_link: str) -> str:
    """
    Download the YouTube video audio track as MP3.
    Returns the file path if successful, or None if skipped.
    """
    yt = YouTube(yt_link)
    # Remove invalid filename characters
    safe_title = "".join(c for c in yt.title if c not in ['/', '\\', '|', '?', '*', ':', '>', '<', '"'])

    out_filename = f"{safe_title}.mp3"
    final_path = os.path.join("../music", out_filename)

    # If file exists, prompt user about overwriting or skipping
    if os.path.exists(final_path):
        if not prompt_file_exists_action():
            return None

    # Download to tmp directory
    video = yt.streams.filter(only_audio=True).first()
    temp_vid = video.download(output_path="../music/tmp")

    # Convert to MP3
    base, _ = os.path.splitext(temp_vid)
    audio_mp3 = base + ".mp3"
    audio_clip = AudioFileClip(temp_vid)
    audio_clip.write_audiofile(audio_mp3, logger=None)
    audio_clip.close()

    # Remove the original downloaded file
    os.remove(temp_vid)

    # Move MP3 into tmp folder with sanitized name
    final_tmp_path = os.path.join("../music/tmp", out_filename)
    os.replace(audio_mp3, final_tmp_path)

    return final_tmp_path


# ------------- METADATA -------------
def set_metadata(metadata: dict, file_path: str):
    """
    Embed ID3 metadata (artist, title, album, track number, date, etc.)
    and album cover image from Spotify in the downloaded MP3.
    """
    try:
        # EasyID3 for simple tags
        audiofile = EasyID3(file_path)
    except Exception:
        # If file has no ID3 tag at all, initialize
        from mutagen.id3 import ID3NoHeaderError
        try:
            ID3(file_path)
        except ID3NoHeaderError:
            audiofile = EasyID3()
            audiofile.save(file_path)
            audiofile = EasyID3(file_path)
        else:
            audiofile = EasyID3(file_path)

    # Fill in basic tags
    audiofile["albumartist"] = metadata["artist_name"]
    audiofile["artist"] = metadata["artists"]
    audiofile["album"] = metadata["album_name"]
    audiofile["title"] = metadata["track_title"]
    audiofile["date"] = metadata["release_date"]
    audiofile["tracknumber"] = str(metadata["track_number"])
    if metadata["isrc"]:
        audiofile["isrc"] = metadata["isrc"]

    audiofile.save()

    # For embedding album art, switch to full ID3
    audio_data = ID3(file_path)
    with urllib.request.urlopen(metadata["album_art"]) as album_art:
        album_bytes = album_art.read()
        audio_data["APIC"] = APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover",
            data=album_bytes
        )
    audio_data.save(v2_version=3)


if __name__ == "__main__":
    main()

