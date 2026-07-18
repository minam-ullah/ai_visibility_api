from app.services.llm_client import LLMClient, LLMResult


class BaseAgent:
    """Shared plumbing for all agents: a lazily-created LLM client and a
    single entry point (`ask`) so subclasses only need to supply prompts and
    validate the shape of what comes back. Deliberately holds no per-run
    state, so each agent can be unit-tested in isolation with a mocked
    LLMClient and reused safely across pipeline runs.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self._llm_client = llm_client

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def ask(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        return self.llm.complete_json(system=system, user=user, max_tokens=max_tokens)
