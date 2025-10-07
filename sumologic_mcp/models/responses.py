"""Response models for Sumo Logic API data."""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


class SearchJobState(str, Enum):
    """Enumeration of search job states."""
    NOT_STARTED = "NOT STARTED"
    GATHERING_RESULTS = "GATHERING RESULTS"
    DONE_GATHERING_RESULTS = "DONE GATHERING RESULTS"
    CANCELLED = "CANCELLED"
    FORCE_PAUSED = "FORCE PAUSED"


class SearchResult(BaseModel):
    """Model for search result data."""
    
    job_id: str = Field(..., description="Unique identifier for the search job")
    status: SearchJobState = Field(..., description="Current status of the search job")
    message_count: int = Field(..., description="Number of log messages found", ge=0)
    record_count: int = Field(..., description="Number of aggregate records found", ge=0)
    results: List[Dict[str, Any]] = Field(default_factory=list, description="Search result records")
    fields: List[Dict[str, str]] = Field(default_factory=list, description="Field definitions for results")
    pending_warnings: List[str] = Field(default_factory=list, description="Pending warnings from search")
    pending_errors: List[str] = Field(default_factory=list, description="Pending errors from search")
    histogram_buckets: Optional[List[Dict[str, Any]]] = Field(None, description="Histogram data buckets")
    
    @validator('job_id')
    def validate_job_id(cls, v):
        """Validate job ID format."""
        if not v or not isinstance(v, str):
            raise ValueError('Job ID must be a non-empty string')
        return v


class SearchJobStatus(BaseModel):
    """Model for search job status information."""
    
    job_id: str = Field(..., description="Search job identifier")
    state: SearchJobState = Field(..., description="Current job state")
    message_count: int = Field(..., description="Current message count", ge=0)
    record_count: int = Field(..., description="Current record count", ge=0)
    pending_warnings: List[str] = Field(default_factory=list, description="Pending warnings")
    pending_errors: List[str] = Field(default_factory=list, description="Pending errors")
    histogram_buckets: Optional[List[Dict[str, Any]]] = Field(None, description="Histogram buckets")


class DashboardPanel(BaseModel):
    """Model for dashboard panel configuration."""
    
    id: Optional[str] = Field(None, description="Panel ID")
    title: str = Field(..., description="Panel title")
    visual_settings: Dict[str, Any] = Field(..., description="Visual settings for the panel")
    keep_visual_settings_consistent_with_parent: bool = Field(default=True, description="Keep settings consistent")
    panel_type: str = Field(..., description="Type of panel (e.g., 'SumoSearchPanel')")
    queries: List[Dict[str, Any]] = Field(default_factory=list, description="Panel queries")
    description: Optional[str] = Field(None, description="Panel description")
    time_range: Optional[Dict[str, Any]] = Field(None, description="Time range for panel")
    color_by: Optional[List[Dict[str, Any]]] = Field(None, description="Color configuration")
    linked_dashboards: Optional[List[Dict[str, Any]]] = Field(None, description="Linked dashboards")


class DashboardInfo(BaseModel):
    """Model for dashboard information."""
    
    id: str = Field(..., description="Dashboard ID")
    title: str = Field(..., description="Dashboard title")
    description: Optional[str] = Field(None, description="Dashboard description")
    folder_id: Optional[str] = Field(None, description="Parent folder ID")
    topology_label_map: Optional[Dict[str, Any]] = Field(None, description="Topology label mapping")
    domain: Optional[str] = Field(None, description="Dashboard domain")
    hierarchies: Optional[List[str]] = Field(None, description="Dashboard hierarchies")
    refresh_interval: Optional[int] = Field(None, description="Auto-refresh interval in seconds")
    theme: str = Field(default="Light", description="Dashboard theme")
    panels: List[DashboardPanel] = Field(default_factory=list, description="Dashboard panels")
    layout: Optional[Dict[str, Any]] = Field(None, description="Dashboard layout configuration")
    variables: Optional[List[Dict[str, Any]]] = Field(None, description="Dashboard variables")
    color_by: Optional[List[Dict[str, Any]]] = Field(None, description="Color configuration")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    created_by: Optional[str] = Field(None, description="Creator user ID")
    modified_at: Optional[str] = Field(None, description="Last modification timestamp")
    modified_by: Optional[str] = Field(None, description="Last modifier user ID")
    version: Optional[int] = Field(None, description="Dashboard version")
    
    @validator('id')
    def validate_id(cls, v):
        """Validate dashboard ID."""
        if not v or not isinstance(v, str):
            raise ValueError('Dashboard ID must be a non-empty string')
        return v


class CollectorType(str, Enum):
    """Enumeration of collector types."""
    INSTALLABLE = "Installable"
    HOSTED = "Hosted"


class CollectorStatus(str, Enum):
    """Enumeration of collector statuses."""
    ONLINE = "Online"
    OFFLINE = "Offline"
    PENDING = "Pending"


