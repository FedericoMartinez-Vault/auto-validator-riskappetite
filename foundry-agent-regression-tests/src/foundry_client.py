"""Azure AI Foundry agent client for Instruction Compliance / Task Drift Resistance tests."""

from __future__ import annotations

import logging
import os
from typing import Callable

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

AGENT_NAME_CANDIDATES = [
    "AF-UW-RiskApetite",
    "AF-UW-RiskAppetite",
]

CORRECTED_AGENT_NAME = "AF-UW-RiskAppetite"
TYPO_AGENT_NAME = "AF-UW-RiskApetite"

PROJECT_NAME = "azr-dev-proj-af-1617"
MAX_RETRY_ATTEMPTS = 10

logger = logging.getLogger(__name__)
StepCallback = Callable[[str], None]
RetryCallback = Callable[[int, int, str, float], None]


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, HttpResponseError):
        return exc.status_code in {408, 409, 429, 500, 502, 503, 504}
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "rate limit",
            "too many requests",
            "timeout",
            "temporarily unavailable",
            "throttl",
            "connection reset",
            "service unavailable",
        )
    )


class FoundryAgentClient:
    """Connect to an existing Foundry agent and execute one prompt per conversation."""

    def __init__(self) -> None:
        self.project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        if not self.project_endpoint:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required in the environment.")

        for env_name in ("FOUNDRY_API_KEY", "AZURE_OPENAI_ENDPOINT"):
            if not os.getenv(env_name, "").strip():
                raise ValueError(f"{env_name} is required in the environment.")

        self.credential = DefaultAzureCredential()
        self.project_client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=self.credential,
        )
        self._openai_context = None
        self._openai_client = None
        self._on_step: StepCallback | None = None
        self._on_retry: RetryCallback | None = None
        self.agent_name, self.agent_id = self._resolve_agent()

    def set_callbacks(
        self,
        on_step: StepCallback | None = None,
        on_retry: RetryCallback | None = None,
    ) -> None:
        self._on_step = on_step
        self._on_retry = on_retry

    def _emit_step(self, step: str) -> None:
        logger.info("Agent step: %s", step)
        if self._on_step is not None:
            self._on_step(step)

    def _list_project_agents_by_name(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for agent in self.project_client.agents.list():
            if agent.name in AGENT_NAME_CANDIDATES:
                found[agent.name] = agent.id
        return found

    def _resolve_agent(self) -> tuple[str, str]:
        found = self._list_project_agents_by_name()
        if not found:
            raise ValueError(
                f"Could not find agent using names {AGENT_NAME_CANDIDATES} "
                f"in project {PROJECT_NAME}."
            )

        if CORRECTED_AGENT_NAME in found and TYPO_AGENT_NAME in found:
            print(
                "Found both agent names in the project: "
                f"{TYPO_AGENT_NAME} and {CORRECTED_AGENT_NAME}. "
                f"Using corrected name {CORRECTED_AGENT_NAME}."
            )
            return CORRECTED_AGENT_NAME, found[CORRECTED_AGENT_NAME]

        if CORRECTED_AGENT_NAME in found:
            return CORRECTED_AGENT_NAME, found[CORRECTED_AGENT_NAME]

        print(
            f"Warning: only typo agent name '{TYPO_AGENT_NAME}' was found. "
            f"Expected corrected name '{CORRECTED_AGENT_NAME}'."
        )
        return TYPO_AGENT_NAME, found[TYPO_AGENT_NAME]

    def _invoke_agent(self, prompt: str) -> str:
        if self._openai_client is None:
            raise RuntimeError("OpenAI client is not initialized.")

        self._emit_step("creating_conversation")
        conversation = self._openai_client.conversations.create(
            items=[{"type": "message", "role": "user", "content": prompt}],
        )
        try:
            self._emit_step("waiting_for_agent_response")
            response = self._openai_client.responses.create(
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": self.agent_name,
                        "type": "agent_reference",
                    }
                },
            )
            self._emit_step("agent_response_received")
            return response.output_text or ""
        finally:
            self._emit_step("cleaning_up_conversation")
            try:
                self._openai_client.conversations.delete(conversation_id=conversation.id)
            except Exception as exc:
                logger.warning("Failed to delete conversation %s: %s", conversation.id, exc)

    def _log_retry(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        wait_seconds = float(retry_state.next_action.sleep) if retry_state.next_action else 0.0
        attempt = retry_state.attempt_number
        error_text = str(exc) if exc else "unknown error"
        logger.warning(
            "Retry %s/%s | error=%s | waiting %.1fs",
            attempt,
            MAX_RETRY_ATTEMPTS,
            error_text,
            wait_seconds,
        )
        if self._on_retry is not None:
            self._on_retry(attempt, MAX_RETRY_ATTEMPTS, error_text, wait_seconds)

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        before_sleep=lambda retry_state: FoundryAgentClient._retry_logger(retry_state),
        reraise=True,
    )
    def run_prompt(self, prompt: str) -> str:
        """Create a new conversation, send the prompt, run the agent, and return the response."""
        output = self._invoke_agent(prompt)
        if not output.strip():
            raise RuntimeError("Agent returned an empty response.")
        return output

    @staticmethod
    def _retry_logger(retry_state: RetryCallState) -> None:
        instance = retry_state.args[0] if retry_state.args else None
        if isinstance(instance, FoundryAgentClient):
            instance._log_retry(retry_state)

    def close(self) -> None:
        if self._openai_context is not None:
            self._openai_context.__exit__(None, None, None)
            self._openai_context = None
            self._openai_client = None
        self.project_client.close()
        self.credential.close()

    def __enter__(self) -> "FoundryAgentClient":
        self._openai_context = self.project_client.get_openai_client()
        self._openai_client = self._openai_context.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
