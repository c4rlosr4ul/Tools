
#!/usr/bin/env python3

import os
import sys
import re
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
import musicbrainzngs

###############################################################################
# 1) Configure MusicBrainz
###############################################################################
musicbrainzngs.set_useragent(
    "MyAutoTagger",          # Your app name
    "0.1",                   # Your app version
    "https://musicbrainz.org/ws/2/.",   # Your contact URL or email
)

###############################################################################
# 2) Main logic: walk files, parse name, query MB, set tags
###############################################################################
def main(root_folder):
    root_folder = os.path.expanduser(root_folder)

    for dirpath, _, filenames in os.walk(root_folder):
        for fname in filenames:
            if not fname.lower().endswith(".mp3"):
                continue

            fullpath = os.path.join(dirpath, fname)
            print(f"\nProcessing file: {fullpath}")

            # 2A) Parse out some guess of composer/artist + track title
            #     For demonstration, let's attempt:
            #     "Chopin： Polonaise in G minor, Op. posth..mp3"
            #     => composer/artist guess = "Chopin"
            #        track guess = "Polonaise in G minor, Op. posth."
            composer_guess, track_guess = parse_classical_filename(fname)

            if not track_guess:
                print("  Could not parse track name from filename. Skipping MB lookup.")
                continue

            # 2B) Query MusicBrainz for a recording that matches
            metadata = lookup_musicbrainz_recording(
                composer_guess,
                track_guess
            )

            if not metadata:
                print(f"  No MusicBrainz match found for: {composer_guess=} {track_guess=}")
                continue

            # 2C) Write the tags with the MB data
            set_id3_tags(fullpath, metadata)

###############################################################################
# 3) Naive parse function
###############################################################################
def parse_classical_filename(filename):
    """
    Example:
      "Chopin： Polonaise in G minor, Op. posth..mp3"
      => composer_guess = "Chopin"
         track_guess    = "Polonaise in G minor, Op. posth."

    If we can't parse anything, return ("Unknown", <filename minus extension>).
    Adjust to your actual naming patterns.
    """
    name_no_ext, _ = os.path.splitext(filename)

    # Replace underscores/hyphens with spaces
    name_no_ext = name_no_ext.replace("_", " ").replace("-", " ")

    # Possibly handle punctuation like "Chopin： ":
    # We'll try a split around "：" or ":" or " - "
    # e.g. "Chopin： Polonaise in G minor" => parts[0]="Chopin", parts[1]="Polonaise in G minor"
    # This is extremely naive; adapt as needed
    composer_guess = "Unknown"
    track_guess    = name_no_ext

    # Regex to capture something like "Composer: Title"
    # We'll accept ":", "：", or " - " as a delimiter
    match = re.split(r"[:：\-]\s*", name_no_ext, maxsplit=1)
    if len(match) == 2:
        composer_guess = match[0].strip()
        track_guess    = match[1].strip()

    # If composer is short or not meaningful, fallback
    if len(composer_guess) < 2:
        composer_guess = "Unknown"

    return composer_guess, track_guess

###############################################################################
# 4) MusicBrainz Query
###############################################################################
def lookup_musicbrainz_recording(artist_guess, track_guess):
    """
    Use musicbrainzngs to search for a recording that matches the guessed
    artist/composer + track title. Return a dict with relevant metadata if found.
    """
    try:
        # We'll do a 'recording' search. Another approach is searching 'work' or 'release'.
        # For classical, composer might be stored as "artist", "tag", or "relate-locations", etc.
        # This is just an example:
        results = musicbrainzngs.search_recordings(
            recording=track_guess,
            artist=artist_guess,
            limit=5  # get up to 5 possible results
        )
        rec_list = results.get('recording-list', [])
        if not rec_list:
            return None

        # Just pick the "best" (first) result
        best = rec_list[0]
        # We can extract:
        #   title = best["title"]
        #   artist-credit = best["artist-credit"][0]["artist"]["name"] maybe
        #   release-list, release date, etc.
        # We'll gather them carefully:
        meta = {}
        meta["title"] = best.get("title", track_guess)
        # Artist
        artist_credits = best.get("artist-credit", [])
        if artist_credits:
            # Usually artist_credits is a list of dicts, e.g. [ {"artist": {"name": "Frederic Chopin", ...}} ]
            meta["artist"] = artist_credits[0]["artist"].get("name", artist_guess)
        else:
            meta["artist"] = artist_guess

        # If there's a release, we might find album or date
        # But it may be absent if it's just a track. We look at 'release-list'
        release_list = best.get("release-list", [])
        if release_list:
            # pick the first release
            release = release_list[0]
            meta["album"] = release.get("title", "")
            # date
            meta["date"] = release.get("date", "")  # e.g. "1981" or "2020-03-10"
        else:
            meta["album"] = ""
            meta["date"]  = ""

        # For classical, "composer" might be the same as "artist" or might be separate, etc.
        # We can store the composer guess as well
        meta["composer"] = artist_guess  # or if you want the actual "composer" from MB, you'd need more advanced logic

        # We'll just put a default genre or omit it
        meta["genre"] = "Classical"

        return meta

    except Exception as e:
        print(f"  MusicBrainz query error: {e}")
        return None

###############################################################################
# 5) Write tags with mutagen
###############################################################################

def normalize_unknown(value):
    """
    If value is exactly '[unknown]' (case-sensitive),
    return 'Unknown' instead.
    Otherwise return value as-is.
    """
    if value == "[unknown]":
        return "Unknown"
    return value

def set_id3_tags(filepath, mb_data):
    """
    Write the MB data to the MP3 using mutagen.EasyID3,
    then print a summary with nicer wording for unknown fields.
    """
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError

        try:
            audio = EasyID3(filepath)
        except ID3NoHeaderError:
            audio = EasyID3()
            audio.save(filepath)
            audio = EasyID3(filepath)

        # Store fields, converting "[unknown]" to "Unknown" if you want:
        def store_if_present(field, key):
            """
            If the key is in mb_data and not empty,
            store it in EasyID3 under `field` name.
            Replace '[unknown]' with 'Unknown'.
            """
            if key in mb_data and mb_data[key]:
                val = mb_data[key]
                if val == "[unknown]":
                    val = "Unknown"
                audio[field] = val

        store_if_present("title", "title")
        store_if_present("artist", "artist")
        store_if_present("album", "album")
        store_if_present("date", "date")
        store_if_present("composer", "composer")
        store_if_present("genre", "genre")

        audio.save()

        # For printing a summary, we read back the final fields:
        final_title    = normalize_unknown(audio.get("title", [""])[0])
        final_artist   = normalize_unknown(audio.get("artist", [""])[0])
        final_album    = normalize_unknown(audio.get("album", [""])[0])
        final_date     = normalize_unknown(audio.get("date", [""])[0])
        final_composer = normalize_unknown(audio.get("composer", [""])[0])

        print(f"  => ID3 tags set from MusicBrainz: "
              f"Title='{final_title}', "
              f"Artist='{final_artist}', "
              f"Album='{final_album}', "
              f"Date='{final_date}', "
              f"Composer='{final_composer}'")

    except Exception as e:
        print(f"  [Error writing tags]: {e}")



###############################################################################
# Entry point
###############################################################################
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} /path/to/music/folder")
        sys.exit(1)

    target_dir = sys.argv[1]
    print(f"Auto-tagging .mp3 files under {target_dir} using MusicBrainz…")
    main(target_dir)
    print("\nDone.\n")

