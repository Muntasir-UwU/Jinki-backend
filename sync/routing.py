from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Changed SyncConsumer to JinkaSyncConsumer
    re_path(r"^ws/sync/(?P<room_id>[\w-]+)/$", consumers.JinkaSyncConsumer.as_asgi()),
]
