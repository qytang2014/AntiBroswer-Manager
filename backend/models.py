"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .runtime import HostOS, RuntimeMode, ViewerMode


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    fingerprint_seed: int | None = None
    proxy: str | None = None
    timezone: str | None = None
    locale: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_family: Literal["auto", "nvidia", "intel"] = "auto"
    humanize: bool = False
    human_preset: Literal["default", "careful"] = "default"
    geoip: bool = True
    clipboard_sync: bool = True
    auto_launch: bool = False
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    launch_args: list[str] = Field(default_factory=list)
    extension_paths: list[str] = Field(default_factory=list)
    allow_3p_cookies: bool = True
    set_google_default: bool = True
    search_engine_name: str | None = None
    search_engine_keyword: str | None = None
    search_engine_url: str | None = None
    capture_preview: bool = True
    restore_session: bool = True
    browser_version: str | None = None
    notes: str | None = None
    tags: list[TagCreate] | None = None


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    fingerprint_seed: int | None = None
    proxy: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    locale: str | None = Field(default=None)
    screen_width: int | None = None
    screen_height: int | None = None
    gpu_family: Literal["auto", "nvidia", "intel"] | None = None
    humanize: bool | None = None
    human_preset: Literal["default", "careful"] | None = None
    geoip: bool | None = None
    clipboard_sync: bool | None = None
    auto_launch: bool | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = Field(default=None)
    launch_args: list[str] | None = None
    extension_paths: list[str] | None = None
    allow_3p_cookies: bool | None = None
    set_google_default: bool | None = None
    search_engine_name: str | None = None
    search_engine_keyword: str | None = None
    search_engine_url: str | None = None
    capture_preview: bool | None = None
    restore_session: bool | None = None
    browser_version: str | None = Field(default=None)
    notes: str | None = Field(default=None)
    tags: list[TagCreate] | None = None

    @field_validator("gpu_family", mode="before")
    @classmethod
    def reject_null_gpu_family(cls, value: object) -> object:
        if value is None:
            raise ValueError("gpu_family cannot be null")
        return value


class ProfileDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Also copy the source's user_data_dir (cookies, logged-in sessions, history,
    # local storage) so the clone launches as the same identity AND the same
    # session. Off by default: the clone starts with fresh, empty browser state.
    include_browser_state: bool = False


class TagCreate(BaseModel):
    tag: str
    color: str | None = None


class TagResponse(BaseModel):
    tag: str
    color: str | None = None


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class ProfileResponse(BaseModel):
    id: str
    name: str
    fingerprint_seed: int
    proxy: str | None = None
    timezone: str | None = None
    locale: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_family: Literal["auto", "nvidia", "intel"] = "auto"
    humanize: bool = False
    human_preset: str = "default"
    geoip: bool = True
    clipboard_sync: bool = True
    auto_launch: bool = False

    @field_validator("clipboard_sync", mode="before")
    @classmethod
    def coerce_clipboard_sync(cls, v: object) -> bool:
        return True if v is None else bool(v)

    color_scheme: str | None = None
    launch_args: list[str] = Field(default_factory=list)
    extension_paths: list[str] = Field(default_factory=list)
    allow_3p_cookies: bool = True
    set_google_default: bool = True
    search_engine_name: str | None = None
    search_engine_keyword: str | None = None
    search_engine_url: str | None = None
    capture_preview: bool = True
    restore_session: bool = True
    browser_version: str | None = None
    notes: str | None = None
    user_data_dir: str
    created_at: str
    updated_at: str
    sort_order: int = 0
    tags: list[TagResponse] = Field(default_factory=list)
    status: str = "stopped"
    runtime_mode: RuntimeMode = "docker"
    viewer_mode: ViewerMode = "vnc"
    vnc_ws_port: int | None = None
    cdp_url: str | None = None
    # Set when the profile's last launch closed on a license denial (out of
    # seats / bad key). {message, reason, upgrade_url?}. Cleared on next launch.
    last_error: dict[str, str] | None = None


class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    binary_installed: bool = True
    license_tier: str = "keyless"
    profiles_total: int
    host_os: HostOS
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    windows_fonts_present: int | None = None
    windows_fonts_required: int | None = None
    windows_fonts_complete: bool | None = None


class UpdateCheckResponse(BaseModel):
    current: str
    latest: str | None = None
    update_available: bool = False
    release_url: str | None = None


class SettingsResponse(BaseModel):
    license_key_set: bool
    license_key_masked: str | None = None
    release_channel: str = "stable"


class SettingsUpdate(BaseModel):
    # None = leave unchanged; "" = clear the license key (back to keyless).
    license_key: str | None = None
    release_channel: str | None = None


class ProfileStatusResponse(BaseModel):
    status: str
    runtime_mode: RuntimeMode
    viewer_mode: ViewerMode
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class ClipboardRequest(BaseModel):
    text: str = Field(max_length=1_048_576)


class ProxyTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proxy: str | None = None
    proxy_type: str | None = None


class ProxyTestResponse(BaseModel):
    ok: bool
    ip: str | None = None
    country: str | None = None
    city: str | None = None
    timezone: str | None = None
    locale: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    cached: bool = False


class LoginRequest(BaseModel):
    token: str


class WebStoreInstallRequest(BaseModel):
    id_or_url: str


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    update_interval_hours: int = Field(default=0, ge=0)


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    update_interval_hours: int | None = Field(default=None, ge=0)


class SubscriptionResponse(BaseModel):
    id: str
    name: str
    url: str
    update_interval_hours: int
    last_updated_at: str | None = None
    node_count: int = 0
    created_at: str
    updated_at: str


class ProxyNodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    protocol: str
    raw_uri: str
    subscription_id: str | None = None


class ProxyNodeBatchCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1_048_576)
    subscription_id: str | None = None


class ProxyNodeResponse(BaseModel):
    id: str
    subscription_id: str | None = None
    name: str
    protocol: str
    raw_uri: str
    last_latency_ms: int | None = None
    last_tested_at: str | None = None
    created_at: str
    updated_at: str


class BatchTestRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list)
    subscription_id: str | None = None
    manual_only: bool = False


class BatchTestResult(BaseModel):
    node_id: str
    latency_ms: int | None = None
    ok: bool
    error: str | None = None


class KernelItem(BaseModel):
    version: str
    name: str
    tier: str  # "pro" | "free"
    platform: str
    description: str
    installed: bool
    is_active: bool = False
    binary_path: str | None = None
    size_mb: float | None = None


class KernelListResponse(BaseModel):
    current_platform: str
    current_tier: str
    active_version: str | None = None
    installed: bool = False
    kernels: list[KernelItem]


class KernelDownloadTask(BaseModel):
    version: str
    tier: str = "free"
    stage: str
    message: str = ""
    percent: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_mb: float | None = None
    binary_path: str | None = None


class KernelDownloadStatusResponse(BaseModel):
    active: bool = False
    task: KernelDownloadTask | None = None


