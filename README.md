# Jinka Sync Backend

Real-time music sync server for the **Jinka** web music player.

- **Django 4.2 + Django Channels 4 + Redis**
- WebSocket endpoint: `ws://<host>/ws/jinka/?user=<name>`
- HTTP health check: `GET /health/`

---

## How it works

| Feature | Detail |
|---|---|
| **Message relay** | `play / pause / seek / track` are forwarded to the partner only — never echoed to the sender |
| **Sync state** | Stored in Redis; late-joiners receive a time-corrected `sync_state` on connect |
| **Drift correction** | Broadcast every 30 s so both players stay frame-accurate |
| **Presence** | `online → away (35 s) → offline (90 s)` tracked via heartbeat timestamps |
| **Self-ping** | GET `/health/` every 10 min to keep free-tier dynos awake |

---

## Local development

### Prerequisites

- Python 3.11+
- Docker (for Redis) — or a local Redis installation

### 1 — Clone & install

```bash
git clone <repo>
cd jinka_backend

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2 — Configure environment

```bash
cp .env.example .env
# Open .env and set DJANGO_SECRET_KEY at minimum.
# Leave SELF_PING_URL blank for local dev.
```

### 3 — Start Redis

**Terminal 1:**
```bash
docker run --rm -p 6379:6379 redis:7
```

### 4 — Start the server

**Terminal 2:**
```bash
python manage.py migrate        # only needed once
python manage.py runserver
```

Daphne (installed via `channels[daphne]`) is used automatically as the ASGI server.

---

## Testing with two browser tabs

Open your browser's DevTools console in **Tab A** and run:

```javascript
// Tab A — Muntasir
const ws = new WebSocket("ws://localhost:8000/ws/jinka/?user=Muntasir");
ws.onmessage = e => console.log("A received:", JSON.parse(e.data));
ws.onopen = () => console.log("A connected");

// Simulate playing track 2 at 34.5 s
ws.send(JSON.stringify({ type: "play", trackIdx: 2, currentTime: 34.5, title: "Test Song" }));

// Heartbeat (repeat every ~10 s to stay "online")
setInterval(() => ws.send(JSON.stringify({ type: "heartbeat", status: "online" })), 10000);
```

Open a **second tab** and run:

```javascript
// Tab B — Billi (open this 20 seconds after Tab A started playing)
const ws = new WebSocket("ws://localhost:8000/ws/jinka/?user=Billi");
ws.onmessage = e => console.log("B received:", JSON.parse(e.data));
ws.onopen = () => console.log("B connected");
// Watch the console — B will immediately receive a sync_state with
// currentTime ≈ 34.5 + <elapsed seconds> so it jumps to the right position.
```

**Health check:**
```bash
curl http://localhost:8000/health/
# {"status": "ok", "connections": 2}
```

---

## Deploying to Railway

1. Push this repo to GitHub.
2. Create a new Railway project → **Deploy from GitHub repo**.
3. Add a **Redis** plugin from the Railway dashboard (it auto-sets `REDIS_URL`).
4. Set environment variables under **Variables**:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | *(generate with the command above)* |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `your-app.up.railway.app` |
| `CORS_ALLOWED_ORIGINS` | `https://muntasir-uwu.github.io` |
| `SELF_PING_URL` | `https://your-app.up.railway.app` |

Railway detects the `Procfile` and runs Daphne automatically.

### Deploying to Render

Same steps. Use **Web Service**, set **Start Command** to:
```
daphne -b 0.0.0.0 -p $PORT jinka_backend.asgi:application
```
Add a Redis instance from the Render dashboard and copy its `REDIS_URL`.

---

## Connecting the Jinka frontend

In your HTML/JS, open the WebSocket like this:

```javascript
const BACKEND = "wss://your-app.up.railway.app";  // or ws://localhost:8000 locally
const ws = new WebSocket(`${BACKEND}/ws/jinka/?user=Muntasir`);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "sync_state") {
    // Jump to msg.currentTime on track msg.trackIdx
  } else if (msg.type === "presence") {
    // Show msg.user is msg.status (online / away / offline)
  } else if (msg.type === "play") {
    // Partner pressed play at msg.currentTime
  } else if (msg.type === "pause") {
    // Partner paused at msg.currentTime
  } else if (msg.type === "seek") {
    // Partner seeked to msg.currentTime
  } else if (msg.type === "track") {
    // Partner switched to trackIdx msg.trackIdx
  }
};

// Send heartbeat every 10 s
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({ type: "heartbeat", status: "online" }));
}, 10000);
```

---

## Project structure

```
jinka_backend/
├── manage.py
├── requirements.txt
├── Procfile
├── .env.example
├── jinka_backend/
│   ├── asgi.py          ← ASGI + WebSocket routing
│   ├── settings.py
│   └── urls.py          ← /health/
└── sync/
    ├── apps.py          ← resets conn_count on startup
    ├── consumers.py     ← full WebSocket consumer
    └── views.py         ← health check
```
