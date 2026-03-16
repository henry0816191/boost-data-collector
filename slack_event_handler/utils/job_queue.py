"""
FIFO job queue and background worker for the Slack PR comment bot.

State (queue + rate-limit timestamps) is persisted per team so multiple workspaces
can run in one process. Config is read from Django settings via rate_limiter helpers.
"""

import logging
import threading
import time
import uuid
from typing import Optional

from django.conf import settings

from slack_event_handler.utils.rate_limiter import (
    SLOT_BUFFER_SEC,
    compute_delay,
    compute_delay_at,
    recent_timestamps_at,
    record_posted,
    wait_for_slot,
)
from slack_event_handler.utils.github_pr_client import post_pr_comment
from slack_event_handler.utils.state import load_state, save_state

logger = logging.getLogger(__name__)

KEY_JOB_ID = "jobId"
KEY_TEAM_ID = "teamId"
KEY_OWNER = "owner"
KEY_REPO = "repo"
KEY_PULL_NUMBER = "pullNumber"
KEY_CHANNEL = "channel"
KEY_MESSAGE_TS = "messageTs"
KEY_USER_ID = "userId"
KEY_IS_DM = "isDm"
KEY_ENQUEUED_AT = "enqueuedAt"

# Per-team Slack app and worker busy flag for multi-workspace support
_slack_app_by_team: dict[str, object] = {}
_slack_app_by_team_lock = threading.Lock()
_worker_busy_by_team: dict[str, bool] = {}
_worker_busy_lock = threading.Lock()


def set_slack_app(app, team_id: str) -> None:
    """Register the Bolt app for this team so the worker can send replies."""
    with _slack_app_by_team_lock:
        _slack_app_by_team[team_id] = app


def enqueue_job(
    owner: str,
    repo: str,
    pull_number: int,
    channel: str,
    message_ts: str,
    user_id: str,
    is_dm: bool = False,
    team_id: Optional[str] = None,
) -> dict:
    """Adds a new job to the persistent FIFO queue for this team and returns it."""
    state = load_state(team_id)
    job = {
        KEY_JOB_ID: str(uuid.uuid4()),
        KEY_TEAM_ID: team_id,
        KEY_OWNER: owner,
        KEY_REPO: repo,
        KEY_PULL_NUMBER: pull_number,
        KEY_CHANNEL: channel,
        KEY_MESSAGE_TS: message_ts,
        KEY_USER_ID: user_id,
        KEY_IS_DM: is_dm,
        KEY_ENQUEUED_AT: time.time(),
    }
    state["queue"].append(job)
    save_state(state, team_id)
    return job


def estimated_delay_sec(team_id: Optional[str] = None) -> int:
    """
    Returns estimated seconds before the newest queued job for this team can post.

    Simulates each job already ahead in the queue consuming a rate-limit slot
    at the earliest available time, then computes the delay for the new job.
    """
    max_per_window = int(getattr(settings, "SLACK_PR_BOT_COMMENTS_MAX_PER_WINDOW", 5))
    window_sec = int(getattr(settings, "SLACK_PR_BOT_COMMENTS_WINDOW_SECONDS", 3600))

    state = load_state(team_id)
    posted_at = list(state["postedAt"])
    with _worker_busy_lock:
        busy = _worker_busy_by_team.get(team_id, False)
    jobs_ahead = max(0, len(state["queue"]) - 1) + (1 if busy else 0)
    now = time.time()
    sim_time = now

    for _ in range(jobs_ahead):
        recent = recent_timestamps_at(posted_at, sim_time, window_sec)
        if len(recent) >= max_per_window:
            oldest = min(recent)
            sim_time += max(0.0, oldest + window_sec - sim_time + SLOT_BUFFER_SEC)
        posted_at = recent_timestamps_at(posted_at, sim_time, window_sec)
        posted_at.append(sim_time)

    delay_at_sim = compute_delay_at(posted_at, sim_time)
    total_delay = max(0.0, sim_time - now + (delay_at_sim if delay_at_sim > 0 else 0))
    return int(total_delay + 0.999) if total_delay > 0.999 else 0


