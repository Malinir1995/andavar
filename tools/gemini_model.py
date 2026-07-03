import logging
from typing import AsyncGenerator

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import Client
from google.genai import types

from tools.memory_store import active_project_api_key, active_project_model
from config import settings

logger = logging.getLogger("andavar.tools.gemini_model")


class ProjectGemini(Gemini):
    """
    Subclass of Gemini that dynamically injects per-project API key
    and model name at request time using ContextVars.
    """
    # Cache clients to prevent aiohttp ClientSession connector AssertionErrors
    _client_cache = {}

    def _get_effective_model(self) -> str:
        """Return the project-scoped model name, or fall back to default."""
        pm = active_project_model.get()
        return pm if pm else self.model

    def _build_client(self, live: bool = False) -> Client:
        """Build or retrieve a genai Client for the current API key."""
        key = active_project_api_key.get() or settings.google_api_key or "default"
        cache_key = f"{key}_{live}"
        
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]
            
        base_url, api_version = self._base_url_and_api_version

        if live:
            http_opts = types.HttpOptions(
                headers=self._tracking_headers(),
                api_version=self._live_api_version,
                base_url=base_url,
            )
        else:
            http_kwargs = {
                'headers': self._tracking_headers(),
                'retry_options': self.retry_options,
                'base_url': base_url,
            }
            if api_version:
                http_kwargs['api_version'] = api_version
            http_opts = types.HttpOptions(**http_kwargs)

        kwargs = {'http_options': http_opts}

        effective_model = self._get_effective_model()
        if effective_model.startswith('projects/'):
            kwargs['enterprise'] = True

        actual_key = active_project_api_key.get()
        if actual_key:
            kwargs['api_key'] = actual_key

        client = Client(**kwargs)
        self._client_cache[cache_key] = client
        return client

    @property
    def api_client(self) -> Client:
        return self._build_client(live=False)

    @property
    def _live_api_client(self) -> Client:
        return self._build_client(live=True)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        """Override to swap the model name on the request before calling super."""
        effective = self._get_effective_model()
        if effective and effective != self.model:
            llm_request.model = effective
            logger.debug("ProjectGemini: using project model '%s'", effective)

        async for response in super().generate_content_async(llm_request, stream):
            yield response
