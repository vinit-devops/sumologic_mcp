"""
Time parsing utilities for Sumo Logic MCP server.

This module provides time parsing functionality compatible with the reference
TypeScript implementation, supporting relative time expressions like '-1h', '-5m', etc.
"""

import re
from datetime import datetime, timedelta
from typing import Union, Optional
import logging

from .exceptions import TimeValidationError

logger = logging.getLogger(__name__)


class TimeParser:
    """Utility class for parsing time expressions compatible with reference implementation."""
    
    # Relative time pattern matching reference implementation - fixed regex
    RELATIVE_TIME_PATTERN = re.compile(r'^-?(\d+)([smhdw])$', re.IGNORECASE)
    
    # Time unit mappings
    TIME_UNITS = {
        's': 'seconds',
        'm': 'minutes', 
        'h': 'hours',
        'd': 'days',
        'w': 'weeks'
    }
    
    @classmethod
    def parse_time(cls, time_str: str, base_time: Optional[datetime] = None) -> datetime:
        """Parse time string into datetime object.
        
        Supports the following formats:
        - 'now' - current time
        - Relative time: '-1h', '-30m', '-24h', '-7d', '-1w'
        - ISO 8601: '2023-12-01T10:00:00Z'
        - Epoch milliseconds: '1701428400000'
        - Epoch seconds: '1701428400'
        
        Args:
            time_str: Time string to parse
            base_time: Base time for relative calculations (defaults to current time)
            
        Returns:
            Parsed datetime object
            
        Raises:
            ValueError: If time string format is not supported
        """
        if not time_str:
            raise TimeValidationError(
                "Time string cannot be empty",
                time_str or "",
                "Non-empty time string in supported format"
            )
        
        time_str = time_str.strip()
        base_time = base_time or datetime.utcnow()
        
        # Handle 'now' - use current UTC time
        if time_str.lower() == 'now':
            return datetime.utcnow()
        
        # Handle relative time expressions
        if cls._is_relative_time(time_str):
            return cls._parse_relative_time(time_str, base_time)
        
        # Handle ISO 8601 format
        if cls._is_iso_format(time_str):
            return cls._parse_iso_time(time_str)
        
        # Handle epoch time (milliseconds or seconds)
        if cls._is_epoch_time(time_str):
            return cls._parse_epoch_time(time_str)
        
        raise TimeValidationError(
            "Unsupported time format",
            time_str,
            "ISO 8601 (YYYY-MM-DDTHH:MM:SSZ), relative time (-1h, -30m, now), or epoch time (seconds/milliseconds)"
        )
    
    @classmethod
    def _is_relative_time(cls, time_str: str) -> bool:
        """Check if time string is a relative time expression."""
        return bool(cls.RELATIVE_TIME_PATTERN.match(time_str))
    
    @classmethod
    def _parse_relative_time(cls, time_str: str, base_time: datetime) -> datetime:
        """Parse relative time expression like '-1h', '-30m'."""
        match = cls.RELATIVE_TIME_PATTERN.match(time_str)
        if not match:
            raise TimeValidationError(
                "Invalid relative time format",
                time_str,
                "Relative time format like -1h, -30m, -24h, -7d, -1w, or 'now'"
            )
        
        amount_str, unit = match.groups()
        amount = int(amount_str)
        
        # Handle negative sign (going back in time)
        if time_str.startswith('-'):
            amount = -amount
        
        # Convert unit to timedelta argument
        unit_name = cls.TIME_UNITS.get(unit.lower())
        if not unit_name:
            raise TimeValidationError(
                f"Unsupported time unit '{unit}'",
                time_str,
                f"Supported units: {', '.join(cls.TIME_UNITS.keys())} (seconds, minutes, hours, days, weeks)"
            )
        
        # Create timedelta
        delta_kwargs = {unit_name: amount}
        delta = timedelta(**delta_kwargs)
        
        return base_time + delta
    
    @classmethod
    def _is_iso_format(cls, time_str: str) -> bool:
        """Check if time string is in ISO 8601 format."""
        # Basic ISO 8601 pattern - fixed patterns
        iso_patterns = [
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z?$',
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?[+-]\d{2}:\d{2}$',
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?Z?$'
        ]
        
        return any(re.match(pattern, time_str) for pattern in iso_patterns)
    
    @classmethod
    def _parse_iso_time(cls, time_str: str) -> datetime:
        """Parse ISO 8601 time string."""
        try:
            # Handle different ISO formats
            formats_to_try = [
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f'
            ]
            
            # Remove timezone info for parsing (assume UTC)
            clean_time = time_str.rstrip('Z')
            if '+' in clean_time or clean_time.count('-') > 2:
                # Has timezone offset, extract the datetime part
                clean_time = re.sub(r'[+-]\d{2}:\d{2}$', '', clean_time)
            
            for fmt in formats_to_try:
                try:
                    return datetime.strptime(clean_time, fmt)
                except ValueError:
                    continue
            
            # Fallback to fromisoformat (Python 3.7+)
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            
        except Exception as e:
            raise TimeValidationError(
                f"Failed to parse ISO 8601 time format: {str(e)}",
                time_str,
                "ISO 8601 format like 2023-12-01T10:00:00Z or 2023-12-01T10:00:00.123Z"
            )
    
    @classmethod
    def _is_epoch_time(cls, time_str: str) -> bool:
        """Check if time string is epoch time (seconds or milliseconds)."""
        try:
            int(time_str)
            return True
        except ValueError:
            return False
    
    @classmethod
    def _parse_epoch_time(cls, time_str: str) -> datetime:
        """Parse epoch time (seconds or milliseconds)."""
        try:
            timestamp = int(time_str)
            
            # Determine if it's seconds or milliseconds based on magnitude
            # Timestamps after year 2001 in seconds are > 1000000000
            # Timestamps in milliseconds are > 1000000000000
            if timestamp > 1000000000000:
                # Milliseconds
                return datetime.fromtimestamp(timestamp / 1000)
            else:
                # Seconds
                return datetime.fromtimestamp(timestamp)
                
        except (ValueError, OSError) as e:
            raise TimeValidationError(
                f"Failed to parse epoch time: {str(e)}",
                time_str,
                "Epoch time in seconds (1701428400) or milliseconds (1701428400000)"
            )
    
    @classmethod
    def to_sumo_api_format(cls, dt: datetime) -> str:
        """Convert datetime to exact Sumo Logic API format.
        
        Args:
            dt: Datetime object to convert
            
        Returns:
            Time string in exact Sumo Logic API format (ISO 8601 with milliseconds and Z suffix)
        """
        # Sumo Logic API expects ISO 8601 format with milliseconds and Z suffix
        # Format: YYYY-MM-DDTHH:MM:SS.sssZ
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    
    @classmethod
    def to_sumo_time_format(cls, dt: datetime) -> str:
        """Convert datetime to Sumo Logic API time format.
        
        Args:
            dt: Datetime object to convert
            
        Returns:
            Time string in Sumo Logic API format (ISO 8601 with milliseconds)
        """
        # Sumo Logic expects ISO format with milliseconds
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    
    @classmethod
    def validate_time_range(cls, from_time: str, to_time: str) -> tuple[datetime, datetime]:
        """Validate and parse a time range.
        
        Args:
            from_time: Start time string
            to_time: End time string
            
        Returns:
            Tuple of (start_datetime, end_datetime)
            
        Raises:
            ValueError: If time range is invalid
        """
        try:
            start_dt = cls.parse_time(from_time)
            end_dt = cls.parse_time(to_time)
            
            if start_dt >= end_dt:
                raise TimeValidationError(
                    f"Start time must be before end time",
                    f"from_time='{from_time}', to_time='{to_time}'",
                    "from_time should represent an earlier time than to_time (e.g., from='-2h', to='-1h' or from='2023-12-01T09:00:00Z', to='2023-12-01T10:00:00Z')"
                )
            
            # Check for reasonable time range (not more than 1 year)
            max_range = timedelta(days=365)
            if end_dt - start_dt > max_range:
                raise TimeValidationError(
                    f"Time range too large: {end_dt - start_dt}",
                    f"from_time='{from_time}', to_time='{to_time}'",
                    f"Maximum allowed time range: {max_range} (365 days). Consider using a smaller time window for better performance."
                )
            
            return start_dt, end_dt
            
        except TimeValidationError:
            # Re-raise TimeValidationError as-is
            raise
        except Exception as e:
            raise TimeValidationError(
                f"Invalid time range: {str(e)}",
                f"from_time='{from_time}', to_time='{to_time}'",
                "Valid time formats: ISO 8601, relative time (-1h, -30m, now), or epoch time"
            )
    
    @classmethod
    def validate_and_convert_time_range(cls, from_time: str, to_time: str) -> tuple[str, str]:
        """Validate and convert time range to Sumo Logic API format.
        
        Args:
            from_time: Start time string (supports relative, ISO 8601, epoch, or 'now')
            to_time: End time string (supports relative, ISO 8601, epoch, or 'now')
            
        Returns:
            Tuple of (from_api_format, to_api_format) in Sumo Logic API format
            
        Raises:
            ValueError: If time range is invalid or formats are unsupported
        """
        try:
            # Parse and validate the time range
            start_dt, end_dt = cls.validate_time_range(from_time, to_time)
            
            # Convert to Sumo Logic API format
            from_api_format = cls.to_sumo_api_format(start_dt)
            to_api_format = cls.to_sumo_api_format(end_dt)
            
            logger.debug(f"Converted time range: {from_time} -> {from_api_format}, {to_time} -> {to_api_format}")
            
            return from_api_format, to_api_format
            
        except TimeValidationError:
            # Re-raise TimeValidationError as-is
            raise
        except Exception as e:
            raise TimeValidationError(
                f"Failed to validate and convert time range: {str(e)}",
                f"from_time='{from_time}', to_time='{to_time}'",
                "Ensure both time values are in supported formats and form a valid time range"
            )
    
    @classmethod
    def convert_now_to_api_format(cls) -> str:
        """Convert 'now' to current timestamp in Sumo Logic API format.
        
        Returns:
            Current timestamp in ISO 8601 format with milliseconds and Z suffix
        """
        return cls.to_sumo_api_format(datetime.utcnow())
    
    @classmethod
    def convert_time_for_api(cls, time_str: str) -> str:
        """Convert any time format to Sumo Logic API format.
        
        Args:
            time_str: Time string in any supported format
            
        Returns:
            Time string in Sumo Logic API format
            
        Raises:
            TimeValidationError: If time format is not supported
        """
        # Handle 'now' specifically for API calls
        if time_str.lower() == 'now':
            return cls.convert_now_to_api_format()
        
        # Parse the time and convert to API format
        dt = cls.parse_time(time_str)
        return cls.to_sumo_api_format(dt)
    
    @classmethod
    def get_relative_time_examples(cls) -> list[dict]:
        """Get examples of supported relative time formats.
        
        Returns:
            List of example time formats with descriptions
        """
        return [
            {"format": "now", "description": "Current time"},
            {"format": "-1h", "description": "1 hour ago"},
            {"format": "-30m", "description": "30 minutes ago"},
            {"format": "-5m", "description": "5 minutes ago"},
            {"format": "-24h", "description": "24 hours ago"},
            {"format": "-7d", "description": "7 days ago"},
            {"format": "-1w", "description": "1 week ago"},
            {"format": "2023-12-01T10:00:00Z", "description": "ISO 8601 format"},
            {"format": "1701428400000", "description": "Epoch milliseconds"},
            {"format": "1701428400", "description": "Epoch seconds"}
        ]


