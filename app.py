from flask import Flask, request, make_response

app = Flask(__name__)

@app.route('/logout')
def logout():
    # 1) Determine the host (e.g., 'app.cymais.cloud')
    host = request.host.split(':')[0]
    # 2) Derive parent domain (e.g., '.cymais.cloud')
    parts = host.split('.')
    parent_domain = '.' + '.'.join(parts[-2:])

    # 3) Parse all cookie names from the Cookie header
    cookie_header = request.headers.get('Cookie', '')
    cookie_names = []
    for part in cookie_header.split(';'):
        if '=' in part:
            name = part.split('=', 1)[0].strip()
            if name:
                cookie_names.append(name)

    # 4) Build response with expired Set-Cookie headers
    response = make_response('You have been logged out.', 200)
    for name in cookie_names:
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

if __name__ == '__main__':
    # For development only; use Gunicorn in production
    app.run(host='0.0.0.0', port=8000)
