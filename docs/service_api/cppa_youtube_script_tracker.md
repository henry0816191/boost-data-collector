# cppa_youtube_script_tracker — Service API

**Module path:** `cppa_youtube_script_tracker.services`
**Description:** YouTube channel metadata, video metadata, transcript state, and speaker links for C++ conference talks. Single place for all writes to `cppa_youtube_script_tracker` models. Speaker profiles live in `cppa_user_tracker.YoutubeSpeaker`.

**Type notation:** Model types refer to `cppa_youtube_script_tracker.models` unless noted. `YoutubeSpeaker` refers to `cppa_user_tracker.models.YoutubeSpeaker`.

---

## YouTubeChannel

| Function                | Parameter types                                  | Return type      | Description                                                                     |
| ----------------------- | ------------------------------------------------ | ---------------- | ------------------------------------------------------------------------------- |
| `get_or_create_channel` | `channel_id: str`, `channel_title: str = ""`   | `YouTubeChannel` | Get or create channel by `channel_id`; updates `channel_title` if it has changed. |

---

## YouTubeVideo

| Function               | Parameter types                                                                    | Return type              | Description                                                                                     |
| ---------------------- | ---------------------------------------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------- |
| `get_or_create_video`  | `video_id: str`, `channel: YouTubeChannel \| None`, `metadata_dict: dict`         | `tuple[YouTubeVideo, bool]` | Get or create video by `video_id`. Raises `ValueError` if `video_id` is empty.                |
| `update_video_transcript` | `video: YouTubeVideo`, `transcript_path: str`                                   | `YouTubeVideo`           | Set `has_transcript=True` and `transcript_path` on the video; saves `update_fields`.           |

`metadata_dict` accepted keys:

| Key                | Type              | Notes                                              |
| ------------------ | ----------------- | -------------------------------------------------- |
| `title`            | str               |                                                    |
| `description`      | str               |                                                    |
| `published_at`     | datetime or str   | ISO string is parsed via `parse_datetime`          |
| `duration_seconds` | int               |                                                    |
| `view_count`       | int \| None       |                                                    |
| `like_count`       | int \| None       |                                                    |
| `comment_count`    | int \| None       |                                                    |
| `search_term`      | str               | Search term used to discover the video             |
| `scraped_at`       | datetime or str   | ISO string is parsed via `parse_datetime`          |

Tags are not part of `metadata_dict`; use `get_or_create_tag` and `link_tag_to_video` (in this module) to associate tags with a video after creating or fetching it.

---

## YouTubeVideoSpeaker

| Function              | Parameter types                               | Return type          | Description                                              |
| --------------------- | --------------------------------------------- | -------------------- | -------------------------------------------------------- |
| `link_speaker_to_video` | `video: YouTubeVideo`, `speaker: YoutubeSpeaker` | `YouTubeVideoSpeaker` | Get-or-create M2M link between a video and a speaker.  |

---

## YoutubeSpeaker (in cppa_user_tracker)

| Function                        | Parameter types                                    | Return type                  | Description                                                                      |
| ------------------------------- | -------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------- |
| `get_or_create_youtube_speaker` | `external_id: str`, `display_name: str = ""`, `identity: Identity \| None = None` | `tuple[YoutubeSpeaker, bool]` | Get or create a speaker by `external_id`; updates `display_name` when provided. Raises `ValueError` if `external_id` is empty. |

**Module path:** `cppa_user_tracker.services`

---

## Preprocessor

**Module path:** `cppa_youtube_script_tracker.preprocessor`

| Function                         | Parameter types                                         | Return type                        | Description                                                                                   |
| -------------------------------- | ------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------- |
| `preprocess_youtube_for_pinecone` | `failed_ids: list[str]`, `final_sync_at: datetime \| None` | `tuple[list[dict], bool]`          | Build Pinecone sync documents for YouTube videos. Returns `(docs, is_chunked=False)`.        |

Each document dict has:
- `content` — Title, speakers, channel, published date, description, and transcript text (if available).
- `metadata["doc_id"]` — `"youtube-{video_id}"`.
- `metadata["ids"]` — DB primary key of the `YouTubeVideo` row (for retry tracking).
- `metadata["type"]` — `"youtube"`.
- `metadata["url"]` — `"https://www.youtube.com/watch?v={video_id}"`.
- `metadata["title"]`, `metadata["author"]` (comma-separated speaker names), `metadata["channel"]`, `metadata["timestamp"]` (Unix timestamp), `metadata["has_transcript"]`.

