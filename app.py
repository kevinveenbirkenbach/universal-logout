import logging
import sys
import os
from flask import Flask, request, make_response, render_template

app = Flask(__name__, template_folder='templates')

DOMAINS = os.getenv('LOGOUT_DOMAINS', '').split(',') if os.getenv('LOGOUT_DOMAINS') else []
DEBUG = os.getenv('DEBUG_LOGOUT', 'false').lower() in ('1', 'true', 'yes')

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

@app.route('/')
def conductor():
    return render_template('conductor.html.j2', domains=DOMAINS)

@app.route('/logout')
def logout():
    host = request.host.split(':')[0]
    parts = host.split('.')
    parent_domain = '.' + '.'.join(parts[-2:])

    if DEBUG:
        logger.debug(f"Incoming host: {host}")
        logger.debug(f"Derived parent domain for cookie deletion: {parent_domain}")

    cookie_header = request.headers.get('Cookie', '')
    cookie_names = []
    for part in cookie_header.split(';'):
        if '=' in part:
            name = part.split('=', 1)[0].strip()
            if name:
                cookie_names.append(name)

    if DEBUG:
        logger.debug(f"Cookies to expire: {cookie_names}")

    response = make_response('You have been logged out.', 200)
    for name in cookie_names:
        if DEBUG:
            logger.debug(f"Expiring cookie: {name} on domain {parent_domain}")
        response.set_cookie(
            key=name,
            value='',
            expires=0,
            domain=parent_domain,
            path='/',
            secure=True,
            httponly=True,
            samesite='Lax'
        )
    return response
