"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- embed_nanobot extensions (append below this line) ---
class MeshConfig(Base):
    """LAN mesh channel configuration for device-to-device communication."""
    enabled: bool = False
    node_id: str = ""          # Unique node identifier (auto-generated from hostname if empty)
    tcp_port: int = 18800      # TCP port for mesh message transport
    udp_port: int = 18799      # UDP port for peer discovery beacons
    roles: list[str] = Field(default_factory=lambda: ["nanobot"])  # Node roles for discovery
    allow_from: list[str] = Field(default_factory=list)  # Allowed node IDs (empty = allow all)
    # --- embed_nanobot extensions: PSK authentication (task 1.9) ---
    psk_auth_enabled: bool = True       # Enable HMAC-PSK authentication for mesh messages
    key_store_path: str = ""            # Path to mesh_keys.json (default: <workspace>/mesh_keys.json)
    allow_unauthenticated: bool = False # If True, log warning but still process unsigned messages
    nonce_window: int = 60              # Seconds; reject messages with ts outside this window
    # --- embed_nanobot extensions: device enrollment (task 1.10) ---
    enrollment_pin_length: int = 6          # Number of digits in enrollment PIN
    enrollment_pin_timeout: int = 300       # Seconds before PIN expires (default 5 min)
    enrollment_max_attempts: int = 3        # Max failed PIN attempts before lockout
    # --- embed_nanobot extensions: payload encryption (task 1.11) ---
    encryption_enabled: bool = True         # Enable AES-256-GCM payload encryption
    # --- embed_nanobot extensions: device registry (task 2.1) ---
    registry_path: str = ""                  # Path to device_registry.json (default: <workspace>/device_registry.json)
    # --- embed_nanobot extensions: automation rules engine (task 2.6) ---
    automation_rules_path: str = ""          # Path to automation_rules.json (default: <workspace>/automation_rules.json)
    # --- embed_nanobot extensions: mTLS device authentication (task 3.1) ---
    mtls_enabled: bool = False               # Enable mTLS (mutual TLS) for transport-level auth+encryption
    ca_dir: str = ""                         # Path to CA directory (default: <workspace>/mesh_ca/)
    device_cert_validity_days: int = 365     # Validity period for device certificates (days)
    # --- embed_nanobot extensions: OTA firmware update (task 3.3) ---
    firmware_dir: str = ""                   # Directory for firmware images. Empty = OTA disabled.
    ota_chunk_size: int = 4096               # Bytes per OTA chunk (default 4KB, suitable for ESP32)
    ota_chunk_timeout: int = 30              # Seconds to wait for chunk ACK before retry
    # --- embed_nanobot extensions: device grouping and scenes (task 3.4) ---
    groups_path: str = ""                    # Path to device groups JSON. Empty = <workspace>/device_groups.json
    scenes_path: str = ""                    # Path to scenes JSON. Empty = <workspace>/device_scenes.json
    # --- embed_nanobot extensions: monitoring dashboard (task 3.6) ---
    dashboard_port: int = 0                  # HTTP port for mesh dashboard. 0 = disabled.
    # --- embed_nanobot extensions: PLC/industrial integration (task 4.1) ---
    industrial_config_path: str = ""         # Path to industrial_config.json. Empty = disabled.
    # --- embed_nanobot extensions: hub-to-hub federation (task 4.2) ---
    federation_config_path: str = ""         # Path to federation.json. Empty = disabled.
    # --- embed_nanobot extensions: sensor data pipeline (task 4.4) ---
    pipeline_enabled: bool = False           # Enable sensor time-series recording.
    pipeline_path: str = ""                  # JSON persistence path. Empty = <workspace>/sensor_data.json
    pipeline_max_points: int = 10000         # Max readings per (device, capability) buffer.
    pipeline_flush_interval: int = 60        # Seconds between auto-save to disk. 0 = manual.
    # --- embed_nanobot extensions: BLE sensor support (task 4.5) ---
    ble_config_path: str = ""                # Path to BLE config JSON. Empty = disabled.
    # --- embed_nanobot extensions: device codegen (task 4.3) ---
    codegen_templates_path: str = ""         # Path to custom code templates JSON. Empty = builtins only.
    # --- embed_nanobot extensions: autonomous mode (task 5.1.1) ---
    autonomous_enabled: bool = False         # Enable periodic autonomous device monitoring.
    autonomous_interval_s: int = 1800        # Seconds between autonomous scans (default 30min).
    autonomous_level: str = "monitor-only"   # off | monitor-only | suggest | act
    autonomous_topics: list[str] = Field(default_factory=list)  # User-defined exploration topics.
    autonomous_keep_messages: int = 8        # Recent session messages to retain between runs.
    # --- embed_nanobot extensions: MCP server (task 5.3.1) ---
    mcp_server_port: int = 0                 # Port for MCP SSE server. 0 = disabled.