---

## Workspace helpers

**Module path:** `cppa_youtube_script_tracker.workspace`

| Function                | Return type | Description                                                                 |
| ----------------------- | ----------- | --------------------------------------------------------------------------- |
| `get_workspace_root()`  | `Path`      | `workspace/cppa_youtube_script_tracker/`                                    |
| `get_raw_dir()`         | `Path`      | `workspace/raw/cppa_youtube_script_tracker/` (permanent JSON archive)       |
| `get_raw_transcripts_dir()` | `Path`      | `workspace/raw/cppa_youtube_script_tracker/transcripts/` (permanent VTT archive) |
| `get_metadata_queue_dir()`       | `Path`      | `workspace/cppa_youtube_script_tracker/metadata/` (short-lived; moved after persist) |
| `get_raw_metadata_path(video_id)` | `Path` | Raw metadata JSON archive path for a video.                                          |
| `get_metadata_queue_path(video_id)` | `Path` | Metadata queue JSON path for a video.                                               |
| `get_transcript_path(video_id, lang="en")` | `Path` | VTT path for a video.                                         |
| `iter_metadata_queue_jsons()`    | `Iterator[Path]` | Yield all `*.json` files in the metadata queue directory.                       |

---

## Fetcher

**Module path:** `cppa_youtube_script_tracker.fetcher`

| Function        | Parameter types                                                                                                                     | Return type          | Description                                                                                           |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ----------------------------------------------------------------------------------------------------- |
| `fetch_videos`  | `published_after: datetime`, `published_before: datetime`, `channel_title: str \| None = None`, `skip_video_ids: set[str] \| None = None`, `min_duration_seconds: int = 0` | `list[dict]` | Fetch video metadata from YouTube Data API v3 for the given time window. Returns normalised metadata dicts. |

Each returned dict contains the following keys:

| Key                | Type        | Notes                                                             |
| ------------------ | ----------- | ----------------------------------------------------------------- |
| `video_id`         | str         | YouTube video ID                                                  |
| `title`            | str         |                                                                   |
| `description`      | str         |                                                                   |
| `channel_id`       | str         |                                                                   |
| `channel_title`    | str         |                                                                   |
| `published_at`     | str         | ISO 8601 datetime string from API                                 |
| `duration_seconds` | int         | Parsed from ISO 8601 duration (e.g. `PT1H2M10S`)                 |
| `view_count`       | int \| None |                                                                   |
| `like_count`       | int \| None |                                                                   |
| `comment_count`    | int \| None |                                                                   |
| `tags`             | list        |                                                                   |
| `search_term`      | str         | Query used to discover the video                                  |
| `scraped_at`       | str         | ISO 8601 datetime when the API call was made                      |

**`channel_title` behaviour:** If `channel_title` matches a key in the `C_PLUS_PLUS_CHANNELS` dict, the API call is filtered by that channel's ID. If `channel_title` is unrecognised, a keyword search by name is used. If `channel_title` is `None`, all known C++ channels are searched.

**Requires:** `YOUTUBE_API_KEY` setting. Raises `ValueError` if missing. Raises `ImportError` if `google-api-python-client` is not installed.

---

## Transcript downloader

**Module path:** `cppa_youtube_script_tracker.transcript`

| Function        | Parameter types                                                               | Return type     | Description                                                                                                      |
| --------------- | ----------------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------- |
| `download_vtt`  | `video_id: str`, `output_dir: Path`, `cookies_file: str \| None = None`      | `Path \| None`  | Download English VTT subtitles for `video_id` into `output_dir`. Returns path to the `.vtt` file, or `None` if not found. |

Tries manual captions first, then auto-generated (`writeautomaticsub`). The output file is written as `{video_id}.en.vtt`; falls back to any `{video_id}*.vtt` file in `output_dir` if the expected name is not present.

**Requires:** `yt-dlp`. Raises `ImportError` if not installed.

---

## Related docs

- [Schema.md](../Schema.md) – Section 10: CPPA YouTube Script Tracker.
- [service_api/README.md](README.md) – Service API index.
