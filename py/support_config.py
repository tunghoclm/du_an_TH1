"""AI provider configuration and encrypted credentials, including legacy Gemini settings."""
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

import database


DEFAULT_MODEL = 'gemini-3.5-flash-lite'
SETTING_KEY = 'support:ai'
LEGACY_SETTING_KEY = 'support:gemini'
PROVIDERS = {
    'gemini': dict(label='Google Gemini', protocol='gemini', base_url='https://generativelanguage.googleapis.com/v1beta',
                   default_model=DEFAULT_MODEL, docs_url='https://aistudio.google.com/apikey', key_env='GEMINI_API_KEY'),
    'openai': dict(label='OpenAI', protocol='openai', base_url='https://api.openai.com/v1',
                  default_model='', docs_url='https://platform.openai.com/api-keys', key_env='OPENAI_API_KEY'),
    'anthropic': dict(label='Anthropic · Claude', protocol='anthropic', base_url='https://api.anthropic.com/v1',
                     default_model='', docs_url='https://platform.claude.com/settings/keys', key_env='ANTHROPIC_API_KEY'),
    'deepseek': dict(label='DeepSeek', protocol='openai', base_url='https://api.deepseek.com',
                    default_model='deepseek-flash', docs_url='https://platform.deepseek.com/api_keys', key_env='DEEPSEEK_API_KEY'),
    'compatible': dict(label='Tùy chỉnh · tương thích OpenAI', protocol='openai', base_url='',
                      default_model='', docs_url='', key_env='SUPPORT_AI_API_KEY'),
}
_key_lock = threading.Lock()


class ConfigError(Exception):
    pass


def _cipher(create=False):
    path = Path(database.DB_PATH).resolve().parent / 'secrets' / 'gemini.key'
    try:
        with _key_lock:
            if create:
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                try:
                    with path.open('xb') as handle:
                        os.chmod(path, 0o600)
                        handle.write(Fernet.generate_key())
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    pass
            return Fernet(path.read_bytes())
    except (OSError, ValueError):
        raise ConfigError('Không đọc được khóa mã hóa trên máy chủ. Hãy khôi phục tệp khóa hoặc liên hệ người vận hành.') from None


def validate_connection(provider, model, base_url):
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ConfigError('Nhà cung cấp AI chưa được hỗ trợ.')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model) or '://' in model:
        raise ConfigError('Vui lòng nhập mã model hợp lệ của nhà cung cấp.')
    if provider == 'gemini' and not re.fullmatch(r'gemini-[a-z0-9._-]{1,90}', model):
        raise ConfigError('Tên model Gemini chưa hợp lệ. Ví dụ: ' + DEFAULT_MODEL + '.')
    preset = PROVIDERS[provider]
    if not isinstance(base_url, str):
        raise ConfigError('Địa chỉ API chưa hợp lệ.')
    base_url = base_url.strip().rstrip('/')
    if provider != 'compatible':
        if base_url and base_url != preset['base_url']:
            raise ConfigError('Để dùng địa chỉ API khác, hãy chọn nhà cung cấp Tùy chỉnh.')
        return preset['base_url']
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        if (len(base_url) > 500 or parts.scheme != 'https' or not host or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment or parts.port == 0
                or re.search(r'[\s\\%\x00-\x1f\x7f]', base_url)):
            raise ValueError
        host = host.encode('idna').decode('ascii').lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError
        except ValueError:
            if re.fullmatch(r'[0-9.:]+', host) or ':' in host:
                raise ValueError
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host:
                raise ValueError
        netloc = ('[' + host + ']') if ':' in host else host
        if parts.port and parts.port != 443:
            netloc += ':' + str(parts.port)
        path = parts.path.rstrip('/')
        if path.endswith('/chat/completions'):
            path = path[:-len('/chat/completions')]
        return urlunsplit(('https', netloc, path, '', ''))
    except (ValueError, UnicodeError):
        raise ConfigError('API tùy chỉnh cần địa chỉ HTTPS công khai, không chứa khóa, tham số truy vấn hoặc địa chỉ nội bộ.') from None


def _empty(source='none', error=''):
    return dict(key='', model=DEFAULT_MODEL, provider='gemini', base_url=PROVIDERS['gemini']['base_url'], source=source, error=error)


