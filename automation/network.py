from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import Blocked


class ApiFailure(Blocked):
    def __init__(self, code: str, http_status: int = 0, transient: bool = False, provider_code=None, provider_subcode=None):
        self.http_status, self.transient = http_status, transient
        self.provider_code = provider_code if type(provider_code) is int else None
        self.provider_subcode = provider_subcode if type(provider_subcode) is int else None
        super().__init__(code, manual=http_status in (400, 401, 403))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, timeout: int = 25, sleep=time.sleep):
        self.timeout, self.sleep = timeout, sleep
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method: str, url: str, headers=None, body=None, form=False, retries=3):
        # Automatic retries are for reads only. Mutating endpoints require their own durable protocol.
        attempts = retries if method == 'GET' else 1
        headers = dict(headers or {})
        headers.setdefault('User-Agent', 'MultiBrandInstagram/1.0')
        data = None
        if body is not None:
            if form:
                data = urllib.parse.urlencode(body).encode('utf-8')
                headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
            else:
                data = json.dumps(body, ensure_ascii=False).encode('utf-8')
                headers['Content-Type'] = 'application/json'
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    raw = response.read(12_000_001)
                    if len(raw) > 12_000_000:
                        raise ApiFailure('RESPONSE_TOO_LARGE')
                    mime = response.headers.get_content_type()
                    return raw, mime
            except urllib.error.HTTPError as error:
                status = error.code
                # Never expose provider error text; it may echo tokens, URLs, captions or headers.
                provider_code = provider_subcode = None
                try:
                    details = json.loads(error.read(65536)).get('error', {})
                    if isinstance(details, dict):
                        provider_code = details.get('code')
                        provider_subcode = details.get('error_subcode')
                except (ValueError, AttributeError, OSError):
                    pass
                finally:
                    error.close()
                transient = status in (408, 429, 500, 502, 503, 504)
                failure = ApiFailure('HTTP_' + str(status), status, transient, provider_code, provider_subcode)
            except (urllib.error.URLError, TimeoutError, OSError):
                failure = ApiFailure('NETWORK_UNAVAILABLE', transient=True)
            if not failure.transient or attempt == attempts - 1:
                raise failure from None
            self.sleep(min(2 ** attempt, 4))
        raise ApiFailure('NETWORK_UNAVAILABLE')

    def json(self, method: str, url: str, **kwargs):
        raw, _ = self.request(method, url, **kwargs)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise ApiFailure('INVALID_API_RESPONSE') from None


class MetaClient:
    """Same Graph v26 Facebook Login/container flow as the audited PowerShell publisher."""
    def __init__(self, config: dict, creds: dict, transport=None):
        self.config, self.creds = config, creds
        self.transport = transport or Transport()
        version = config['api_version']
        import re
        if not re.fullmatch(r'v\d+\.0', version):
            raise Blocked('INVALID_GRAPH_VERSION')
        self.base = 'https://graph.facebook.com/' + version + '/'

    def get(self, node: str, fields: str, **params):
        return self.transport.json('GET', self.base + node + '?' + urllib.parse.urlencode({'fields': fields, **params}),
                                   headers={'Authorization': 'Bearer ' + self.creds['token']})

    def post(self, edge: str, fields: dict):
        return self.transport.json('POST', self.base + self.creds['instagram_user_id'] + '/' + edge,
                                   headers={'Authorization': 'Bearer ' + self.creds['token']}, body=fields, form=True)

    def verify_account(self) -> dict:
        target = self.config['target']
        page = self.get(target['facebook_page_id'], 'id,name,instagram_business_account')
        ig = self.get(target['instagram_user_id'], 'id,username')
        if (str(page.get('id')) != target['facebook_page_id'] or
            str(page.get('instagram_business_account', {}).get('id')) != target['instagram_user_id'] or
            str(ig.get('id')) != target['instagram_user_id'] or
            str(ig.get('username', '')).casefold() != target['username'].casefold()):
            raise Blocked('LIVE_ACCOUNT_MISMATCH')
        if self.config.get('expected_facebook_page_name') and page.get('name') != self.config['expected_facebook_page_name']:
            raise Blocked('LIVE_FACEBOOK_PAGE_NAME_MISMATCH')
        limit = self.get(target['instagram_user_id'] + '/content_publishing_limit', 'config,quota_usage')
        if not limit.get('data'):
            raise Blocked('PUBLISH_PERMISSION_NOT_READABLE', manual=True)
        for entry in limit['data']:
            cap = entry.get('config', {}).get('quota_total')
            if cap is not None and entry.get('quota_usage', 0) >= cap:
                raise Blocked('META_QUOTA_EXHAUSTED')
        return {'instagram_user_id': str(ig['id']), 'username': ig['username'],
                'facebook_page_id': str(page['id']), 'facebook_page_name': page.get('name'), 'api_access': True}

    def wait_container(self, creation_id: str):
        for _ in range(30):
            result = self.get(creation_id, 'id,status_code')
            code = result.get('status_code')
            if code == 'FINISHED':
                return
            if code in ('ERROR', 'EXPIRED', 'PUBLISHED'):
                raise Blocked('CONTAINER_' + code, manual=code == 'PUBLISHED')
            self.transport.sleep(2)
        raise Blocked('CONTAINER_TIMEOUT', manual=True)

    def recent_media(self):
        return self.get(self.creds['instagram_user_id'] + '/media', 'id,caption,media_type,media_url,permalink,timestamp', limit=100).get('data', [])
