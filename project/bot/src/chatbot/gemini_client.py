"""Gemini REST client with bounded retries and sanitized errors."""
import json
import logging
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, settings, opener=urlopen, sleep=time.sleep):
        self.settings = settings
        self._open = opener
        self._sleep = sleep

    @property
    def configured(self):
        return bool(self.settings.gemini_api_key and self.settings.gemini_model)

    def extract_query(self, prompt: str) -> dict:
        return self._generate(prompt)

    def generate_answer(self, prompt: str) -> dict:
        return self._generate(prompt)

    def _generate(self, prompt):
        if not self.configured or not re.fullmatch(r'[A-Za-z0-9._-]+', self.settings.gemini_model):
            raise GeminiError('Configure GEMINI_API_KEY and GEMINI_MODEL')
        body = json.dumps({
            'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.2,
                                 'maxOutputTokens': 4096},
        }).encode('utf-8')
        request = Request(
            f'https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent',
            data=body, headers={'Content-Type': 'application/json',
                                'x-goog-api-key': self.settings.gemini_api_key}, method='POST')
        for attempt in range(self.settings.max_retries + 1):
            try:
                with self._open(request, timeout=self.settings.timeout_seconds) as response:
                    raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise GeminiError('Gemini response exceeds size limit')
                return self._parse(json.loads(raw))
            except HTTPError as error:
                retryable = error.code in (408, 429, 500, 502, 503, 504)
                error.close()
                if not retryable or attempt == self.settings.max_retries:
                    raise GeminiError(f'Gemini HTTP status {error.code}') from None
            except (URLError, TimeoutError, ConnectionError):
                if attempt == self.settings.max_retries:
                    raise GeminiError('Gemini network request failed') from None
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                raise GeminiError('Gemini returned invalid content') from None
            logger.warning('Retrying transient Gemini failure, attempt %d', attempt + 1)
            self._sleep(min(2 ** attempt, 8))

    @staticmethod
    def _parse(payload):
        candidate = payload['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise GeminiError('Gemini response blocked or incomplete')
        text = ''.join(part.get('text', '') for part in candidate['content']['parts']
                       if not part.get('thought'))
        result = json.loads(text)
        if not isinstance(result, dict):
            raise GeminiError('Gemini response must be an object')
        return result
