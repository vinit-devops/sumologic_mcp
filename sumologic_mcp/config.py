"""Configuration management for Sumo Logic MCP server."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator, ValidationError
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


class SumoLogicConfig(BaseModel):
    """Configuration for Sumo Logic MCP server."""
    
    # Sumo Logic API credentials (supports both new and reference environment variables)
    access_id: str = Field(
        ..., 
        description="Sumo Logic Access ID",
        env="SUMOLOGIC_ACCESS_ID"
    )
    access_key: str = Field(
        ..., 
        description="Sumo Logic Access Key",
        env="SUMOLOGIC_ACCESS_KEY"
    )
    endpoint: str = Field(
        ..., 
        description="Sumo Logic API endpoint",
        env="SUMOLOGIC_ENDPOINT"
    )
    
    # Server configuration
    timeout: int = Field(
        default=30, 
        description="Request timeout in seconds",
        env="SUMOLOGIC_TIMEOUT"
    )
    max_retries: int = Field(
        default=3, 
        description="Maximum retry attempts",
        env="SUMOLOGIC_MAX_RETRIES"
    )
    rate_limit_delay: float = Field(
        default=1.0, 
        description="Delay between rate-limited requests in seconds",
        env="SUMOLOGIC_RATE_LIMIT_DELAY"
    )
    
    # Logging configuration
    log_level: str = Field(
        default="INFO", 
        description="Logging level",
        env="SUMOLOGIC_LOG_LEVEL"
    )
    log_format: str = Field(
        default="json", 
        description="Log format (json or text)",
        env="SUMOLOGIC_LOG_FORMAT"
    )
    
    # MCP server configuration
    server_name: str = Field(
        default="sumologic-mcp-server", 
        description="MCP server name",
        env="SUMOLOGIC_SERVER_NAME"
    )
    server_version: str = Field(
        default="0.1.0", 
        description="MCP server version",
        env="SUMOLOGIC_SERVER_VERSION"
    )
    
    # Reference implementation compatibility
    query_timeout: int = Field(
        default=300,
        description="Query timeout for compatibility with reference implementation",
        env="QUERY_TIMEOUT"
    )
    max_results: int = Field(
        default=1000,
        description="Maximum results for compatibility with reference implementation",
        env="MAX_RESULTS"
    )
    default_vmware_source: str = Field(
        default="otel/vmware",
        description="Default VMware source category for metrics exploration",
        env="DEFAULT_VMWARE_SOURCE"
    )

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        
    @validator("endpoint")
    def validate_endpoint(cls, v: str) -> str:
        """Validate Sumo Logic endpoint URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Endpoint must be a valid HTTP/HTTPS URL")
        if not v.endswith(".sumologic.com"):
            raise ValueError("Endpoint must be a valid Sumo Logic domain")
        return v.rstrip("/")
    
    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v_upper
    
    @validator("log_format")
    def validate_log_format(cls, v: str) -> str:
        """Validate log format."""
        valid_formats = {"json", "text"}
        v_lower = v.lower()
        if v_lower not in valid_formats:
            raise ValueError(f"Log format must be one of: {', '.join(valid_formats)}")
        return v_lower
    
    @validator("timeout")
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout value."""
        if v <= 0:
            raise ValueError("Timeout must be greater than 0")
        if v > 300:  # 5 minutes max
            raise ValueError("Timeout must not exceed 300 seconds")
        return v
    
    @validator("max_retries")
    def validate_max_retries(cls, v: int) -> int:
        """Validate max retries value."""
        if v < 0:
            raise ValueError("Max retries must be non-negative")
        if v > 10:
            raise ValueError("Max retries should not exceed 10")
        return v
    
    @validator("rate_limit_delay")
    def validate_rate_limit_delay(cls, v: float) -> float:
        """Validate rate limit delay."""
        if v < 0:
            raise ValueError("Rate limit delay must be non-negative")
        if v > 60:  # 1 minute max
            raise ValueError("Rate limit delay should not exceed 60 seconds")
        return v
    
    @validator("query_timeout")
    def validate_query_timeout(cls, v: int) -> int:
        """Validate query timeout value."""
        if v <= 0:
            raise ValueError("Query timeout must be greater than 0")
        if v > 3600:  # 1 hour max
            raise ValueError("Query timeout must not exceed 3600 seconds (1 hour)")
        return v
    
    @validator("max_results")
    def validate_max_results(cls, v: int) -> int:
        """Validate max results value."""
        if v <= 0:
            raise ValueError("Max results must be greater than 0")
        if v > 100000:  # 100k max
            raise ValueError("Max results should not exceed 100,000")
        return v
    
    @validator("default_vmware_source")
    def validate_default_vmware_source(cls, v: str) -> str:
        """Validate default VMware source category."""
        if not v.strip():
            raise ValueError("Default VMware source cannot be empty")
        return v.strip()

    @classmethod
    def from_env(cls) -> "SumoLogicConfig":
        """Create configuration from environment variables.
        
        Supports both new environment variables and reference implementation variables
        for backward compatibility. Reference variables take precedence if both are set.
        """
        # Helper function to get environment variable with fallback
        def get_env_with_fallback(primary: str, fallback: str, default: str = "") -> str:
            return os.getenv(primary) or os.getenv(fallback) or default
        
        return cls(
            # Support both SUMOLOGIC_* and SUMO_* (reference) environment variables
            access_id=get_env_with_fallback("SUMOLOGIC_ACCESS_ID", "SUMO_ACCESS_ID"),
            access_key=get_env_with_fallback("SUMOLOGIC_ACCESS_KEY", "SUMO_ACCESS_KEY"),
            endpoint=get_env_with_fallback("SUMOLOGIC_ENDPOINT", "SUMO_ENDPOINT"),
            timeout=int(get_env_with_fallback("SUMOLOGIC_TIMEOUT", "TIMEOUT", "30")),
            max_retries=int(get_env_with_fallback("SUMOLOGIC_MAX_RETRIES", "MAX_RETRIES", "3")),
            rate_limit_delay=float(get_env_with_fallback("SUMOLOGIC_RATE_LIMIT_DELAY", "RATE_LIMIT_DELAY", "1.0")),
            log_level=get_env_with_fallback("SUMOLOGIC_LOG_LEVEL", "LOG_LEVEL", "INFO"),
            log_format=get_env_with_fallback("SUMOLOGIC_LOG_FORMAT", "LOG_FORMAT", "json"),
            server_name=get_env_with_fallback("SUMOLOGIC_SERVER_NAME", "SERVER_NAME", "sumologic-mcp-server"),
            server_version=get_env_with_fallback("SUMOLOGIC_SERVER_VERSION", "SERVER_VERSION", "0.1.0"),
            # Reference compatibility fields
            query_timeout=int(get_env_with_fallback("QUERY_TIMEOUT", "SUMOLOGIC_QUERY_TIMEOUT", "300")),
            max_results=int(get_env_with_fallback("MAX_RESULTS", "SUMOLOGIC_MAX_RESULTS", "1000")),
            default_vmware_source=get_env_with_fallback("DEFAULT_VMWARE_SOURCE", "SUMOLOGIC_DEFAULT_VMWARE_SOURCE", "otel/vmware"),
        )
    
    @classmethod
    def from_file(cls, config_path: Path) -> "SumoLogicConfig":
        """Create configuration from a JSON configuration file.
        
        Args:
            config_path: Path to the JSON configuration file
            
        Returns:
            SumoLogicConfig instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is not valid JSON
            ValidationError: If config values are invalid
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file {config_path}: {e}")
        
        return cls(**config_data)
    
    @classmethod
    def from_env_and_file(cls, config_path: Optional[Path] = None) -> "SumoLogicConfig":
        """Create configuration from environment variables and optional config file.
        
        Environment variables take precedence over config file values.
        
        Args:
            config_path: Optional path to JSON configuration file
            
        Returns:
            SumoLogicConfig instance
            
        Raises:
            ValueError: If configuration file is invalid or environment variables have invalid values
            FileNotFoundError: If specified config file doesn't exist
        """
        # Start with defaults
        config_data = {
            "access_id": "",
            "access_key": "",
            "endpoint": "",
            "timeout": 30,
            "max_retries": 3,
            "rate_limit_delay": 1.0,
            "log_level": "INFO",
            "log_format": "json",
            "server_name": "sumologic-mcp-server",
            "server_version": "0.1.0",
            "query_timeout": 300,
            "max_results": 1000,
            "default_vmware_source": "otel/vmware",
        }
        
        config_sources = {
            "file_loaded": False,
            "file_path": None,
            "env_vars_found": [],
            "parsing_errors": []
        }
        
        # Load from config file if provided
        if config_path:
            if not config_path.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                
                # Validate that file_config is a dictionary
                if not isinstance(file_config, dict):
                    raise ValueError(f"Configuration file must contain a JSON object, got {type(file_config).__name__}")
                
                config_data.update(file_config)
                config_sources["file_loaded"] = True
                config_sources["file_path"] = str(config_path)
                
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in configuration file {config_path}: {e}")
            except IOError as e:
                raise ValueError(f"Error reading configuration file {config_path}: {e}")
        
        # Override with environment variables with proper type conversion and validation
        # Support both new and reference environment variables
        env_mappings = {
            # Primary environment variables
            "SUMOLOGIC_ACCESS_ID": ("access_id", str),
            "SUMOLOGIC_ACCESS_KEY": ("access_key", str),
            "SUMOLOGIC_ENDPOINT": ("endpoint", str),
            "SUMOLOGIC_TIMEOUT": ("timeout", int),
            "SUMOLOGIC_MAX_RETRIES": ("max_retries", int),
            "SUMOLOGIC_RATE_LIMIT_DELAY": ("rate_limit_delay", float),
            "SUMOLOGIC_LOG_LEVEL": ("log_level", str),
            "SUMOLOGIC_LOG_FORMAT": ("log_format", str),
            "SUMOLOGIC_SERVER_NAME": ("server_name", str),
            "SUMOLOGIC_SERVER_VERSION": ("server_version", str),
            "SUMOLOGIC_QUERY_TIMEOUT": ("query_timeout", int),
            "SUMOLOGIC_MAX_RESULTS": ("max_results", int),
            "SUMOLOGIC_DEFAULT_VMWARE_SOURCE": ("default_vmware_source", str),
            
            # Reference implementation compatibility variables (take precedence)
            "SUMO_ACCESS_ID": ("access_id", str),
            "SUMO_ACCESS_KEY": ("access_key", str),
            "SUMO_ENDPOINT": ("endpoint", str),
            "QUERY_TIMEOUT": ("query_timeout", int),
            "MAX_RESULTS": ("max_results", int),
            "DEFAULT_VMWARE_SOURCE": ("default_vmware_source", str),
        }
        
        for env_var, (config_key, value_type) in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                try:
                    if value_type == str:
                        config_data[config_key] = env_value.strip()
                    elif value_type == int:
                        config_data[config_key] = int(env_value)
                    elif value_type == float:
                        config_data[config_key] = float(env_value)
                    
                    config_sources["env_vars_found"].append(env_var)
                    
                except (ValueError, TypeError) as e:
                    error_msg = f"Invalid value for {env_var}: '{env_value}' (expected {value_type.__name__})"
                    config_sources["parsing_errors"].append(error_msg)
                    raise ValueError(error_msg) from e
        
        # Store configuration source information for debugging
        config_instance = cls(**config_data)
        config_instance._config_sources = config_sources
        
        return config_instance
    
    def validate_required_fields(self) -> Dict[str, str]:
        """Validate that all required fields are present and valid.
        
        Returns:
            Dictionary of validation errors (empty if valid)
        """
        errors = {}
        
        if not self.access_id:
            errors["access_id"] = "Sumo Logic Access ID is required. Set SUMOLOGIC_ACCESS_ID environment variable or provide in config file."
        
        if not self.access_key:
            errors["access_key"] = "Sumo Logic Access Key is required. Set SUMOLOGIC_ACCESS_KEY environment variable or provide in config file."
        
        if not self.endpoint:
            errors["endpoint"] = "Sumo Logic API endpoint is required. Set SUMOLOGIC_ENDPOINT environment variable or provide in config file."
        
        return errors
    
    def validate_startup_configuration(self) -> Dict[str, Any]:
        """Comprehensive startup configuration validation with detailed error messages.
        
        Returns:
            Dictionary with validation results including errors, warnings, and recommendations
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "recommendations": [],
            "config_sources": {
                "environment_variables": {},
                "config_file": None,
                "defaults_used": []
            }
        }
        
        # Check required fields
        required_errors = self.validate_required_fields()
        if required_errors:
            validation_result["valid"] = False
            for field, message in required_errors.items():
                validation_result["errors"].append({
                    "field": field,
                    "message": message,
                    "severity": "error",
                    "category": "required_field"
                })
        
        # Check configuration values and provide warnings/recommendations
        if self.timeout < 10:
            validation_result["warnings"].append({
                "field": "timeout",
                "message": f"Timeout of {self.timeout}s is quite low and may cause request failures",
                "recommendation": "Consider using a timeout of at least 10 seconds",
                "current_value": self.timeout
            })
        elif self.timeout > 120:
            validation_result["warnings"].append({
                "field": "timeout", 
                "message": f"Timeout of {self.timeout}s is very high",
                "recommendation": "Consider using a timeout between 30-120 seconds for better performance",
                "current_value": self.timeout
            })
        
        if self.max_retries > 5:
            validation_result["warnings"].append({
                "field": "max_retries",
                "message": f"Max retries of {self.max_retries} is quite high",
                "recommendation": "Consider using 3-5 retries to balance reliability and performance",
                "current_value": self.max_retries
            })
        
        if self.rate_limit_delay < 0.5:
            validation_result["warnings"].append({
                "field": "rate_limit_delay",
                "message": f"Rate limit delay of {self.rate_limit_delay}s is very low",
                "recommendation": "Consider using at least 0.5s to avoid hitting rate limits",
                "current_value": self.rate_limit_delay
            })
        
        # Check endpoint configuration
        if self.endpoint and not self.endpoint.startswith("https://api."):
            validation_result["warnings"].append({
                "field": "endpoint",
                "message": "Endpoint should typically start with 'https://api.' for Sumo Logic",
                "recommendation": "Verify your endpoint URL is correct",
                "current_value": self.endpoint
            })
        
        # Add recommendations for optimal configuration
        if self.log_level == "DEBUG":
            validation_result["recommendations"].append({
                "field": "log_level",
                "message": "DEBUG logging is enabled",
                "recommendation": "Use INFO or WARNING level in production for better performance"
            })
        
        # Track which values are using defaults
        defaults_used = []
        if self.timeout == 30:
            defaults_used.append("timeout")
        if self.max_retries == 3:
            defaults_used.append("max_retries")
        if self.rate_limit_delay == 1.0:
            defaults_used.append("rate_limit_delay")
        if self.log_level == "INFO":
            defaults_used.append("log_level")
        if self.log_format == "json":
            defaults_used.append("log_format")
        
        validation_result["config_sources"]["defaults_used"] = defaults_used
        
        return validation_result
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get a summary of configuration validation status.
        
        Returns:
            Dictionary with validation details
        """
        errors = self.validate_required_fields()
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": [],
            "config": {
                "access_id_set": bool(self.access_id),
                "access_key_set": bool(self.access_key),
                "endpoint": self.endpoint,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "rate_limit_delay": self.rate_limit_delay,
                "log_level": self.log_level,
                "log_format": self.log_format,
                "server_name": self.server_name,
                "server_version": self.server_version,
            }
        }


