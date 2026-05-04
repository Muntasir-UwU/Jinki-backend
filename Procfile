# Daphne serves both HTTP and WebSocket over the same port.
# $PORT is injected automatically by Railway and Render.
web: daphne -b 0.0.0.0 -p ${PORT:-8000} jinka_backend.asgi:application
