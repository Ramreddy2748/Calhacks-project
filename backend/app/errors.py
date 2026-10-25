"""Safe provider diagnostics that can cross agent messages without leaking keys."""
import httpx

MESSAGES = {
    'claude_output_limit': 'Claude reached its response limit before finishing. Try a shorter scenario; your transcript is saved.',
    'claude_refusal': 'Claude declined to generate this scenario. Your transcript is saved; no generated result was accepted.',
    'claude_invalid_response': 'Claude returned an invalid response. Your transcript is saved; please try again.',
    'claude_timeout': 'Claude took too long to respond. Your transcript is saved; please try again shortly.',
    'claude_auth': 'Claude rejected the API credentials. Check ANTHROPIC_API_KEY in the hosting environment.',
    'claude_model': 'The configured Claude model was not found or is unavailable to this API key. Check ANTHROPIC_MODEL.',
    'claude_rate_limit': 'Claude is temporarily rate-limited. Wait a moment before starting another simulation.',
    'claude_unavailable': 'Claude is temporarily unavailable. Your transcript is saved; please try again shortly.',
}


class AgentError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'claude_invalid_response'
        super().__init__(MESSAGES[self.code])


def error_code(error):
    if isinstance(error, AgentError):
        return error.code
    if isinstance(error, httpx.TimeoutException):
        try:
            if error.request.url.host == 'api.anthropic.com':
                return 'claude_timeout'
        except RuntimeError:
            pass
    if isinstance(error, httpx.HTTPStatusError) and error.request.url.host == 'api.anthropic.com':
        return {401: 'claude_auth', 403: 'claude_auth', 404: 'claude_model',
                429: 'claude_rate_limit', 500: 'claude_unavailable', 503: 'claude_unavailable',
                529: 'claude_unavailable'}.get(error.response.status_code, '')
    return ''


def error_message(error):
    return MESSAGES.get(error_code(error),
        'A provider or agent request failed. Check configuration and provider availability before retrying.')
