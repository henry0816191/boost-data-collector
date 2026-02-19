"""
Process a Slack huddle canvas: fetch transcript, download HTML, generate markdown, upload to GitHub.
"""
import json
import logging
import os

from django.conf import settings

from github_ops import upload_file
from operations.file_ops import sanitize_filename
from operations.slack_ops import SlackFetcher, fetch_huddle_transcript

from cppa_slack_transcript_tracker.workspace import get_data_dir

from .huddle_markdown import generate_huddle_markdown

logger = logging.getLogger(__name__)


def process_huddle_canvas(file_id):
    """
    Fetch huddle by file_id, generate markdown, upload to GitHub.
    Returns dict with "success" (bool) and optionally "github_url" (str).
    """
    result = fetch_huddle_transcript(file_id)
    if not result or not result.get("ok"):
        logger.warning("Failed to fetch huddle transcript for file_id: %s", file_id)
        return {"success": False}

    file_data = result.get("file", {})
    download_url = file_data.get("url_private_download") or file_data.get("url_private")
    if not download_url:
        logger.warning("No download URL for file_id: %s", file_id)
        return {"success": False}

    data_dir = get_data_dir()
    work_dir = data_dir / file_id
    work_dir.mkdir(parents=True, exist_ok=True)

    result_json_path = work_dir / "result.json"
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    try:
        fetcher = SlackFetcher()
    except ValueError as e:
        logger.error("SlackFetcher init failed: %s", e)
        return {"success": False}

    filename = sanitize_filename(file_data.get("name", "huddle_summary.html"))
    html_path = fetcher.download_file(download_url, str(work_dir), filename)
    if not html_path or not os.path.isfile(html_path):
        logger.error("Failed to download huddle HTML for file_id: %s", file_id)
        return {"success": False}

    md_path = generate_huddle_markdown(html_path, result_json_path, work_dir)
    if not md_path:
        logger.error("Failed to generate markdown for file_id: %s", file_id)
        return {"success": False}

    md_basename = os.path.basename(md_path)
    dest_path = f"slack_huddles/{md_basename}"
    branch = getattr(settings, "GITHUB_DEFAULT_BRANCH", None) or "main"
    owner = (getattr(settings, "GITHUB_SLACK_HUDDLE_REPO_OWNER", "") or "").strip()
    repo = (getattr(settings, "GITHUB_SLACK_HUDDLE_REPO_NAME", "") or "").strip()
    if not owner or not repo:
        logger.error("Missing GITHUB_SLACK_HUDDLE_REPO_OWNER or GITHUB_SLACK_HUDDLE_REPO_NAME")
        return {"success": False}
    upload_result = upload_file(
        owner,
        repo,
        dest_path,
        md_path,
        commit_message=f"Add huddle transcript: {md_basename}",
        branch=branch,
    )
    if not upload_result:
        logger.error("Failed to upload %s to GitHub", md_path)
        return {"success": False}

    github_url = f"https://github.com/{owner}/{repo}/blob/{branch}/{dest_path}"
    return {"success": True, "github_url": github_url}
