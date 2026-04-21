"""
IntellCluster — root configuration.
Manages server settings + API key detection for both tools.
"""

import os


class Settings:
    """Unified IntellCluster settings."""

    # Server
    host: str = "0.0.0.0"
    port: int = int(os.environ.get("PORT", "5000"))
    debug: bool = os.environ.get("DEBUG", "").lower() == "true"

    # Cost profile used by Phronesis: cheap | balanced | full
    cost_profile: str = os.environ.get("COST_PROFILE", "cheap")

    # Phronesis limits
    max_options: int = 10
    min_options: int = 2
    max_criteria: int = 10
    judge_timeout: int = 300

    @staticmethod
    def _get_key(*env_names) -> str | None:
        for name in env_names:
            val = os.environ.get(name)
            if val:
                return val
        return None

    @staticmethod
    def has_any_api_key() -> bool:
        """Check if at least one LLM API key is configured."""
        return bool(
            Settings._get_key("OPENAI_API_KEY", "GPT_API_KEY")
            or Settings._get_key("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
            or Settings._get_key("GOOGLE_API_KEY", "GEMINI_API_KEY")
        )

    @staticmethod
    def available_judges() -> list[str]:
        """List which LLM providers have API keys configured."""
        judges = []
        if Settings._get_key("OPENAI_API_KEY", "GPT_API_KEY"):
            judges.append("OpenAI (GPT-4o)")
        if Settings._get_key("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
            judges.append("Anthropic (Claude)")
        if Settings._get_key("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            judges.append("Google (Gemini)")
        if Settings._get_key("DEEPSEEK_API_KEY"):
            judges.append("DeepSeek")
        if Settings._get_key("XAI_API_KEY", "GROK_API_KEY"):
            judges.append("xAI (Grok)")
        return judges


settings = Settings()
