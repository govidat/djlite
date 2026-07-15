Yes — two separate issues:

**1. Redis not running — Celery can't queue the task**

The error is `ConnectionRefusedError: Error 111 connecting to localhost:6379` — Redis isn't running, so Celery can't dispatch the task chain. The `run_status` stays empty because `ForecastVersion.objects.filter(pk=pk).update(run_status='QUEUED', ...)` never executes (the exception happens at `task_chain.apply_async()` before the update).

Start Redis:

```bash
# Fedora/RHEL
sudo systemctl start redis

# or directly
redis-server

# verify it's up
redis-cli ping
# should return: PONG
```

**2. Celery worker also needs to be running**

Even with Redis up, the task chain only gets *queued* by the view — a separate Celery worker process must be running to actually *execute* the tasks. Open a second terminal:

```bash
cd /home/govidat/Documents/learning/djlite
source .venv/bin/activate
celery -A your_project_name worker --loglevel=info
```

Replace `your_project_name` with your Django project's Celery app name:

```bash
grep -rn "app = Celery\|celery_app" --include="*.py" . | grep -v ".venv"
```

**3. Once both are running, the full sequence is:**

Terminal 1 — Django dev server (already running):
```bash
python manage.py runserver
```

Terminal 2 — Redis:
```bash
redis-server
```

Terminal 3 — Celery worker:
```bash
celery -A mydj worker --loglevel=info
```

Then re-send the `run/` POST from your `.http` file — you should get `202 Accepted` with `run_status: QUEUED`, and the Celery terminal will show the task chain executing (`compute_series_profiles` → `run_forecast`). Poll `run-status/` every few seconds until `run_status` changes to `COMPLETE` or `FAILED`.


Mirror is stale. Try installing directly with dnf:

```bash
sudo dnf install valkey -y
```

Valkey is the Redis-compatible fork that Fedora 42 ships. Once installed, start it:

```bash
sudo systemctl start valkey
sudo systemctl enable valkey  # auto-start on boot

# verify
valkey-cli ping
# should return: PONG
```

Then check your Django/Celery broker URL setting — it's likely set to `redis://localhost:6379/0`. Since Valkey is a drop-in Redis replacement, it runs on the same port (6379) with the same protocol, so no config change needed:

```bash
grep -rn "CELERY_BROKER_URL\|BROKER_URL\|redis://" --include="*.py" . | grep -v ".venv"
```

If the `dnf` install also fails due to mirror issues, try:

```bash
sudo dnf install valkey --refresh -y
# or force a specific mirror
sudo dnf install valkey --disablerepo="*" --enablerepo="fedora,updates" -y
```

Or as a quick alternative without installation — use Celery's in-memory broker just for local testing (no Redis needed), by temporarily adding to `settings.py`:

```python
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
```

This runs tasks synchronously in the same process — useful for testing the task logic works before wiring up Redis properly. Not for production.