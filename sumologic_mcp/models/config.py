"""Configuration models for Sumo Logic MCP server."""

from pydantic import BaseModel, Field, validator, HttpUrl
from typing import Optional, Dict, Any, List
import re


class SumoLogicConfig(BaseModel):
    """Configuration for Sumo Logic connection."""
    
    access_id: str = Field(..., description="Sumo Logic Access ID", min_length=1)
    access_key: str = Field(..., description="Sumo Logic Access Key", min_length=1)
    endpoint: str = Field(..., description="Sumo Logic API endpoint")
    timeout: int = Field(default=30, description="Request timeout in seconds", ge=1, le=300)
    max_retries: int = Field(default=3, description="Maximum retry attempts", ge=0, le=10)
    rate_limit_delay: float = Field(default=1.0, description="Delay between rate-limited requests", ge=0.1, le=60.0)
    
    @validator('endpoint')
    def validate_endpoint(cls, v):
        """Validate that endpoint is a proper Sumo Logic API URL."""
        if not v.startswith('https://'):
            raise ValueError('Endpoint must use HTTPS')
        if not re.match(r'https://api\.[a-z0-9-]+\.sumologic\.com', v):
            raise ValueError('Endpoint must be a valid Sumo Logic API URL')
        return v
    
    @validator('access_id')
    def validate_access_id(cls, v):
        """Validate access ID format."""
        if not re.match(r'^[A-Za-z0-9]{14}$', v):
            raise ValueError('Access ID must be 14 alphanumeric characters')
        return v
    
    @validator('access_key')
    def validate_access_key(cls, v):
        """Validate access key format."""
        if len(v) < 20:
            raise ValueError('Access key must be at least 20 characters long')
        return v


class SearchRequest(BaseModel):
    """Model for search request parameters."""
    
    query: str = Field(..., description="Search query string", min_length=1)
    from_time: str = Field(..., description="Start time (ISO format or relative)")
    to_time: str = Field(..., description="End time (ISO format or relative)")
    limit: int = Field(default=100, ge=1, le=10000, description="Maximum results to return")
    offset: int = Field(default=0, ge=0, description="Result offset for pagination")
    time_zone: Optional[str] = Field(default=None, description="Time zone for query (e.g., 'UTC', 'America/New_York')")
    by_receipt_time: bool = Field(default=False, description="Search by receipt time instead of message time")
    auto_parsing_mode: Optional[str] = Field(default=None, description="Auto parsing mode ('intelligent', 'performance')")
    
    @validator('query')
    def validate_query(cls, v):
        """Validate search query is not empty after stripping whitespace."""
        if not v.strip():
            raise ValueError('Search query cannot be empty')
        return v.strip()
    
    @validator('from_time', 'to_time')
    def validate_time_format(cls, v):
        """Validate time format (ISO 8601, relative time, or 'now')."""
        # Allow 'now' as a valid time format
        if v.lower() == 'now':
            return v
        
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
    
    @validator('auto_parsing_mode')
    def validate_auto_parsing_mode(cls, v):
        """Validate auto parsing mode."""
        if v is not None and v not in ['intelligent', 'performance']:
            raise ValueError('Auto parsing mode must be "intelligent" or "performance"')
        return v