def _send_reply(
    team_id: Optional[str],
    channel: str,
    thread_ts: str,
    is_dm: bool,
    text: str,
) -> None:
    """Posts a thread reply for channel messages or a plain DM for direct messages."""
    app = None
    if team_id is not None:
        with _slack_app_by_team_lock:
            app = _slack_app_by_team.get(team_id)
    if app is None:
        return
    try:
        kwargs = {"channel": channel, "text": text}
        if not is_dm:
            kwargs["thread_ts"] = thread_ts
        app.client.chat_postMessage(**kwargs)
    except Exception as e:
        logger.warning("Failed to send reply (channel=%s): %s", channel, e)


def _job_label(job: dict) -> str:
    is_dm = job.get(KEY_IS_DM, False)
    source = "dm" if is_dm else "channel"
    team = job.get(KEY_TEAM_ID, "")
    return (
        f"[job:{job[KEY_JOB_ID]}][team:{team}][{source}] "
        f"{job[KEY_OWNER]}/{job[KEY_REPO]}#{job[KEY_PULL_NUMBER]}"
    )


def _process_job(job: dict) -> None:
    team_id = job.get(KEY_TEAM_ID)
    with _worker_busy_lock:
        _worker_busy_by_team[team_id] = True

    is_dm = job.get(KEY_IS_DM, False)
    label = _job_label(job)
    owner = job[KEY_OWNER]
    repo = job[KEY_REPO]
    pull_number = job[KEY_PULL_NUMBER]
    channel = job[KEY_CHANNEL]
    message_ts = job[KEY_MESSAGE_TS]

    state = load_state(team_id)
    delay = compute_delay(state["postedAt"])
    if delay > 0:
        logger.debug("%s – rate limited, waiting %ds", label, int(delay + 0.999))

    wait_for_slot(team_id)

    logger.debug("%s – posting GitHub comment", label)
    post_pr_comment(owner, repo, pull_number)
    record_posted(team_id)
    with _worker_busy_lock:
        _worker_busy_by_team[team_id] = False
    _send_reply(
        team_id,
        channel,
        message_ts,
        is_dm,
        f"✅ Comment posted to `{owner}/{repo}#{pull_number}`.",
    )
    logger.debug("%s – comment posted", label)

    with _slack_app_by_team_lock:
        app = _slack_app_by_team.get(team_id) if team_id else None
    if app is None:
        return
    try:
        app.client.reactions_add(
            channel=channel, timestamp=message_ts, name="white_check_mark"
        )
    except Exception as e:
        if "already_reacted" not in str(e):
            raise


def _worker(team_id: Optional[str]) -> None:
    """Long-running FIFO worker daemon thread for one team."""
    logger.debug("PR job queue worker started for team %s", team_id or "default")
    while True:
        state = load_state(team_id)

        if not state["queue"]:
            time.sleep(1)
            continue

        job, *remaining = state["queue"]
        state["queue"] = remaining
        save_state(state, team_id)

        with _worker_busy_lock:
            _worker_busy_by_team[team_id] = True
        label = _job_label(job)
        is_dm = job.get(KEY_IS_DM, False)
        try:
            _process_job(job)
        except Exception as e:
            logger.warning("%s – FAILED: %s", label, e)
            _send_reply(
                team_id,
                job[KEY_CHANNEL],
                job[KEY_MESSAGE_TS],
                is_dm,
                f"❌ Could not post comment to "
                f"`{job[KEY_OWNER]}/{job[KEY_REPO]}#{job[KEY_PULL_NUMBER]}`: {e}",
            )
        finally:
            with _worker_busy_lock:
                _worker_busy_by_team[team_id] = False


def start_worker(team_id: Optional[str] = None) -> None:
    """Starts the background PR job queue worker for this team in a daemon thread."""
    name = f"pr-job-queue-worker-{team_id or 'default'}"
    t = threading.Thread(target=_worker, args=(team_id,), daemon=True, name=name)
    t.start()
