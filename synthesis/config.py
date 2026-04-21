from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


# === Display Name Mapping ===
# UI-facing premium labels -> actual backend model IDs are resolved via config.
# These are purely cosmetic. Backend NEVER uses these for API calls.
MODEL_DISPLAY_NAMES = {
    # Flagship models (Expert tier research)
    "gpt-4o": {"display": "GPT-5.4 Thinking", "description": "Broad reasoning and structured problem solving"},
    "claude-sonnet-4-6": {"display": "Claude Sonnet 4.6", "description": "Strong synthesis and analytical reasoning"},
    "claude-opus-4-6": {"display": "Claude Opus 4.7", "description": "Deepest reasoning and premium written analysis"},
    # Workhorse models (Standard tier research)
    "gpt-4o-mini": {"display": "GPT-4.1 Turbo", "description": "Fast and cost-efficient reasoning"},
    "claude-haiku-4-5-20251001": {"display": "Claude Haiku 4.5", "description": "Quick analytical support"},
    # Shared across tiers
    "gemini-2.5-flash": {"display": "Gemini 3.1 Pro", "description": "Strong multimodal and long-context reasoning"},
    "gemini-2.0-flash": {"display": "Gemini 3.1 Pro", "description": "Fast and reliable model"},
    "gemini-1.5-flash": {"display": "Gemini 3.1 Pro", "description": "Stable and reliable model"},
    "deepseek-chat": {"display": "DeepSeek V3.2 Speciale", "description": "Cost-efficient analytical support"},
    "grok-3": {"display": "Grok 4.20 Heavy", "description": "Broad context and fast agentic analysis"},
}

# Role display names for UI
ROLE_DISPLAY_NAMES = {
    "prompt_engineer": "Prompt Engine",
    "strategist": "Strategist",
    "decision_maker": "Final Synthesized Output",
    "coding": "Coding",
}

# Progress messages shown during pipeline execution
PROGRESS_MESSAGES = [
    "Refining your prompt...",
    "Structuring the request...",
    "Distributing across AI models...",
    "Running parallel analysis...",
    "Cross-checking reasoning...",
    "Validating consistency...",
    "Filtering weak signals...",
    "Identifying consensus...",
    "Resolving contradictions...",
    "Synthesizing final answer...",
    "Finalizing response...",
]


