import os
bind = '0.0.0.0:5000'
workers = int(os.getenv('WEB_WORKERS', '2'))
worker_class = 'gthread'
threads = int(os.getenv('WEB_THREADS', '4'))
timeout = int(os.getenv('WEB_TIMEOUT', '1800'))
graceful_timeout = 45
accesslog = '-'
errorlog = '-'


def on_starting(server):
    from config import assert_safe_runtime
    assert_safe_runtime()