class ChannelsConfig(Base):
    """Configuration for chat channels.

    Built-in and plugin channel configs are stored as extra fields (dicts).
    Each channel parses its own config in __init__.
    Per-channel "streaming": true enables streaming output (requires send_delta impl).
    """

    model_config = ConfigDict(extra="allow")

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    # --- embed_nanobot extensions (append below this line) ---
    mesh: MeshConfig = Field(default_factory=MeshConfig)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str = (
        "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    )
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    reasoning_effort: str | None = None  # low / medium / high - enables LLM thinking mode


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)  # Azure OpenAI (model = deployment name)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)  # Ollama local models
    ovms: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenVINO Model Server (OVMS)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    mistral: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动)
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine (火山引擎)
    volcengine_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine Coding Plan
    byteplus: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus (VolcEngine international)
    byteplus_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus Coding Plan
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)  # Github Copilot (OAuth)


class HeartbeatConfig(Base):
    """Heartbeat service configuration."""

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes
    keep_recent_messages: int = 8


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


# --- embed_nanobot extensions (append below this line) ---
class HybridRouterConfig(Base):
    """Hybrid routing configuration for dual-model (local + API) setup.

    The local model judges task difficulty and handles easy tasks.
    Difficult tasks are forwarded to the API model after PII sanitisation.
    """
    enabled: bool = False
    local_provider: str = ""       # Config key of the local provider (e.g. "ollama", "vllm")
    local_model: str = ""          # Model name served locally (e.g. "llama3")
    api_provider: str = ""         # Config key of the API provider (e.g. "anthropic", "openrouter")
    api_model: str = ""            # Model name on the API side (e.g. "anthropic/claude-sonnet-4-5")
    difficulty_threshold: float = 0.5  # 0–1; higher → more tasks stay local
    # --- embed_nanobot extensions: cloud fallback (task 2.7) ---
    fallback_to_local: bool = True            # Fall back to local model when API is unreachable
    circuit_breaker_threshold: int = 3        # Consecutive API failures before circuit opens
    circuit_breaker_timeout: int = 300        # Seconds to route all to local after circuit opens


class WebSearchConfig(Base):
    """Web search tool configuration."""

    provider: str = "brave"  # brave, tavily, duckduckgo, searxng, jina
    api_key: str = ""
    base_url: str = ""  # SearXNG base URL
    max_results: int = 5


class WebToolsConfig(Base):
    """Web tools configuration."""

    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    enable: bool = True
    timeout: int = 60
    path_append: str = ""

class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE: custom headers
    tool_timeout: int = 30  # seconds before a tool call is cancelled
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])  # Only register these tools; accepts raw MCP names or wrapped mcp_<server>_<tool> names; ["*"] = all tools; [] = no tools

class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    # --- embed_nanobot extensions (append below this line) ---
    hybrid_router: HybridRouterConfig = Field(default_factory=HybridRouterConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from nanobot.providers.registry import PROVIDERS, find_by_name

        forced = self.agents.defaults.provider
        if forced != "auto":
            spec = find_by_name(forced)
            if spec:
                p = getattr(self.providers, spec.name, None)
                return (p, spec.name) if p else (None, None)
            return None, None

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # Fallback: configured local providers can route models without
        # provider-specific keywords (for example plain "llama3.2" on Ollama).
        # Prefer providers whose detect_by_base_keyword matches the configured api_base
        # (e.g. Ollama's "11434" in "http://localhost:11434") over plain registry order.
        local_fallback: tuple[ProviderConfig, str] | None = None
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if not (p and p.api_base):
                continue
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in p.api_base:
                return p, spec.name
            if local_fallback is None:
                local_fallback = (p, spec.name)
        if local_fallback:
            return local_fallback

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for gateway/local providers."""
        from nanobot.providers.registry import find_by_name

        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default api_base here. Standard providers
        # resolve their base URL from the registry in the provider constructor.
        if name:
            spec = find_by_name(name)
            if spec and (spec.is_gateway or spec.is_local) and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = ConfigDict(env_prefix="NANOBOT_", env_nested_delimiter="__")
