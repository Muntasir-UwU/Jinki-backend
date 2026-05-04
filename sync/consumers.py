"""
consumers.py — Jinka real-time music sync
==========================================

WebSocket URL:  ws://<host>/ws/jinka/?user=<name>
Room:           jinka_room  (hardcoded, private two-person room)

Redis keys
----------
jinka:sync_state        JSON: {trackIdx, currentTime, isPlaying, lastUpdatedAt}
jinka:presence:<name>   float: Unix timestamp of last heartbeat  (TTL 200 s)
jinka:conn_count        int:   currently connected WebSocket clients
"""

import asyncio
import json
import logging
import time
from urllib.parse import parse_qs, unquote

import aiohttp
import redis.asyncio as aioredis
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
ROOM_GROUP = "jinka_room"

AWAY_TIMEOUT = 35       # seconds since last heartbeat → status "away"
OFFLINE_TIMEOUT = 90    # seconds since last heartbeat → status "offline"
DRIFT_INTERVAL = 30     # seconds between periodic sync_state broadcasts
PING_INTERVAL = 600     # 10 min self-ping to keep free-tier dyno alive
PRESENCE_TTL = 200      # Redis key TTL for presence records (generous buffer)

SYNC_STATE_KEY = "jinka:sync_state"
PRESENCE_KEY_PREFIX = "jinka:presence:"
CONN_COUNT_KEY = "jinka:conn_count"

# ── Module-level singletons ──────────────────────────────────────────────────
_redis_client: aioredis.Redis | None = None
_drift_task: asyncio.Task | None = None
_ping_task: asyncio.Task | None = None


def _get_redis() -> aioredis.Redis:
    """Return (and lazily create) the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_client


# ── Background tasks (module-level, shared across all consumer instances) ────

async def _drift_broadcaster():
    """
    Every DRIFT_INTERVAL seconds, send the current sync_state to every
    connected client so they can self-correct minor playback drift.
    Runs as long as the process is alive; skips beats when nobody is online.
    """
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    redis = _get_redis()

    logger.info("Drift broadcaster started.")
    try:
        while True:
            await asyncio.sleep(DRIFT_INTERVAL)

            count_raw = await redis.get(CONN_COUNT_KEY)
            if not count_raw or int(count_raw) < 1:
                continue  # nobody home — skip this beat

            raw = await redis.get(SYNC_STATE_KEY)
            if not raw:
                continue

            state = json.loads(raw)
            now = time.time()
            current_time = _corrected_time(state, now)

            await channel_layer.group_send(
                ROOM_GROUP,
                {
                    "type": "send_json_to_client",
                    "data": {
                        "type": "sync_state",
                        "trackIdx": state.get("trackIdx", 0),
                        "currentTime": round(current_time, 3),
                        "isPlaying": state.get("isPlaying", False),
                        "timestamp": now,
                    },
                },
            )
    except asyncio.CancelledError:
        logger.info("Drift broadcaster stopped.")
    except Exception:
        logger.exception("Drift broadcaster crashed — will restart on next connect.")


async def _self_pinger():
    """
    GET /health/ every PING_INTERVAL seconds so the free-tier dyno never idles.
    Only runs when SELF_PING_URL is set in the environment.
    """
    url = getattr(settings, "SELF_PING_URL", "").rstrip("/")
    if not url:
        logger.info("SELF_PING_URL not set — self-ping disabled.")
        return

    logger.info("Self-pinger started → %s/health/", url)
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{url}/health/",
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        logger.info("Self-ping → %s  status=%s", f"{url}/health/", resp.status)
            except Exception as exc:
                logger.warning("Self-ping failed: %s", exc)
    except asyncio.CancelledError:
        logger.info("Self-pinger stopped.")


async def _ensure_background_tasks():
    """Start drift broadcaster and self-pinger if they aren't already running."""
    global _drift_task, _ping_task

    if _drift_task is None or _drift_task.done():
        _drift_task = asyncio.create_task(_drift_broadcaster())

    if _ping_task is None or _ping_task.done():
        _ping_task = asyncio.create_task(_self_pinger())


# ── Helpers ──────────────────────────────────────────────────────────────────

def _corrected_time(state: dict, now: float) -> float:
    """
    If the track was playing, add elapsed time since the state was last saved.
    This gives a late-joiner the time-corrected position.
    """
    ct = state.get("currentTime", 0.0)
    if state.get("isPlaying"):
        ct += now - state.get("lastUpdatedAt", now)
    return max(0.0, ct)


# ── Consumer ─────────────────────────────────────────────────────────────────