class VMwareQueryPatterns:
    """VMware-specific query patterns and utilities."""
    
    # Common VMware metric patterns
    VMWARE_METRICS = {
        'cpu': [
            'vm.cpu.usage.average',
            'vm.cpu.ready.summation',
            'host.cpu.usage.average',
            'host.cpu.utilization.average'
        ],
        'memory': [
            'vm.memory.usage.average',
            'vm.memory.consumed.average',
            'host.memory.usage.average',
            'host.memory.consumed.average'
        ],
        'disk': [
            'vm.disk.usage.average',
            'vm.disk.read.average',
            'vm.disk.write.average',
            'datastore.disk.used.latest',
            'datastore.disk.capacity.latest'
        ],
        'network': [
            'vm.network.usage.average',
            'vm.network.received.average',
            'vm.network.transmitted.average',
            'host.network.usage.average'
        ]
    }
    
    # Common VMware resource attributes
    VMWARE_ATTRIBUTES = [
        'vm.name',
        'vm.uuid',
        'host.name',
        'cluster.name',
        'datacenter.name',
        'resource_pool.name',
        'datastore.name',
        'vcenter.name',
        'instance.name',
        'resource.name'
    ]
    
    @classmethod
    def get_cpu_queries(cls, source_category: str = "otel/vmware") -> list[dict]:
        """Get CPU-related VMware query patterns."""
        return [
            {
                "name": "VM CPU Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.cpu.usage.average"',
                "description": "Monitor virtual machine CPU usage percentage"
            },
            {
                "name": "VM CPU Ready Time",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.cpu.ready.summation"',
                "description": "Monitor VM CPU ready time (indicates CPU contention)"
            },
            {
                "name": "Host CPU Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="host.cpu.usage.average"',
                "description": "Monitor ESXi host CPU usage"
            },
            {
                "name": "Top CPU Consumers",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.cpu.usage.average" | avg by vm.name | sort by _avg desc | limit 10',
                "description": "Find VMs with highest CPU usage"
            }
        ]
    
    @classmethod
    def get_memory_queries(cls, source_category: str = "otel/vmware") -> list[dict]:
        """Get memory-related VMware query patterns."""
        return [
            {
                "name": "VM Memory Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.memory.usage.average"',
                "description": "Monitor virtual machine memory usage percentage"
            },
            {
                "name": "VM Memory Consumed",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.memory.consumed.average"',
                "description": "Monitor actual memory consumed by VMs"
            },
            {
                "name": "Host Memory Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="host.memory.usage.average"',
                "description": "Monitor ESXi host memory usage"
            },
            {
                "name": "Memory Pressure Analysis",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.memory.usage.average" | where _value > 80 | count by vm.name',
                "description": "Find VMs with high memory pressure (>80%)"
            }
        ]
    
    @classmethod
    def get_storage_queries(cls, source_category: str = "otel/vmware") -> list[dict]:
        """Get storage-related VMware query patterns."""
        return [
            {
                "name": "Datastore Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="datastore.disk.used.latest"',
                "description": "Monitor datastore disk usage"
            },
            {
                "name": "Datastore Capacity",
                "query": f'_sourceCategory="{source_category}" metric_name="datastore.disk.capacity.latest"',
                "description": "Monitor datastore total capacity"
            },
            {
                "name": "VM Disk Performance",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.disk.usage.average" | avg by vm.name',
                "description": "Monitor VM disk I/O performance"
            },
            {
                "name": "Datastore Utilization",
                "query": f'_sourceCategory="{source_category}" (metric_name="datastore.disk.used.latest" OR metric_name="datastore.disk.capacity.latest") | eval utilization = used/capacity*100 | fields datastore.name, utilization',
                "description": "Calculate datastore utilization percentage"
            }
        ]
    
    @classmethod
    def get_network_queries(cls, source_category: str = "otel/vmware") -> list[dict]:
        """Get network-related VMware query patterns."""
        return [
            {
                "name": "VM Network Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.network.usage.average"',
                "description": "Monitor VM network usage"
            },
            {
                "name": "VM Network Received",
                "query": f'_sourceCategory="{source_category}" metric_name="vm.network.received.average"',
                "description": "Monitor VM network received traffic"
            },
            {
                "name": "VM Network Transmitted", 
                "query": f'_sourceCategory="{source_category}" metric_name="vm.network.transmitted.average"',
                "description": "Monitor VM network transmitted traffic"
            },
            {
                "name": "Host Network Usage",
                "query": f'_sourceCategory="{source_category}" metric_name="host.network.usage.average"',
                "description": "Monitor ESXi host network usage"
            }
        ]
    
    @classmethod
    def get_all_query_patterns(cls, source_category: str = "otel/vmware") -> dict:
        """Get all VMware query patterns organized by category."""
        return {
            "cpu": cls.get_cpu_queries(source_category),
            "memory": cls.get_memory_queries(source_category),
            "storage": cls.get_storage_queries(source_category),
            "network": cls.get_network_queries(source_category)
        }
    
    @classmethod
    def get_resource_discovery_query(cls, source_category: str = "otel/vmware") -> str:
        """Get query for discovering VMware resources."""
        return f'_sourceCategory="{source_category}" | json auto | keys | where _key matches "*name*" OR _key matches "*uuid*" | count by _key'
    
    @classmethod
    def get_metric_discovery_query(cls, source_category: str = "otel/vmware") -> str:
        """Get query for discovering VMware metrics."""
        return f'_sourceCategory="{source_category}" | json auto | where metric_name matches "*" | count by metric_name | sort by _count desc'