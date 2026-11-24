"""Local-only support inference: no API credentials, HTTP client or remote fallback."""
import support_config
import support_knowledge


class AIError(Exception):
    def __init__(self, message, status=503, code='local_ai_error'):
        super().__init__(message)
        self.status = status
        self.code = code


def available():
    return support_config.load()['configured']


def generate_reply(history, text):
    try:
        return support_knowledge.answer(text, history)['answer']
    except support_knowledge.KnowledgeError as error:
        raise AIError(str(error)) from None
