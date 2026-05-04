from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/sync/(?P<room_id>[\w-]+)/$", consumers.SyncConsumer.as_asgi()),
]