class SourceInfo(BaseModel):
    """Model for source information."""
    
    id: int = Field(..., description="Source ID")
    name: str = Field(..., description="Source name")
    description: Optional[str] = Field(None, description="Source description")
    category: Optional[str] = Field(None, description="Source category")
    host_name: Optional[str] = Field(None, description="Host name")
    time_zone: str = Field(default="UTC", description="Time zone")
    source_type: str = Field(..., description="Type of source")
    alive: bool = Field(..., description="Whether source is alive")
    status: Optional[Dict[str, Any]] = Field(None, description="Source status information")
    scan_interval: Optional[int] = Field(None, description="Scan interval in milliseconds")
    content_type: Optional[str] = Field(None, description="Content type")
    message_per_request: Optional[bool] = Field(None, description="Message per request setting")
    multiline_processing_enabled: Optional[bool] = Field(None, description="Multiline processing enabled")
    use_autoline_matching: Optional[bool] = Field(None, description="Use autoline matching")
    manual_prefix_regexp: Optional[str] = Field(None, description="Manual prefix regex")
    force_time_zone: Optional[bool] = Field(None, description="Force time zone")
    default_date_format: Optional[str] = Field(None, description="Default date format")
    filters: Optional[List[Dict[str, Any]]] = Field(None, description="Processing filters")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    created_by: Optional[str] = Field(None, description="Creator user ID")
    modified_at: Optional[str] = Field(None, description="Last modification timestamp")
    modified_by: Optional[str] = Field(None, description="Last modifier user ID")


class CollectorInfo(BaseModel):
    """Model for collector information."""
    
    id: int = Field(..., description="Collector ID")
    name: str = Field(..., description="Collector name")
    description: Optional[str] = Field(None, description="Collector description")
    category: Optional[str] = Field(None, description="Collector category")
    time_zone: str = Field(default="UTC", description="Time zone")
    links: Optional[List[Dict[str, str]]] = Field(None, description="Related links")
    ephemeral: bool = Field(default=True, description="Whether collector is ephemeral")
    source_sync_mode: str = Field(default="UI", description="Source synchronization mode")
    collector_type: CollectorType = Field(..., description="Type of collector")
    collector_version: Optional[str] = Field(None, description="Collector version")
    last_seen_alive: Optional[int] = Field(None, description="Last seen alive timestamp")
    alive: bool = Field(..., description="Whether collector is alive")
    host_name: Optional[str] = Field(None, description="Host name for hosted collectors")
    status: Optional[CollectorStatus] = Field(None, description="Collector status")
    message: Optional[str] = Field(None, description="Status message")
    os_name: Optional[str] = Field(None, description="Operating system name")
    os_arch: Optional[str] = Field(None, description="Operating system architecture")
    os_version: Optional[str] = Field(None, description="Operating system version")
    sources: Optional[List[SourceInfo]] = Field(None, description="Sources associated with collector")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    created_by: Optional[str] = Field(None, description="Creator user ID")
    modified_at: Optional[str] = Field(None, description="Last modification timestamp")
    modified_by: Optional[str] = Field(None, description="Last modifier user ID")
    
    @validator('id')
    def validate_id(cls, v):
        """Validate collector ID."""
        if v is None or v < 0:
            raise ValueError('Collector ID must be a non-negative integer')
        return v


class MetricsQueryResult(BaseModel):
    """Model for metrics query result data."""
    
    query: str = Field(..., description="Original metrics query")
    time_series: List[Dict[str, Any]] = Field(default_factory=list, description="Time series data")
    tabular_data: Optional[List[Dict[str, Any]]] = Field(None, description="Tabular result data")
    query_info: Optional[Dict[str, Any]] = Field(None, description="Query execution information")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    
    @validator('query')
    def validate_query(cls, v):
        """Validate metrics query."""
        if not v or not isinstance(v, str):
            raise ValueError('Query must be a non-empty string')
        return v


class FolderInfo(BaseModel):
    """Model for folder information."""
    
    id: str = Field(..., description="Folder ID")
    name: str = Field(..., description="Folder name")
    description: Optional[str] = Field(None, description="Folder description")
    parent_id: Optional[str] = Field(None, description="Parent folder ID")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    created_by: Optional[str] = Field(None, description="Creator user ID")
    modified_at: Optional[str] = Field(None, description="Last modification timestamp")
    modified_by: Optional[str] = Field(None, description="Last modifier user ID")
    item_type: str = Field(default="Folder", description="Item type")
    permissions: Optional[List[str]] = Field(None, description="Folder permissions")
    children: Optional[List[Dict[str, Any]]] = Field(None, description="Child items")


class APIResponse(BaseModel):
    """Generic API response wrapper."""
    
    status: str = Field(..., description="Response status")
    message: Optional[str] = Field(None, description="Response message")
    data: Optional[Union[Dict[str, Any], List[Any]]] = Field(None, description="Response data")
    errors: Optional[List[str]] = Field(None, description="Error messages")
    warnings: Optional[List[str]] = Field(None, description="Warning messages")


class PaginatedResponse(BaseModel):
    """Model for paginated API responses."""
    
    data: List[Dict[str, Any]] = Field(..., description="Response data items")
    total: Optional[int] = Field(None, description="Total number of items")
    offset: int = Field(default=0, description="Current offset")
    limit: int = Field(default=100, description="Items per page")
    has_more: Optional[bool] = Field(None, description="Whether more items are available")
    next_token: Optional[str] = Field(None, description="Token for next page")
    
    @validator('offset')
    def validate_offset(cls, v):
        """Validate offset is non-negative."""
        if v < 0:
            raise ValueError('Offset must be non-negative')
        return v
    
    @validator('limit')
    def validate_limit(cls, v):
        """Validate limit is positive."""
        if v <= 0:
            raise ValueError('Limit must be positive')
        return v