import sys
import socket
from .base import *

DEBUG = True

DB_ENGINE = config('DB_ENGINE', default='').lower()

if DB_ENGINE == 'sqlite' or 'test' in sys.argv:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    pg_host = config('DB_HOST', default='localhost')
    pg_port = int(config('DB_PORT', default=5432))
    pg_available = False
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1):
            pg_available = True
    except OSError:
        pg_available = False

    if pg_available:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': config('DB_NAME', default='pulsenotify_db'),
                'USER': config('DB_USER', default='pulsenotify_user'),
                'PASSWORD': config('DB_PASSWORD', default='pulsenotify_pass'),
                'HOST': pg_host,
                'PORT': str(pg_port),
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
