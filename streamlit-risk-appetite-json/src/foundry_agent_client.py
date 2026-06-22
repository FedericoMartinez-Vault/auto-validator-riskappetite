"""Azure AI Foundry agent client for the Streamlit Metal JSON intake app."""

from __future__ import annotations

import logging
import os
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import (
    ClientSecretCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from dotenv import load_dotenv

from src.utils import extract_json_object

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_AGENT_CANDIDATES = [
    "AF-UW-RiskApetite",
    "AF-UW-RiskAppetite",
]


class FoundryAgentClient:
    """Connect to an existing Foundry agent and execute prompts via conversations API."""

    def __init__(self) -> None:
        self.project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        if not self.project_endpoint:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required. Set it in your .env file.")

        self.candidate_names = self._resolve_candidate_names()
        self.credential = self._build_credential()
        self.project_client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=self.credential,
        )
        self._openai_context = None
        self._openai_client = None
        self.agent_name: str | None = None
        self.agent_id: str | None = None

    @staticmethod
    def _resolve_candidate_names() -> list[str]:
        configured = os.getenv("FOUNDRY_AGENT_NAME", "").strip()
        if configured:
            extras = [name for name in DEFAULT_AGENT_CANDIDATES if name != configured]
            return [configured, *extras]
        return list(DEFAULT_AGENT_CANDIDATES)

    @staticmethod
    def _build_credential():
        """Prefer service principal on servers; fall back to managed identity or az login."""
        tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
        client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
        client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip()

        if tenant_id and client_id and client_secret:
            return ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

        use_managed = os.getenv("USE_MANAGED_IDENTITY", "").strip().lower() in {"1", "true", "yes"}
        if use_managed:
            return ManagedIdentityCredential(client_id=client_id or None)

        use_cli = os.getenv("USE_AZURE_CLI_AUTH", "true").strip().lower() in {"1", "true", "yes"}
        if use_cli:
            return DefaultAzureCredential(
                exclude_interactive_browser_credential=True,
                exclude_visual_studio_code_credential=True,
            )

        raise ValueError(
            "No Azure credentials configured. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and "
            "AZURE_CLIENT_SECRET, or USE_MANAGED_IDENTITY=true, or USE_AZURE_CLI_AUTH=true."
        )

    def find_agent(self, candidate_names: list[str] | None = None) -> dict[str, str]:
        """List existing agents and return the first match by name."""
        names = candidate_names or self.candidate_names
        agents_by_name: dict[str, str] = {}
        for agent in self.project_client.agents.list():
            if agent.name in names:
                agents_by_name[agent.name] = agent.id

        for name in names:
            if name in agents_by_name:
                self.agent_name = name
                self.agent_id = agents_by_name[name]
                return {"name": name, "id": agents_by_name[name]}

        available = sorted({agent.name for agent in self.project_client.agents.list()})
        raise ValueError(
            "Could not find a Risk Appetite agent. "
            f"Tried: {names}. Available agents: {available}"
        )

    def _ensure_agent(self) -> None:
        if not self.agent_name or not self.agent_id:
            self.find_agent()

    def _ensure_openai_client(self) -> None:
        if self._openai_client is None:
            self._openai_context = self.project_client.get_openai_client()
            self._openai_client = self._openai_context.__enter__()

    def run_agent(self, prompt: str) -> dict[str, Any]:
        """Create a conversation, run the agent, and parse the response."""
        self._ensure_agent()
        self._ensure_openai_client()

        status = "completed"
        raw_text = ""
        try:
            conversation = self._openai_client.conversations.create(
                items=[{"type": "message", "role": "user", "content": prompt}],
            )
            try:
                response = self._openai_client.responses.create(
                    conversation=conversation.id,
                    extra_body={
                        "agent_reference": {
                            "name": self.agent_name,
                            "type": "agent_reference",
                        }
                    },
                )
                raw_text = response.output_text or ""
            finally:
                try:
                    self._openai_client.conversations.delete(conversation_id=conversation.id)
                except Exception as exc:
                    logger.warning("Failed to delete conversation: %s", type(exc).__name__)
        except Exception as exc:
            status = "error"
            raw_text = str(exc)
            logger.error("Agent run failed: %s", type(exc).__name__)

        parsed_json, parse_status = extract_json_object(raw_text)
        return {
            "raw_text": raw_text,
            "parsed_json": parsed_json,
            "parse_status": parse_status,
            "status": status,
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
        }

    def close(self) -> None:
        if self._openai_context is not None:
            self._openai_context.__exit__(None, None, None)
            self._openai_context = None
            self._openai_client = None
        self.project_client.close()
        if hasattr(self.credential, "close"):
            self.credential.close()

    def __enter__(self) -> "FoundryAgentClient":
        self._ensure_openai_client()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