class SearchRequest(BaseModel):
    """Model for search request parameters."""
    
    query: str = Field(..., description="Search query string")
    from_time: str = Field(..., description="Start time (ISO format or relative)")
    to_time: str = Field(..., description="End time (ISO format or relative)")
    limit: int = Field(
        default=100, 
        ge=1, 
        le=10000, 
        description="Maximum results to return"
    )
    offset: int = Field(
        default=0, 
        ge=0, 
        description="Result offset for pagination"
    )
    time_zone: Optional[str] = Field(None, description="Time zone for query")
    by_receipt_time: bool = Field(default=False, description="Search by receipt time")
    auto_parsing_mode: Optional[str] = Field(None, description="Auto parsing mode")
    
    @validator("query")
    def validate_query(cls, v: str) -> str:
        """Validate search query."""
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()
    
    @validator("from_time", "to_time")
    def validate_time_format(cls, v: str) -> str:
        """Validate time format (ISO 8601, relative time, or 'now')."""
        if not v.strip():
            raise ValueError("Time cannot be empty")
        
        v = v.strip()
        
        # Allow 'now' as a valid time format
        if v.lower() == 'now':
            return v
        
        import re
        
        # Enhanced ISO 8601 patterns to match Sumo Logic API requirements
        iso_patterns = [
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$',  # With milliseconds and Z
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?Z$',  # With microseconds and Z
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?[+-]\d{2}:\d{2}$',  # With timezone offset
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$',  # Basic ISO format
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?$'  # With optional milliseconds
        ]
        
        # Enhanced relative time pattern to match TimeParser implementation
        relative_pattern = r'^-?(\d+)([smhdw])$'
        
        # Check epoch time patterns (seconds or milliseconds)
        epoch_pattern = r'^\d{10,13}$'  # 10-13 digits for epoch seconds/milliseconds
        
        # Validate against all supported patterns
        is_iso = any(re.match(pattern, v, re.IGNORECASE) for pattern in iso_patterns)
        is_relative = re.match(relative_pattern, v, re.IGNORECASE)
        is_epoch = re.match(epoch_pattern, v)
        
        if not (is_iso or is_relative or is_epoch):
            raise ValueError(
                f"Invalid time format '{v}'. Supported formats:\n"
                "- 'now' for current time\n"
                "- Relative time: '-1h', '-30m', '-24h', '-7d', '-1w'\n"
                "- ISO 8601: '2023-12-01T10:00:00Z', '2023-12-01T10:00:00.123Z'\n"
                "- Epoch time: '1701428400' (seconds) or '1701428400000' (milliseconds)"
            )
        return v


class DashboardConfig(BaseModel):
    """Model for dashboard configuration."""
    
    title: str = Field(..., description="Dashboard title")
    description: Optional[str] = Field(None, description="Dashboard description")
    panels: list = Field(..., description="Dashboard panels configuration")
    refresh_interval: Optional[int] = Field(
        None, 
        ge=30, 
        description="Auto-refresh interval in seconds (minimum 30)"
    )
    
    @validator("title")
    def validate_title(cls, v: str) -> str:
        """Validate dashboard title."""
        if not v.strip():
            raise ValueError("Title cannot be empty")
        if len(v.strip()) > 255:
            raise ValueError("Title cannot exceed 255 characters")
        return v.strip()
    
    @validator("panels")
    def validate_panels(cls, v: list) -> list:
        """Validate panels configuration."""
        if not v:
            raise ValueError("Dashboard must have at least one panel")
        return v