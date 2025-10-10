"""Monitor-specific data models for Sumo Logic MCP server."""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Union
from enum import Enum
import re


class MonitorType(str, Enum):
    """Enumeration of monitor types."""
    LOGS = "MonitorsLibraryMonitor"
    METRICS = "MetricsMonitor"
    SLI = "SliMonitor"


class TriggerType(str, Enum):
    """Enumeration of trigger condition types."""
    CRITICAL = "Critical"
    WARNING = "Warning"
    MISSING_DATA = "MissingData"


class NotificationType(str, Enum):
    """Enumeration of notification action types."""
    EMAIL = "EmailAction"
    WEBHOOK = "WebhookAction"
    SLACK = "SlackAction"
    PAGERDUTY = "PagerDutyAction"


class MonitorStatus(str, Enum):
    """Enumeration of monitor status values."""
    NORMAL = "Normal"
    TRIGGERED = "Triggered"
    DISABLED = "Disabled"
    UNKNOWN = "Unknown"


class ThresholdType(str, Enum):
    """Enumeration of threshold comparison types."""
    GREATER_THAN = "GreaterThan"
    LESS_THAN = "LessThan"
    GREATER_THAN_OR_EQUAL = "GreaterThanOrEqual"
    LESS_THAN_OR_EQUAL = "LessThanOrEqual"


class OccurrenceType(str, Enum):
    """Enumeration of occurrence types for trigger conditions."""
    RESULT_COUNT = "ResultCount"
    AT_LEAST_ONCE = "AtLeastOnce"
    ALWAYS = "Always"


class TriggerSource(str, Enum):
    """Enumeration of trigger source types."""
    ALL_RESULTS = "AllResults"
    ANY_TIME_SERIES = "AnyTimeSeries"
    ALL_TIME_SERIES = "AllTimeSeries"


class TriggerCondition(BaseModel):
    """Model for monitor trigger condition configuration."""
    
    threshold: float = Field(..., description="Threshold value for triggering")
    threshold_type: ThresholdType = Field(..., description="Type of threshold comparison")
    time_range: str = Field(..., description="Time range for evaluation (e.g., '-5m', '-1h')")
    occurrence_type: OccurrenceType = Field(default=OccurrenceType.RESULT_COUNT, description="Type of occurrence evaluation")
    trigger_source: TriggerSource = Field(default=TriggerSource.ALL_RESULTS, description="Source for trigger evaluation")
    
    @validator('time_range')
    def validate_time_range(cls, v):
        """Validate time range format."""
        # Allow relative time expressions like -5m, -1h, -1d
        if not re.match(r'^-?\d+[smhdw]$', v):
            raise ValueError('Time range must be in relative format (e.g., -5m, -1h, -1d)')
        return v
    
    @validator('threshold')
    def validate_threshold(cls, v):
        """Validate threshold is a valid number."""
        if not isinstance(v, (int, float)):
            raise ValueError('Threshold must be a number')
        return float(v)


class NotificationAction(BaseModel):
    """Model for notification action configuration."""
    
    action_type: NotificationType = Field(..., description="Type of notification action")
    subject: Optional[str] = Field(None, description="Subject line for notifications", max_length=255)
    recipients: Optional[List[str]] = Field(None, description="List of notification recipients")
    webhook_url: Optional[str] = Field(None, description="Webhook URL for webhook notifications")
    message_body: Optional[str] = Field(None, description="Custom message body for notifications", max_length=2000)
    
    @validator('recipients')
    def validate_recipients(cls, v, values):
        """Validate recipients based on action type."""
        action_type = values.get('action_type')
        
        if action_type == NotificationType.EMAIL and v:
            # Validate email addresses
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            for email in v:
                if not re.match(email_pattern, email):
                    raise ValueError(f'Invalid email address: {email}')
        
        return v
    
    @validator('webhook_url')
    def validate_webhook_url(cls, v, values):
        """Validate webhook URL format."""
        action_type = values.get('action_type')
        
        if action_type == NotificationType.WEBHOOK:
            if not v:
                raise ValueError('Webhook URL is required for webhook notifications')
            if not v.startswith(('http://', 'https://')):
                raise ValueError('Webhook URL must start with http:// or https://')
        
        return v