class JinkaConsumer(AsyncWebsocketConsumer):
    """
    One instance per WebSocket connection.

    Query-string param:  ?user=<name>   (e.g. ws://host/ws/jinka/?user=Billi)
    If omitted, a short anonymous ID is assigned.
    """

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        # Parse username from query string
        qs = self.scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(qs)
        raw_name = params.get("user", [None])[0]
        self.username: str = unquote(raw_name) if raw_name else f"anon_{id(self) % 9999}"

        await self.channel_layer.group_add(ROOM_GROUP, self.channel_name)
        await self.accept()

        redis = _get_redis()
        await redis.incr(CONN_COUNT_KEY)

        # Record heartbeat so presence monitor starts fresh
        await self._touch_presence()

        # Tell the room this user is online
        await self._broadcast_presence("online")

        # Send the late-joiner the time-corrected sync state immediately
        await self._push_sync_state_to_self()

        # Kick off shared background tasks
        await _ensure_background_tasks()

        # Per-connection presence watchdog
        self._presence_status = "online"
        self._presence_task: asyncio.Task = asyncio.create_task(
            self._presence_watchdog()
        )

        logger.info("CONNECT  user=%s  channel=%s", self.username, self.channel_name)

    async def disconnect(self, close_code):
        logger.info(
            "DISCONNECT  user=%s  channel=%s  code=%s",
            self.username, self.channel_name, close_code,
        )

        # Cancel watchdog first
        if hasattr(self, "_presence_task"):
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass

        redis = _get_redis()
        await redis.decr(CONN_COUNT_KEY)
        await redis.delete(f"{PRESENCE_KEY_PREFIX}{self.username}")

        await self._broadcast_presence("offline")
        await self.channel_layer.group_discard(ROOM_GROUP, self.channel_name)

    async def receive(self, text_data: str):
        try:
            data: dict = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")
        logger.debug("RECV  user=%s  type=%s", self.username, msg_type)

        if msg_type == "heartbeat":
            await self._touch_presence()
            # Recover to "online" if the user had drifted to away
            if self._presence_status != "online":
                self._presence_status = "online"
                await self._broadcast_presence("online")

        elif msg_type in ("play", "pause", "seek", "track"):
            await self._update_sync_state(data)

            # Relay to the other user — NOT back to the sender
            await self.channel_layer.group_send(
                ROOM_GROUP,
                {
                    "type": "relay_to_partner",
                    "data": data,
                    "sender_channel": self.channel_name,
                },
            )

    # ── Channel-layer message handlers ───────────────────────────────────────

    async def relay_to_partner(self, event: dict):
        """Forward play/pause/seek/track — skip the sender."""
        if event["sender_channel"] != self.channel_name:
            await self.send(text_data=json.dumps(event["data"]))

    async def send_json_to_client(self, event: dict):
        """Generic handler for sync_state and presence broadcasts."""
        await self.send(text_data=json.dumps(event["data"]))

    # ── Sync state ───────────────────────────────────────────────────────────

    async def _push_sync_state_to_self(self):
        """Send the current (time-corrected) sync state to this connection only."""
        redis = _get_redis()
        raw = await redis.get(SYNC_STATE_KEY)
        if not raw:
            return  # nobody has played anything yet

        state = json.loads(raw)
        now = time.time()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "sync_state",
                    "trackIdx": state.get("trackIdx", 0),
                    "currentTime": round(_corrected_time(state, now), 3),
                    "isPlaying": state.get("isPlaying", False),
                    "timestamp": now,
                }
            )
        )

    async def _update_sync_state(self, data: dict):
        """
        Merge an incoming play/pause/seek/track message into the Redis sync state.
        Always stamps lastUpdatedAt with the server's current time.
        """
        redis = _get_redis()
        raw = await redis.get(SYNC_STATE_KEY)
        state: dict = (
            json.loads(raw)
            if raw
            else {"trackIdx": 0, "currentTime": 0.0, "isPlaying": False}
        )

        msg_type = data["type"]

        if msg_type == "play":
            state["isPlaying"] = True
            state["currentTime"] = data.get("currentTime", state["currentTime"])
            if "trackIdx" in data:
                state["trackIdx"] = data["trackIdx"]

        elif msg_type == "pause":
            state["isPlaying"] = False
            state["currentTime"] = data.get("currentTime", state["currentTime"])

        elif msg_type == "seek":
            # Preserve isPlaying; just update position
            state["currentTime"] = data.get("currentTime", state["currentTime"])

        elif msg_type == "track":
            state["trackIdx"] = data.get("trackIdx", state["trackIdx"])
            state["currentTime"] = 0.0
            state["isPlaying"] = False

        state["lastUpdatedAt"] = time.time()
        await redis.set(SYNC_STATE_KEY, json.dumps(state))

    # ── Presence ─────────────────────────────────────────────────────────────

    async def _touch_presence(self):
        """Stamp the current Unix time as this user's last-seen timestamp."""
        redis = _get_redis()
        await redis.set(
            f"{PRESENCE_KEY_PREFIX}{self.username}",
            time.time(),
            ex=PRESENCE_TTL,
        )

    async def _broadcast_presence(self, status: str):
        """Broadcast a presence update for this user to the whole room."""
        await self.channel_layer.group_send(
            ROOM_GROUP,
            {
                "type": "send_json_to_client",
                "data": {
                    "type": "presence",
                    "user": self.username,
                    "status": status,
                },
            },
        )

    async def _presence_watchdog(self):
        """
        Per-connection background task.
        Polls Redis every 5 seconds; fires status transitions:
            online  →  away    (after AWAY_TIMEOUT seconds without heartbeat)
            away    →  offline (after OFFLINE_TIMEOUT seconds without heartbeat)

        The WebSocket itself stays open — away/offline just means the other
        user sees the partner has left the tab idle.
        """
        redis = _get_redis()
        try:
            while True:
                await asyncio.sleep(5)

                raw = await redis.get(f"{PRESENCE_KEY_PREFIX}{self.username}")
                if raw is None:
                    new_status = "offline"
                else:
                    elapsed = time.time() - float(raw)
                    if elapsed >= OFFLINE_TIMEOUT:
                        new_status = "offline"
                    elif elapsed >= AWAY_TIMEOUT:
                        new_status = "away"
                    else:
                        new_status = "online"

                if new_status != self._presence_status:
                    logger.info(
                        "PRESENCE  user=%s  %s → %s",
                        self.username, self._presence_status, new_status,
                    )
                    self._presence_status = new_status
                    await self._broadcast_presence(new_status)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Presence watchdog crashed for user=%s", self.username)