class Settings(BaseSettings):
    # --- Admin Authentication ---
    admin_username: str = "admin"
    admin_password: str = ""  # MUST be set in .env
    admin_secret_key: str = "change-me-in-production"  # for session signing

    # --- API Keys (admin — primary) ---
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("openai_api_key", "gpt_api_key"),
    )
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key", "claude_api_key"),
    )
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("google_api_key", "gemini_api_key"),
    )
    deepseek_api_key: str = Field(default="")
    xai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("xai_api_key", "grok_api_key"),
    )

    # --- API Keys (user — future isolation, falls back to admin keys) ---
    openai_api_key_user: str = ""
    anthropic_api_key_user: str = ""
    google_api_key_user: str = ""
    deepseek_api_key_user: str = ""
    xai_api_key_user: str = ""

    # --- Provider Model IDs (actual API model names — NEVER shown in UI) ---
    openai_model_id: str = "gpt-4o"
    anthropic_model_id: str = "claude-sonnet-4-6"
    google_model_id: str = "gemini-2.5-flash"
    deepseek_model_id: str = "deepseek-chat"
    xai_model_id: str = "grok-3"

    # --- Role-Based Model Routing (Standard Mode / Tier 2) ---
    prompt_engineer_model: str = "gemini-2.5-flash"
    prompt_engineer_provider: str = "google"

    # --- Synthesis Layer (Strategist + Decision Maker) ---
    # Tier 2 (Standard): top-tier Claude for synthesis
    strategist_model: str = "claude-opus-4-6"
    strategist_provider: str = "anthropic"

    decision_maker_model: str = "claude-opus-4-6"
    decision_maker_provider: str = "anthropic"

    coding_model: str = "claude-sonnet-4-6"
    coding_provider: str = "anthropic"

    # --- Expert Mode Role Overrides (Tier 3 — strongest models) ---
    expert_prompt_engineer_model: str = "gpt-4o"
    expert_prompt_engineer_provider: str = "openai"

    expert_strategist_model: str = "claude-opus-4-6"
    expert_strategist_provider: str = "anthropic"

    expert_decision_maker_model: str = "claude-opus-4-6"
    expert_decision_maker_provider: str = "anthropic"

    # --- Hidden Cost-Efficient Overrides (Tier 1 — cheapest, silent) ---
    cheap_prompt_engineer_model: str = "deepseek-chat"
    cheap_prompt_engineer_provider: str = "deepseek"

    # Mid-tier for strategist/DM — cheap but not the weakest
    cheap_strategist_model: str = "gemini-2.5-flash"
    cheap_strategist_provider: str = "google"

    cheap_decision_maker_model: str = "gemini-2.5-flash"
    cheap_decision_maker_provider: str = "google"

    # --- Model Pools ---
    # Tier 1: ONLY 3 cheapest models for research
    cheap_research_models: list[str] = [
        "gemini-2.5-flash",
        "deepseek-chat",
        "grok-3",
    ]
    # Tier 2: 5 workhorse models (cheaper variants of GPT, strong Claude Sonnet)
    standard_research_models: list[str] = [
        "gpt-4o-mini",
        "claude-sonnet-4-6",
        "gemini-2.5-flash",
        "deepseek-chat",
        "grok-3",
    ]
    # Tier 3: 5 flagship models (strongest available)
    expert_research_models: list[str] = [
        "gpt-4o",
        "claude-sonnet-4-6",
        "gemini-2.5-flash",
        "deepseek-chat",
        "grok-3",
    ]
    # Legacy alias (defaults to standard workhorse pool)
    research_models: list[str] = [
        "gpt-4o-mini",
        "claude-sonnet-4-6",
        "gemini-2.5-flash",
        "deepseek-chat",
        "grok-3",
    ]
    # All models the system knows about (both workhorse and flagship)
    enabled_models: list[str] = [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-6",
        "gemini-2.5-flash",
        "deepseek-chat",
        "grok-3",
    ]

    # --- Mode System ---
    standard_mode_max_models: int = 5
    expert_mode_max_models: int = 5
    standard_mode_max_output_chars: int = 3000
    expert_mode_max_output_chars: int = 6000
    simple_prompt_char_threshold: int = 200

    # --- Cost Control ---
    standard_mode_token_budget: int = 50000
    expert_mode_token_budget: int = 120000
    max_cost_per_run_soft: float = 0.50
    max_cost_per_run_hard: float = 2.00

    # --- Margin Safety ---
    standard_mode_target_margin: float = 0.40
    expert_mode_target_margin: float = 0.25
    fallback_to_lower_tier: bool = True

    # --- Role-Specific Timeouts (seconds) ---
    prompt_engineer_timeout: int = 120
    research_timeout: int = 600
    strategist_timeout: int = 600
    decision_maker_timeout: int = 600
    coding_timeout: int = 900
    safety_timeout_seconds: int = 900
    max_retries: int = 2  # enough for 503 backoff retry

    # --- Size Limits ---
    max_prompt_chars: int = 8000
    max_model_output_chars: int = 4000
    max_phases: int = 5

    # --- Success Threshold ---
    min_successful_models: int = 3

    # --- Dev Mode ---
    dev_mode: bool = False
    debug_mode: bool = False  # hidden debug: shows all raw model outputs in UI
    test_mode: bool = False   # uses mock providers instead of real APIs

    # --- Logging ---
    log_mode: str = "minimal"

    # --- Circuit Breaker ---
    circuit_breaker_threshold: int = 3

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8080

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def effective_min_models(self) -> int:
        if self.dev_mode:
            return 1
        return self.min_successful_models

    def get_timeout_for_role(self, role: str) -> int:
        role_timeouts = {
            "prompt_engineer": self.prompt_engineer_timeout,
            "research": self.research_timeout,
            "strategist": self.strategist_timeout,
            "decision_maker": self.decision_maker_timeout,
            "coding": self.coding_timeout,
        }
        return role_timeouts.get(role, self.safety_timeout_seconds)

    def get_api_key(self, provider: str, is_admin: bool = True) -> str:
        """Get API key for a provider. Uses admin keys by default.
        If is_admin=False, tries user keys first, falls back to admin.
        """
        if not is_admin:
            user_map = {
                "openai": self.openai_api_key_user,
                "anthropic": self.anthropic_api_key_user,
                "google": self.google_api_key_user,
                "deepseek": self.deepseek_api_key_user,
                "xai": self.xai_api_key_user,
            }
            user_key = user_map.get(provider, "")
            if user_key:
                return user_key
        # Admin keys (or fallback)
        admin_map = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
            "deepseek": self.deepseek_api_key,
            "xai": self.xai_api_key,
        }
        return admin_map.get(provider, "")

    def get_model_id_for_provider(self, provider: str) -> str:
        id_map = {
            "openai": self.openai_model_id,
            "anthropic": self.anthropic_model_id,
            "google": self.google_model_id,
            "deepseek": self.deepseek_model_id,
            "xai": self.xai_model_id,
        }
        return id_map.get(provider, "")

    def _model_provider_map(self) -> dict[str, str]:
        return {
            self.openai_model_id: "openai",
            "gpt-4o-mini": "openai",
            self.anthropic_model_id: "anthropic",
            "claude-haiku-4-5-20251001": "anthropic",
            "claude-opus-4-6": "anthropic",
            self.google_model_id: "google",
            self.deepseek_model_id: "deepseek",
            self.xai_model_id: "xai",
        }

    def get_available_models(self) -> list[dict]:
        model_provider = self._model_provider_map()
        available = []
        for model in self.enabled_models:
            provider = model_provider.get(model)
            # In test_mode, skip API key check — all models are available via mock
            if provider and (self.test_mode or self.get_api_key(provider)):
                display = MODEL_DISPLAY_NAMES.get(model, {})
                available.append({
                    "model": model,
                    "provider": provider,
                    "display_name": display.get("display", model),
                    "description": display.get("description", ""),
                })
        return available

    def get_role_assignments(self, mode: str = "standard") -> dict:
        available_names = {m["model"] for m in self.get_available_models()}

        if mode == "expert":
            roles = {
                "prompt_engineer": {
                    "model": self.expert_prompt_engineer_model,
                    "provider": self.expert_prompt_engineer_provider,
                },
                "strategist": {
                    "model": self.expert_strategist_model,
                    "provider": self.expert_strategist_provider,
                },
                "decision_maker": {
                    "model": self.expert_decision_maker_model,
                    "provider": self.expert_decision_maker_provider,
                },
                "coding": {
                    "model": self.coding_model,
                    "provider": self.coding_provider,
                },
            }
        else:
            roles = {
                "prompt_engineer": {
                    "model": self.prompt_engineer_model,
                    "provider": self.prompt_engineer_provider,
                },
                "strategist": {
                    "model": self.strategist_model,
                    "provider": self.strategist_provider,
                },
                "decision_maker": {
                    "model": self.decision_maker_model,
                    "provider": self.decision_maker_provider,
                },
                "coding": {
                    "model": self.coding_model,
                    "provider": self.coding_provider,
                },
            }

        for role_key, role_info in roles.items():
            role_info["available"] = role_info["model"] in available_names
            role_info["display_name"] = ROLE_DISPLAY_NAMES.get(role_key, role_key)
            model_display = MODEL_DISPLAY_NAMES.get(role_info["model"], {})
            role_info["model_display"] = model_display.get("display", role_info["model"])
        return roles

    def get_mode_config(self, mode: str) -> dict:
        """Get mode-specific settings including research model pool."""
        if mode == "expert":
            return {
                "max_models": self.expert_mode_max_models,
                "max_output_chars": self.expert_mode_max_output_chars,
                "token_budget": self.expert_mode_token_budget,
                "target_margin": self.expert_mode_target_margin,
                "research_models": self.expert_research_models,
                "label": "Expert Analysis",
            }
        return {
            "max_models": self.standard_mode_max_models,
            "max_output_chars": self.standard_mode_max_output_chars,
            "token_budget": self.standard_mode_token_budget,
            "target_margin": self.standard_mode_target_margin,
            "research_models": self.standard_research_models,
            "label": "Standard",
        }

    def classify_prompt_complexity(self, prompt: str, category: str = "") -> str:
        """Classify prompt as simple/moderate/complex for internal cost routing.

        Used to silently downgrade system roles to cheapest models for simple prompts.
        Research always uses all 5 models regardless.
        """
        import re
        text = prompt.strip().lower()
        length = len(text)

        # Categories that are NEVER simple
        complex_categories = {
            "deep_research", "competitor_market_research", "comparison_evaluation",
        }
        if category in complex_categories:
            return "complex"

        # Keywords that indicate complexity
        complex_keywords = [
            r"\banalyze\b", r"\bcompare\b", r"\bstrateg", r"\bevaluate\b",
            r"\bcompetitor", r"\blandscape\b", r"\bmulti-phase\b",
            r"\bbreakdown\b", r"\bvalidat", r"\boptimiz", r"\bfunnel\b",
            r"\bpricing\b", r"\bacquisition\b", r"\bscaling\b",
            r"\btrade-off", r"\bpros.*cons\b", r"\brisk", r"\bROI\b",
        ]
        keyword_hits = sum(1 for p in complex_keywords if re.search(p, text))

        if keyword_hits >= 2 or length > 500:
            return "complex"
        if keyword_hits >= 1 or length > self.simple_prompt_char_threshold:
            return "moderate"
        return "simple"

    def get_effective_tier(self, mode: str, complexity: str) -> str:
        """Determine the actual routing tier based on mode + complexity.

        Returns: "expert", "standard", or "cost_efficient"
        Expert mode → always "expert" (never downgraded)
        Standard mode + simple prompt → "cost_efficient" (hidden)
        Standard mode + moderate/complex → "standard"
        """
        if mode == "expert":
            return "expert"
        if complexity == "simple":
            return "cost_efficient"
        return "standard"

    def get_role_model_for_tier(self, role: str, tier: str) -> tuple[str, str]:
        """Get (model_id, provider) for a role at a specific tier."""
        if tier == "cost_efficient":
            mapping = {
                "prompt_engineer": (self.cheap_prompt_engineer_model, self.cheap_prompt_engineer_provider),
                "strategist": (self.cheap_strategist_model, self.cheap_strategist_provider),
                "decision_maker": (self.cheap_decision_maker_model, self.cheap_decision_maker_provider),
                "coding": (self.coding_model, self.coding_provider),
            }
        elif tier == "expert":
            mapping = {
                "prompt_engineer": (self.expert_prompt_engineer_model, self.expert_prompt_engineer_provider),
                "strategist": (self.expert_strategist_model, self.expert_strategist_provider),
                "decision_maker": (self.expert_decision_maker_model, self.expert_decision_maker_provider),
                "coding": (self.coding_model, self.coding_provider),
            }
        else:
            mapping = {
                "prompt_engineer": (self.prompt_engineer_model, self.prompt_engineer_provider),
                "strategist": (self.strategist_model, self.strategist_provider),
                "decision_maker": (self.decision_maker_model, self.decision_maker_provider),
                "coding": (self.coding_model, self.coding_provider),
            }
        return mapping.get(role, (self.strategist_model, self.strategist_provider))

    def get_tier_research_models(self, tier: str) -> list[str]:
        """Get the research model pool for a specific tier.

        Tier 1 (cost_efficient): 3 cheapest models
        Tier 2 (standard): 5 workhorse models
        Tier 3 (expert): 5 strongest models
        """
        if tier == "cost_efficient":
            return self.cheap_research_models
        elif tier == "expert":
            return self.expert_research_models
        return self.standard_research_models


settings = Settings()
