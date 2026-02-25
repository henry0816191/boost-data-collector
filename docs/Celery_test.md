# How to test the Celery task

This guide explains how to confirm the Celery worker runs `run_all_collectors_task` correctly. The task is scheduled daily at 1:00 AM PST via Celery Beat; you can also run it once on demand for testing.

---

## Prerequisites

- Python env with project dependencies installed: `pip install -r requirements.txt`
- **Redis** running (Celery uses it as the message broker). Default: `localhost:6379`.

  - **Windows:** Install Redis (e.g. via WSL, or [Redis for Windows](https://github.com/microsoftarchive/redis/releases)), or use Docker: `docker run -d -p 6379:6379 redis`
  - **macOS:** `brew install redis` then `brew services start redis` (or `redis-server`)
  - **Linux:** `sudo apt install redis-server` (or equivalent), then start Redis

---

## Step 1: Start the Celery worker (Terminal 1)

Open a terminal in the project root and run:

```bash
celery -A config worker -l info
```

**Windows:** The project configures the worker to use the `solo` pool on Windows automatically, so you don't get `PermissionError: [WinError 5]`. If you still see that error, run: `celery -A config worker -l info --pool=solo`

Leave this running. You should see something like:

```
[config] celery@... ready.
```

This process will **execute** tasks when they are queued (by Beat or when you trigger one manually).

---

## Step 2: Run the task once (for testing)

Open a **second** terminal in the project root.

To queue the task so it runs **immediately** (worker picks it up within a second), use the Django shell:

```bash
python manage.py shell -c "from workflow.tasks import run_all_collectors_task; run_all_collectors_task.delay()"
```

You should see the task run in **Terminal 1** (the worker), for example:

```
Task workflow.tasks.run_all_collectors_task[<id>] received
run_all_collectors_task: starting (stop_on_failure=False)
...
run_all_collectors_task: finished successfully
Task workflow.tasks.run_all_collectors_task[<id>] succeeded in ...s
```

The task runs `run_all_collectors` (same as `python manage.py run_all_collectors`), so any output or errors from that command will appear in the worker terminal or in `logs/app.log`.

---

## Optional: Use Celery Beat for the daily schedule

To run the task on the daily schedule (1:00 AM PST), start Celery Beat in a **third** terminal:

```bash
celery -A config beat -l info
```

Keep both the worker and beat running. At 1:00 AM Pacific time, Beat will queue `run_all_collectors_task` and the worker will run it.

---

## Summary

| Step | Terminal | Command |
|------|----------|---------|
| 1 | Terminal 1 | `celery -A config worker -l info` (leave running) |
| 2 | Terminal 2 | `python manage.py shell -c "from workflow.tasks import run_all_collectors_task; run_all_collectors_task.delay()"` |
| 3 | Terminal 1 | Watch for task received → succeeded |

If Redis isn't running, the shell command may hang or show a connection error; start Redis first. If the worker isn't running, the task will stay in the queue until a worker is started.
