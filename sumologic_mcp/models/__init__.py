"""Data models for Sumo Logic MCP server."""

from .config import (
    SumoLogicConfig,
    SearchRequest,
    DashboardConfig,
    MetricsRequest,
    CollectorConfig,
    SourceConfig
)

from .responses import (
    SearchResult,
    SearchJobStatus,
    SearchJobState,
    DashboardInfo,
    DashboardPanel,
    CollectorInfo,
    CollectorType,
    CollectorStatus,
    SourceInfo,
    MetricsQueryResult,
    FolderInfo,
    APIResponse,
    PaginatedResponse
)

__all__ = [
    # Configuration models
    'SumoLogicConfig',
    'SearchRequest', 
    'DashboardConfig',
    'MetricsRequest',
    'CollectorConfig',
    'SourceConfig',
    
    # Response models
    'SearchResult',
    'SearchJobStatus',
    'SearchJobState',
    'DashboardInfo',
    'DashboardPanel',
    'CollectorInfo',
    'CollectorType',
    'CollectorStatus',
    'SourceInfo',
    'MetricsQueryResult',
    'FolderInfo',
    'APIResponse',
    'PaginatedResponse'
]