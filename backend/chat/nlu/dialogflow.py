"""Optional Dialogflow ES adapter (AUBOT_INTENT_BACKEND=dialogflow).

Requires `pip install google-cloud-dialogflow`, GOOGLE_APPLICATION_CREDENTIALS
pointing at a service-account JSON, and an agent whose intent display names
match the keys in data/intents.yaml.
Dialogflow's own fallback intent maps to out_of_scope.
"""
import uuid

from .base import OUT_OF_SCOPE, IntentResult


class DialogflowEngine:
    name = "dialogflow"

    def __init__(self, project_id: str, language: str):
        if not project_id:
            raise RuntimeError("DIALOGFLOW_PROJECT_ID must be set to use the Dialogflow backend")
        try:
            from google.cloud import dialogflow  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install google-cloud-dialogflow to use the Dialogflow backend") from exc
        self._df = dialogflow
        self._client = dialogflow.SessionsClient()
        self.project_id = project_id
        self.language = language

    def classify(self, text: str) -> IntentResult:  # pragma: no cover - network call
        session = self._client.session_path(self.project_id, uuid.uuid4().hex)
        query_input = self._df.QueryInput(text=self._df.TextInput(text=text, language_code=self.language))
        result = self._client.detect_intent(request={"session": session, "query_input": query_input}).query_result
        intent = result.intent.display_name if not result.intent.is_fallback else OUT_OF_SCOPE
        return IntentResult(intent=intent or OUT_OF_SCOPE, confidence=float(result.intent_detection_confidence), engine=self.name)