class DashboardConfig(BaseModel):
    """Model for dashboard configuration."""
    
    title: str = Field(..., description="Dashboard title", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Dashboard description", max_length=1000)
    panels: List[Dict[str, Any]] = Field(..., description="Dashboard panels configuration", min_items=1)
    refresh_interval: Optional[int] = Field(None, description="Auto-refresh interval in seconds", ge=30, le=86400)
    folder_id: Optional[str] = Field(None, description="Folder ID to place dashboard in")
    theme: Optional[str] = Field(default="Light", description="Dashboard theme")
    topology_label_map: Optional[Dict[str, Any]] = Field(None, description="Topology label mapping")
    domain: Optional[str] = Field(None, description="Dashboard domain")
    
    @validator('title')
    def validate_title(cls, v):
        """Validate dashboard title."""
        if not v.strip():
            raise ValueError('Dashboard title cannot be empty')
        return v.strip()
    
    @validator('theme')
    def validate_theme(cls, v):
        """Validate dashboard theme."""
        if v is not None and v not in ['Light', 'Dark']:
            raise ValueError('Theme must be "Light" or "Dark"')
        return v
    
    @validator('panels')
    def validate_panels(cls, v):
        """Validate panels configuration."""
        if not v:
            raise ValueError('Dashboard must have at least one panel')
        
        for i, panel in enumerate(v):
            if not isinstance(panel, dict):
                raise ValueError(f'Panel {i} must be a dictionary')
            
            # Check required panel fields
            required_fields = ['title', 'visualSettings']
            for field in required_fields:
                if field not in panel:
                    raise ValueError(f'Panel {i} missing required field: {field}')
        
        return v


class MetricsRequest(BaseModel):
    """Model for metrics query request parameters."""
    
    query: str = Field(..., description="Metrics query string", min_length=1)
    from_time: str = Field(..., description="Start time (ISO format or relative)")
    to_time: str = Field(..., description="End time (ISO format or relative)")
    requested_data_points: Optional[int] = Field(default=600, ge=1, le=1440, description="Number of data points to return")
    max_tab_results: Optional[int] = Field(default=100, ge=1, le=1000, description="Maximum tabular results")
    
    @validator('query')
    def validate_metrics_query(cls, v):
        """Validate metrics query is not empty."""
        if not v.strip():
            raise ValueError('Metrics query cannot be empty')
        return v.strip()
    
    @validator('from_time', 'to_time')
    def validate_time_format(cls, v):
        """Validate time format (ISO 8601, relative time, or 'now')."""
        # Allow 'now' as a valid time format
        if v.lower() == 'now':
            return v
        
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


class CollectorConfig(BaseModel):
    """Model for collector configuration."""
    
    name: str = Field(..., description="Collector name", min_length=1, max_length=128)
    description: Optional[str] = Field(None, description="Collector description", max_length=1000)
    category: Optional[str] = Field(None, description="Collector category", max_length=1000)
    host_name: Optional[str] = Field(None, description="Host name for hosted collector")
    time_zone: Optional[str] = Field(default="UTC", description="Time zone for collector")
    ephemeral: bool = Field(default=True, description="Whether collector is ephemeral")
    source_sync_mode: Optional[str] = Field(default="UI", description="Source synchronization mode")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate collector name."""
        if not v.strip():
            raise ValueError('Collector name cannot be empty')
        # Check for invalid characters
        if re.search(r'[<>:"/\\|?*]', v):
            raise ValueError('Collector name contains invalid characters')
        return v.strip()
    
    @validator('source_sync_mode')
    def validate_source_sync_mode(cls, v):
        """Validate source sync mode."""
        if v is not None and v not in ['UI', 'JSON', 'Both']:
            raise ValueError('Source sync mode must be "UI", "JSON", or "Both"')
        return v


class SourceConfig(BaseModel):
    """Model for source configuration."""
    
    name: str = Field(..., description="Source name", min_length=1, max_length=128)
    description: Optional[str] = Field(None, description="Source description", max_length=1000)
    category: Optional[str] = Field(None, description="Source category", max_length=1000)
    host_name: Optional[str] = Field(None, description="Host name for source")
    time_zone: Optional[str] = Field(default="UTC", description="Time zone for source")
    automatic_date_parsing: bool = Field(default=True, description="Enable automatic date parsing")
    multiline_processing_enabled: bool = Field(default=True, description="Enable multiline processing")
    use_autoline_matching: bool = Field(default=True, description="Use automatic line matching")
    force_time_zone: bool = Field(default=False, description="Force time zone")
    default_date_format: Optional[str] = Field(None, description="Default date format")
    filters: Optional[List[Dict[str, Any]]] = Field(None, description="Processing filters")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate source name."""
        if not v.strip():
            raise ValueError('Source name cannot be empty')
        # Check for invalid characters
        if re.search(r'[<>:"/\\|?*]', v):
            raise ValueError('Source name contains invalid characters')
        return v.strip()