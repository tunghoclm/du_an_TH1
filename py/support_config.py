"""Configuration for the exclusively local support assistant."""
import support_knowledge

ConfigError = support_knowledge.KnowledgeError


def load():
    return support_knowledge.status()


def public_settings():
    return load()


def identity(config=None):
    config = config or load()
    return dict(label=config['name'], provider='local')


def save(data):
    if any(key in data for key in ('api_key', 'base_url', 'model', 'provider')):
        raise ConfigError('Trợ lý chỉ chạy nội bộ; cấu hình API bên ngoài đã được loại bỏ.')
    return support_knowledge.settings(data)
