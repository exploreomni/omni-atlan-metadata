"""Configuration management for Omni-Atlan integration"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class OmniConfig(BaseSettings):
    """Omni API configuration"""
    base_url: str
    api_key: str
    
    model_config = SettingsConfigDict(
        env_prefix="OMNI_",
        case_sensitive=False,
        env_file=".env"
    )


class AtlanConfig(BaseSettings):
    """Atlan API configuration"""
    base_url: str
    api_key: str
    
    model_config = SettingsConfigDict(
        env_prefix="ATLAN_",
        case_sensitive=False,
        env_file=".env"
    )


class TemporalConfig(BaseSettings):
    """Temporal configuration"""
    host: str = "localhost:7233"
    namespace: str = "default"
    
    model_config = SettingsConfigDict(
        env_prefix="TEMPORAL_",
        case_sensitive=False,
        env_file=".env"
    )


def get_omni_config() -> OmniConfig:
    """Get Omni configuration"""
    return OmniConfig()


def get_atlan_config() -> AtlanConfig:
    """Get Atlan configuration"""
    return AtlanConfig()


def get_temporal_config() -> TemporalConfig:
    """Get Temporal configuration"""
    return TemporalConfig()