class MonitorConfig(BaseModel):
    """Model for monitor configuration."""
    
    name: str = Field(..., description="Monitor name", min_length=1, max_length=255)
    description: Optional[str] = Field("", description="Monitor description", max_length=1000)
    type: MonitorType = Field(..., description="Type of monitor")
    query: str = Field(..., description="Monitor query string", min_length=1)
    trigger_conditions: Dict[TriggerType, TriggerCondition] = Field(..., description="Trigger conditions for different severity levels")
    notifications: List[NotificationAction] = Field(default_factory=list, description="Notification actions")
    is_disabled: bool = Field(default=False, description="Whether monitor is disabled")
    group_notifications: bool = Field(default=True, description="Whether to group notifications")
    evaluation_delay: Optional[str] = Field(default="0m", description="Delay before evaluation (e.g., '5m')")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate monitor name."""
        if not v.strip():
            raise ValueError('Monitor name cannot be empty')
        # Check for invalid characters that might cause issues
        if re.search(r'[<>:"/\\|?*]', v):
            raise ValueError('Monitor name contains invalid characters')
        return v.strip()
    
    @validator('query')
    def validate_query(cls, v):
        """Validate monitor query is not empty."""
        if not v.strip():
            raise ValueError('Monitor query cannot be empty')
        return v.strip()
    
    @validator('trigger_conditions')
    def validate_trigger_conditions(cls, v):
        """Validate trigger conditions."""
        if not v:
            raise ValueError('At least one trigger condition must be specified')
        
        # Ensure at least one condition is provided
        valid_triggers = [TriggerType.CRITICAL, TriggerType.WARNING, TriggerType.MISSING_DATA]
        if not any(trigger in v for trigger in valid_triggers):
            raise ValueError('At least one valid trigger condition (Critical, Warning, or MissingData) must be specified')
        
        return v
    
    @validator('evaluation_delay')
    def validate_evaluation_delay(cls, v):
        """Validate evaluation delay format."""
        if v and not re.match(r'^\d+[smh]$', v):
            raise ValueError('Evaluation delay must be in format like "5m", "1h", "30s"')
        return v


class MonitorResponse(BaseModel):
    """Model for monitor response data."""
    
    id: str = Field(..., description="Monitor ID")
    name: str = Field(..., description="Monitor name")
    description: str = Field(..., description="Monitor description")
    type: str = Field(..., description="Monitor type")
    query: str = Field(..., description="Monitor query")
    is_disabled: bool = Field(..., description="Whether monitor is disabled")
    status: str = Field(..., description="Current monitor status")
    created_at: str = Field(..., description="Creation timestamp")
    created_by: str = Field(..., description="Creator user ID")
    modified_at: str = Field(..., description="Last modification timestamp")
    modified_by: str = Field(..., description="Last modifier user ID")
    version: int = Field(..., description="Monitor version number")
    trigger_conditions: Dict[str, Any] = Field(..., description="Trigger conditions configuration")
    notifications: List[Dict[str, Any]] = Field(..., description="Notification actions configuration")
    evaluation_delay: Optional[str] = Field(None, description="Evaluation delay setting")
    group_notifications: Optional[bool] = Field(None, description="Group notifications setting")
    
    @validator('id')
    def validate_id(cls, v):
        """Validate monitor ID."""
        if not v or not isinstance(v, str):
            raise ValueError('Monitor ID must be a non-empty string')
        return v
    
    @validator('version')
    def validate_version(cls, v):
        """Validate version is positive."""
        if v < 1:
            raise ValueError('Monitor version must be positive')
        return v


class MonitorStatusInfo(BaseModel):
    """Model for monitor status information."""
    
    monitor_id: str = Field(..., description="Monitor ID")
    monitor_name: str = Field(..., description="Monitor name")
    status: MonitorStatus = Field(..., description="Current monitor status")
    last_triggered: Optional[str] = Field(None, description="Last trigger timestamp")
    trigger_count_24h: int = Field(default=0, description="Number of triggers in last 24 hours", ge=0)
    current_trigger_severity: Optional[str] = Field(None, description="Current trigger severity level")
    last_evaluation: Optional[str] = Field(None, description="Last evaluation timestamp")
    next_evaluation: Optional[str] = Field(None, description="Next scheduled evaluation timestamp")
    
    @validator('monitor_id')
    def validate_monitor_id(cls, v):
        """Validate monitor ID."""
        if not v or not isinstance(v, str):
            raise ValueError('Monitor ID must be a non-empty string')
        return v


class ActiveAlert(BaseModel):
    """Model for active alert information."""
    
    monitor_id: str = Field(..., description="Monitor ID")
    monitor_name: str = Field(..., description="Monitor name")
    severity: str = Field(..., description="Alert severity level")
    triggered_at: str = Field(..., description="Alert trigger timestamp")
    trigger_value: float = Field(..., description="Value that triggered the alert")
    threshold: float = Field(..., description="Threshold that was exceeded")
    query: str = Field(..., description="Monitor query that triggered")
    alert_id: str = Field(..., description="Unique alert identifier")
    status: str = Field(default="Active", description="Alert status")
    
    @validator('monitor_id', 'alert_id')
    def validate_ids(cls, v):
        """Validate ID fields."""
        if not v or not isinstance(v, str):
            raise ValueError('ID must be a non-empty string')
        return v
    
    @validator('severity')
    def validate_severity(cls, v):
        """Validate severity level."""
        valid_severities = ['Critical', 'Warning', 'MissingData']
        if v not in valid_severities:
            raise ValueError(f'Severity must be one of: {", ".join(valid_severities)}')
        return v


class MonitorHistoryEntry(BaseModel):
    """Model for monitor execution history entry."""
    
    timestamp: str = Field(..., description="Execution timestamp")
    status: str = Field(..., description="Execution status")
    execution_duration_ms: Optional[int] = Field(None, description="Execution duration in milliseconds", ge=0)
    result_count: Optional[int] = Field(None, description="Number of results returned", ge=0)
    triggered: bool = Field(..., description="Whether monitor was triggered")
    trigger_value: Optional[float] = Field(None, description="Value that caused trigger (if triggered)")
    error_message: Optional[str] = Field(None, description="Error message if execution failed")
    
    @validator('execution_duration_ms')
    def validate_duration(cls, v):
        """Validate execution duration."""
        if v is not None and v < 0:
            raise ValueError('Execution duration must be non-negative')
        return v


class MonitorHistoryResponse(BaseModel):
    """Model for monitor history API response."""
    
    success: bool = Field(..., description="Whether the request was successful")
    monitor_id: str = Field(..., description="Monitor ID for which history was retrieved")
    execution_history: List[Dict[str, Any]] = Field(..., description="List of formatted execution history entries")
    performance_metrics: Dict[str, Any] = Field(..., description="Aggregated performance statistics")
    trigger_patterns: Dict[str, Any] = Field(..., description="Trigger pattern analysis")
    metadata: Dict[str, Any] = Field(..., description="Request metadata and pagination info")
    
    @validator('monitor_id')
    def validate_monitor_id(cls, v):
        """Validate monitor ID."""
        if not v or not isinstance(v, str):
            raise ValueError('Monitor ID must be a non-empty string')
        return v
    
    @validator('execution_history')
    def validate_execution_history(cls, v):
        """Validate execution history is a list."""
        if not isinstance(v, list):
            raise ValueError('Execution history must be a list')
        return v


class MonitorValidationResult(BaseModel):
    """Model for monitor configuration validation results."""
    
    valid: bool = Field(..., description="Whether configuration is valid")
    errors: List[str] = Field(default_factory=list, description="Validation error messages")
    warnings: List[str] = Field(default_factory=list, description="Validation warning messages")
    query_syntax_valid: Optional[bool] = Field(None, description="Whether query syntax is valid")
    trigger_conditions_valid: Optional[bool] = Field(None, description="Whether trigger conditions are valid")
    notifications_valid: Optional[bool] = Field(None, description="Whether notification configurations are valid")
    
    @validator('valid')
    def validate_consistency(cls, v, values):
        """Ensure validity is consistent with errors."""
        errors = values.get('errors', [])
        if v and errors:
            raise ValueError('Configuration cannot be valid if there are errors')
        if not v and not errors:
            raise ValueError('Configuration must have errors if marked as invalid')
        return v