from decimal import Decimal, InvalidOperation
from django.core.exceptions import ImproperlyConfigured
import sys
import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DJANGO_DEBUG', 'False').strip().lower() in ('1', 'true', 'yes', 'on')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'dev-only-change-me'  # Local development only; never use with DEBUG=False.
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DEBUG is disabled.')
ALLOWED_HOSTS = [x.strip() for x in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,backend' if DEBUG else '').split(',') if x.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must contain at least one host when DEBUG is disabled.')
INSTALLED_APPS = [
    'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions',
    'django.contrib.messages','django.contrib.staticfiles','rest_framework','corsheaders','core',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware','corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME': BASE_DIR / 'db.sqlite3'}}
AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [
 {'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
 {'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},
 {'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},
 {'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE='en-us'; TIME_ZONE='Asia/Kolkata'; USE_I18N=True; USE_TZ=True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173' if DEBUG else '').split(',') if x.strip()]
# Vite moves to 5174, 5175... when 5173 is busy; in local dev accept any localhost/127.0.0.1 port so login never fails with 'Failed to fetch'.
CORS_ALLOWED_ORIGIN_REGEXES = [r'^http://(localhost|127\.0\.0\.1):\d+$'] if DEBUG else []
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + ['cache-control', 'pragma']
CORS_ALLOW_ALL_ORIGINS = DEBUG
REST_FRAMEWORK = {
 'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
 'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
 'DEFAULT_THROTTLE_CLASSES': [
     'rest_framework.throttling.AnonRateThrottle',
     'rest_framework.throttling.UserRateThrottle',
 ],
 'DEFAULT_THROTTLE_RATES': {
     'anon': os.getenv('API_ANON_RATE', '100/hour'),
     'user': os.getenv('API_USER_RATE', '1200/hour'),
 },
 'DEFAULT_RENDERER_CLASSES': (
     ('rest_framework.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer')
     if DEBUG else ('rest_framework.renderers.JSONRenderer',)
 ),
}
from datetime import timedelta
SIMPLE_JWT = {'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60), 'REFRESH_TOKEN_LIFETIME': timedelta(days=7)}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Phase 5: production security defaults. Configure TLS at the reverse proxy/load balancer.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.getenv('DJANGO_SECURE_SSL_REDIRECT', 'False' if DEBUG else 'True').strip().lower() in ('1', 'true', 'yes', 'on')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = os.getenv('DJANGO_HSTS_PRELOAD', 'False').strip().lower() in ('1', 'true', 'yes', 'on')
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]

# Keep production database connections healthy; require SSL for non-debug deployments.
CONN_HEALTH_CHECKS = True
if DATABASE_URL and not DEBUG:
    DATABASES['default']['OPTIONS'] = {**DATABASES['default'].get('OPTIONS', {}), 'sslmode': 'require'}

# PayPal marketplace (server-side credentials; never expose these to React)
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')
PAYPAL_BASE_URL = os.getenv('PAYPAL_BASE_URL', 'https://api-m.sandbox.paypal.com').rstrip('/')
if PAYPAL_BASE_URL not in ('https://api-m.sandbox.paypal.com', 'https://api-m.paypal.com'):
    raise ImproperlyConfigured('PAYPAL_BASE_URL must be the official PayPal sandbox or live API origin.')
PAYPAL_WEBHOOK_ID = os.getenv('PAYPAL_WEBHOOK_ID', '')
if not DEBUG and (not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET or not PAYPAL_WEBHOOK_ID):
    raise ImproperlyConfigured('Production requires PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and PAYPAL_WEBHOOK_ID.')
PLATFORM_FEE_PERCENT = os.getenv('PLATFORM_FEE_PERCENT', '1')
# Fail fast on a mistyped fee (e.g. '10%') instead of crashing later in the middle of a payment capture.
try:
    if not (Decimal(PLATFORM_FEE_PERCENT) >= 0 and Decimal(PLATFORM_FEE_PERCENT) <= 100): raise ValueError
except (InvalidOperation, ValueError):
    raise ImproperlyConfigured("PLATFORM_FEE_PERCENT must be a plain number between 0 and 100 (for example 10), not %r." % PLATFORM_FEE_PERCENT)

FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

# Much faster test runs: password hashing is deliberately slow and irrelevant to tests.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


# Structured application logging: never log request bodies or PayPal credentials.
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'core': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}
