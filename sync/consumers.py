"""
sync/consumers.py
────────────────────────────────────────────────────────────────────
JinkaSyncConsumer  —  WebSocket relay for the Jinka Couple Sync feature.

Protocol (mirrors what the frontend already sends/expects):
────────────────────────────────────────────────────────────────────
Client → Server (all messages):
  { type, user, ...payload }

Server → all OTHER clients in the room:
  Same JSON object, verbatim relay — the server never mutates payloads.

Message types the frontend produces:
  presence  { status: 'online' | 'offline', user }
  state     { trackIdx, trackTitle, currentTime, isPlaying, user }
  play      { time, user }
  pause     { time, user }
  seek      { time, user }
  track     { trackIdx, trackTitle, user }

The server additionally injects:
  connected { type:'connected', user, room, peers:[...usernames] }
    → sent only to the joining client on open
  peer_left { type:'peer_left', user }
    → sent to remaining clients when someone disconnects
────────────────────────────────────────────────────────────────────
Room strategy:
  Everyone shares one room: JINKA_ROOM = 'jinka-couple'
  This is intentional — Billi & Muntasir are the only users.
  A simple ?room= param extension is included if you ever want
  per-couple isolation.
────────────────────────────────────────────────────────────────────
"""
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

# Default shared room — matches SYNC_ROOM constant in frontend
JINKA_ROOM = 'jinka-couple'

# Registry of connected users per room: { room: { channel_name: username } }
# This lives in process memory.  For a single Daphne worker (Render free tier)
# this is perfectly fine.  If you scale to multiple workers, replace with
# a Redis-backed solution (see bottom of file for the stub).
_rooms: dict[str, dict[str, str]] = {}


class JinkaSyncConsumer(AsyncWebsocketConsumer):
    """
    One instance per connected WebSocket client.
    """

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def connect(self):
        qs   = self.scope.get('query_string', b'').decode()
        params = _parse_qs(qs)

        self.username = params.get('user', 'unknown')[:32]  # cap at 32 chars
        self.room     = params.get('room', JINKA_ROOM)[:64]

        # Join the channel layer group for this room
        await self.channel_layer.group_add(self.room, self.channel_name)

        # Register in local room registry
        _rooms.setdefault(self.room, {})[self.channel_name] = self.username

        await self.accept()

        # Tell this client who else is already in the room
        peers = [
            name for ch, name in _rooms[self.room].items()
            if ch != self.channel_name
        ]
        await self.send(json.dumps({
            'type':  'connected',
            'user':  self.username,
            'room':  self.room,
            'peers': peers,
        }))

        logger.info('CONNECT  room=%s user=%s peers=%s',
                    self.room, self.username, peers)

    async def disconnect(self, close_code):
        # Remove from room registry
        room_map = _rooms.get(self.room, {})
        room_map.pop(self.channel_name, None)

        # Notify remaining clients
        await self.channel_layer.group_send(
            self.room,
            {
                'type':        'relay',          # maps to self.relay()
                'payload':     json.dumps({
                    'type': 'peer_left',
                    'user': self.username,
                }),
                'sender':      self.channel_name,
            }
        )

        # Leave the group
        await self.channel_layer.group_discard(self.room, self.channel_name)

        logger.info('DISCONNECT room=%s user=%s code=%s',
                    self.room, self.username, close_code)

    # ── Receive from client ────────────────────────────────────────────────

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        # Validate JSON — drop malformed messages silently
        try:
            parsed = json.loads(text_data)
        except (json.JSONDecodeError, ValueError):
            logger.warning('Malformed JSON from %s: %r', self.username, text_data[:120])
            return

        # Enforce that 'user' field matches the handshake username
        # (prevents one client from spoofing another's name)
        parsed['user'] = self.username

        msg_type = parsed.get('type', '')
        logger.debug('MSG  room=%s user=%s type=%s', self.room, self.username, msg_type)

        # Relay to all OTHER clients in the room
        await self.channel_layer.group_send(
            self.room,
            {
                'type':    'relay',
                'payload': json.dumps(parsed),
                'sender':  self.channel_name,
            }
        )

    # ── Channel layer handler ──────────────────────────────────────────────

    async def relay(self, event):
        """Called on every group_send; forwards payload to this WS client,
        EXCEPT if this client was the original sender (echo prevention)."""
        if event.get('sender') == self.channel_name:
            return
        await self.send(text_data=event['payload'])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_qs(qs: str) -> dict[str, str]:
    """Minimal query-string parser — returns first value for each key."""
    result: dict[str, str] = {}
    for part in qs.split('&'):
        if '=' in part:
            k, _, v = part.partition('=')
            result[k] = v
    return result


# ── Redis-backed room registry stub (for multi-worker scaling) ───────────────
#
# If you ever add more Daphne workers or use Gunicorn with multiple processes,
# the in-memory _rooms dict will diverge between workers.  Replace it with:
#
#   import aioredis
#   redis = aioredis.from_url(os.environ['REDIS_URL'])
#
#   async def _add_peer(room, channel, username):
#       await redis.hset(f'room:{room}:peers', channel, username)
#
#   async def _remove_peer(room, channel):
#       await redis.hdel(f'room:{room}:peers', channel)
#
#   async def _list_peers(room, exclude_channel=None):
#       data = await redis.hgetall(f'room:{room}:peers')
#       return [v.decode() for k, v in data.items()
#               if k.decode() != exclude_channel]
#
# Then call these helpers in connect() / disconnect() instead of _rooms.