def load():
    raw = database.get_setting(SETTING_KEY)
    if raw is None:
        raw = database.get_setting(LEGACY_SETTING_KEY)
    if raw is None:
        provider = os.environ.get('SUPPORT_AI_PROVIDER', 'gemini').strip() or 'gemini'
        preset = PROVIDERS.get(provider, PROVIDERS['gemini'])
        key = (os.environ.get('SUPPORT_AI_API_KEY') or os.environ.get(preset['key_env']) or
               (os.environ.get('GOOGLE_API_KEY') if provider == 'gemini' else '') or '').strip()
        model = (os.environ.get('SUPPORT_AI_MODEL') or
                 (os.environ.get('GEMINI_MODEL') if provider == 'gemini' else '') or preset['default_model']).strip()
        if not key and provider == 'gemini' and not model:
            model = DEFAULT_MODEL
        base_url = os.environ.get('SUPPORT_AI_BASE_URL', '')
        if not key and provider == 'gemini':
            return _empty()
        try:
            base_url = validate_connection(provider, model, base_url)
        except ConfigError:
            return _empty(source='environment', error='Cấu hình AI trong biến môi trường chưa hợp lệ. Hãy kiểm tra nhà cung cấp, model và địa chỉ API.')
        return dict(key=key, model=model, provider=provider, base_url=base_url, source='environment' if key else 'none', error='')
    try:
        saved = json.loads(raw)
        if not isinstance(saved, dict) or not isinstance(saved.get('model'), str):
            raise ValueError
        provider = saved.get('provider', 'gemini')
        base_url = validate_connection(provider, saved['model'], saved.get('base_url', ''))
        if saved.get('enabled') is False:
            return dict(key='', model=saved['model'], provider=provider, base_url=base_url, source='disabled', error='')
        if saved.get('enabled') is not True or not isinstance(saved.get('api_key'), str):
            raise ValueError
        key = _cipher().decrypt(saved['api_key'].encode('ascii')).decode('utf-8')
        return dict(key=key, model=saved['model'], provider=provider, base_url=base_url, source='settings', error='')
    except (ConfigError, InvalidToken, ValueError, TypeError, UnicodeError):
        return _empty(source='settings', error='Chưa đọc được cấu hình AI đã lưu. Hãy kiểm tra tệp khóa mã hóa trên máy chủ hoặc nhập lại khóa API.')


def public_settings():
    config = load()
    return dict(configured=bool(config['key']), model=config['model'], provider=config['provider'], base_url=config['base_url'],
                source=config['source'], error=config['error'], providers=[dict(id=key, **{k:v for k,v in value.items() if k != 'key_env'}) for key,value in PROVIDERS.items()])


def identity(config=None):
    config = config or load()
    label = PROVIDERS[config['provider']]['label']
    if config['provider'] == 'compatible':
        label = urlsplit(config['base_url']).hostname or 'API tùy chỉnh'
    return dict(label=label, provider=config['provider'])


def save(api_key, model, provider='gemini', base_url=''):
    if not isinstance(api_key, str) or not isinstance(model, str):
        raise ConfigError('Cấu hình gửi chưa hợp lệ.')
    api_key, model = api_key.strip(), model.strip()
    base_url = validate_connection(provider, model, base_url)
    if api_key and not re.fullmatch(r'[\x21-\x7e]{16,4096}', api_key):
        raise ConfigError('Khóa API chưa hợp lệ. Hãy sao chép lại khóa từ nhà cung cấp, không thêm khoảng trắng hoặc xuống dòng.')
    if not api_key:
        current = load()
        if (provider, base_url) != (current['provider'], current['base_url']):
            raise ConfigError('Khi đổi nhà cung cấp hoặc địa chỉ API, vui lòng nhập khóa tương ứng.')
        api_key = current['key']
    if not api_key:
        raise ConfigError('Vui lòng nhập khóa API để kết nối trợ lý AI.')
    encrypted = _cipher(create=True).encrypt(api_key.encode('utf-8')).decode('ascii')
    _store(dict(enabled=True, api_key=encrypted, model=model, provider=provider, base_url=base_url))
    return public_settings()


def disconnect():
    current = load()
    _store(dict(enabled=False, model=current['model'], provider=current['provider'], base_url=current['base_url']))
    return public_settings()


def _store(value):
    conn = database.get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (SETTING_KEY, json.dumps(value)))
        conn.execute('DELETE FROM settings WHERE key=?', (LEGACY_SETTING_KEY,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
