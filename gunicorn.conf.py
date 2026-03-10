"""Gunicorn production config."""
import multiprocessing
import os

# Bind
bind = "127.0.0.1:5000"

# Workers
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
timeout = 120

# Logging
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"

# Process
daemon = False
pidfile = "/tmp/gunicorn.pid"

# Restart workers after this many requests (prevent memory leaks)
max_requests = 1000
max_requests_jitter = 50
