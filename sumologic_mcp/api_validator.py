"""API parameter validation system for Sumo Logic MCP server.

This module provides comprehensive validation for Sumo Logic API parameters
according to the official API documentation, ensuring parameter compliance
and providing clear error messages for validation failures.
"""

import re
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator

from .exceptions import ValidationError, TimeValidationError, APIParameterError


class SumoLogicAPIValidator:
    """Validator for Sumo Logic API parameters according to official documentation."""
    
    # Official Sumo Logic API parameter schemas based on https://api.sumologic.com/docs/
    SEARCH_API_SCHEMA = {
        "query": {
            "type": "string",
            "required": True,
            "min_length": 1,
            "description": "Search query string using Sumo Logic query language"
        },
        "from": {
            "type": "string", 
            "required": True,
            "format": "iso8601_or_relative",
            "description": "Start time in ISO 8601 format or relative time (e.g., '-1h')"
        },
        "to": {
            "type": "string",
            "required": True, 
            "format": "iso8601_or_relative",
            "description": "End time in ISO 8601 format or relative time (e.g., 'now')"
        },
        "timeZone": {
            "type": "string",
            "required": False,
            "default": "UTC",
            "pattern": r"^[A-Za-z_/]+$",
            "description": "Time zone for query (e.g., 'UTC', 'America/New_York')"
        },
        "byReceiptTime": {
            "type": "boolean",
            "required": False,
            "default": False,
            "description": "Search by receipt time instead of message time"
        },
        "autoParsingMode": {
            "type": "string",
            "required": False,
            "enum": ["intelligent", "performance"],
            "description": "Auto parsing mode for log processing"
        },
        "limit": {
            "type": "integer",
            "required": False,
            "default": 100,
            "min": 1,
            "max": 10000,
            "description": "Maximum number of results to return"
        },
        "offset": {
            "type": "integer",
            "required": False,
            "default": 0,
            "min": 0,
            "description": "Starting position for result retrieval"
        }
    }
    
    MONITOR_API_SCHEMA = {
        "query": {
            "type": "string",
            "required": True,
            "min_length": 1,
            "description": "Search query for monitors"
        },
        "limit": {
            "type": "integer",
            "required": False,
            "default": 100,
            "min": 1,
            "max": 1000,
            "description": "Maximum number of results to return"
        },
        "offset": {
            "type": "integer", 
            "required": False,
            "default": 0,
            "min": 0,
            "description": "Starting position for result retrieval"
        },
        "type": {
            "type": "string",
            "required": False,
            "enum": ["MonitorsLibraryMonitor", "MonitorsLibraryFolder", "*"],
            "description": "Content type filter for monitors and folders"
        }
    }
    
    # Time format patterns
    ISO8601_PATTERN = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?([+-]\d{2}:\d{2}|Z)?$'
    )
    RELATIVE_TIME_PATTERN = re.compile(r'^-?\d+[smhdw]$|^now$')
    
    @classmethod
    def validate_search_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate search API parameters against official schema.
        
        Args:
            params: Dictionary of search parameters to validate
            
        Returns:
            Dictionary of validated and normalized parameters
            
        Raises:
            APIParameterError: If parameter validation fails
            TimeValidationError: If time format validation fails
        """
        validated_params = {}
        schema = cls.SEARCH_API_SCHEMA
        
        # Check required parameters
        for param_name, param_schema in schema.items():
            if param_schema.get("required", False) and param_name not in params:
                raise APIParameterError(
                    param_name=param_name,
                    param_value=None,
                    expected_type=param_schema["type"],
                    api_endpoint="search API"
                )
        
        # Validate each parameter
        for param_name, param_value in params.items():
            if param_name not in schema:
                # Allow unknown parameters but log warning
                validated_params[param_name] = param_value
                continue
                
            param_schema = schema[param_name]
            validated_value = cls._validate_parameter(
                param_name, param_value, param_schema, "search API"
            )
            validated_params[param_name] = validated_value
        
        # Add default values for missing optional parameters
        for param_name, param_schema in schema.items():
            if param_name not in validated_params and "default" in param_schema:
                validated_params[param_name] = param_schema["default"]
        
        # Validate time range consistency
        if "from" in validated_params and "to" in validated_params:
            cls._validate_time_range(validated_params["from"], validated_params["to"])
        
        return validated_params
    
    @classmethod
    def validate_monitor_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate monitor API parameters against official schema.
        
        Args:
            params: Dictionary of monitor parameters to validate
            
        Returns:
            Dictionary of validated and normalized parameters
            
        Raises:
            APIParameterError: If parameter validation fails
        """
        validated_params = {}
        schema = cls.MONITOR_API_SCHEMA
        
        # Check required parameters
        for param_name, param_schema in schema.items():
            if param_schema.get("required", False) and param_name not in params:
                raise APIParameterError(
                    param_name=param_name,
                    param_value=None,
                    expected_type=param_schema["type"],
                    api_endpoint="monitor API"
                )
        
        # Validate each parameter
        for param_name, param_value in params.items():
            if param_name not in schema:
                # Allow unknown parameters but include them
                validated_params[param_name] = param_value
                continue
                
            param_schema = schema[param_name]
            validated_value = cls._validate_parameter(
                param_name, param_value, param_schema, "monitor API"
            )
            validated_params[param_name] = validated_value
        
        # Add default values for missing optional parameters
        for param_name, param_schema in schema.items():
            if param_name not in validated_params and "default" in param_schema:
                validated_params[param_name] = param_schema["default"]
        
        return validated_params
    
    @classmethod
    def _validate_parameter(
        cls, 
        param_name: str, 
        param_value: Any, 
        param_schema: Dict[str, Any], 
        api_endpoint: str
    ) -> Any:
        """Validate individual parameter against schema.
        
        Args:
            param_name: Name of the parameter
            param_value: Value to validate
            param_schema: Schema definition for the parameter
            api_endpoint: API endpoint name for error context
            
        Returns:
            Validated parameter value
            
        Raises:
            APIParameterError: If parameter validation fails
            TimeValidationError: If time format validation fails
        """
        expected_type = param_schema["type"]
        
        # Type validation
        if expected_type == "string":
            if not isinstance(param_value, str):
                raise APIParameterError(param_name, param_value, "string", api_endpoint)
            
            # String length validation
            if "min_length" in param_schema and len(param_value) < param_schema["min_length"]:
                raise APIParameterError(
                    param_name, param_value, 
                    f"string with minimum length {param_schema['min_length']}", 
                    api_endpoint
                )
            
            # Pattern validation
            if "pattern" in param_schema:
                pattern = re.compile(param_schema["pattern"])
                if not pattern.match(param_value):
                    raise APIParameterError(
                        param_name, param_value,
                        f"string matching pattern {param_schema['pattern']}",
                        api_endpoint
                    )
            
            # Enum validation
            if "enum" in param_schema and param_value not in param_schema["enum"]:
                raise APIParameterError(
                    param_name, param_value,
                    f"one of {param_schema['enum']}",
                    api_endpoint
                )
            
            # Time format validation
            if param_schema.get("format") == "iso8601_or_relative":
                cls._validate_time_format(param_name, param_value)
            
            return param_value
            
        elif expected_type == "integer":
            if not isinstance(param_value, int):
                # Try to convert if it's a string representation
                if isinstance(param_value, str) and param_value.isdigit():
                    param_value = int(param_value)
                else:
                    raise APIParameterError(param_name, param_value, "integer", api_endpoint)
            
            # Range validation
            if "min" in param_schema and param_value < param_schema["min"]:
                raise APIParameterError(
                    param_name, param_value,
                    f"integer >= {param_schema['min']}",
                    api_endpoint
                )
            
            if "max" in param_schema and param_value > param_schema["max"]:
                raise APIParameterError(
                    param_name, param_value,
                    f"integer <= {param_schema['max']}",
                    api_endpoint
                )
            
            return param_value
            
        elif expected_type == "boolean":
            if not isinstance(param_value, bool):
                # Try to convert string representations
                if isinstance(param_value, str):
                    if param_value.lower() in ["true", "1", "yes"]:
                        return True
                    elif param_value.lower() in ["false", "0", "no"]:
                        return False
                
                raise APIParameterError(param_name, param_value, "boolean", api_endpoint)
            
            return param_value
        
        else:
            # Unknown type, return as-is
            return param_value
    
    @classmethod
    def _validate_time_format(cls, param_name: str, time_value: str) -> None:
        """Validate time format (ISO 8601 or relative).
        
        Args:
            param_name: Name of the time parameter
            time_value: Time value to validate
            
        Raises:
            TimeValidationError: If time format is invalid
        """
        if not isinstance(time_value, str):
            raise TimeValidationError(
                "Time value must be a string",
                str(time_value),
                "ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ) or relative format (-1h, now)"
            )
        
        # Check if it matches ISO 8601 format
        if cls.ISO8601_PATTERN.match(time_value):
            return
        
        # Check if it matches relative time format
        if cls.RELATIVE_TIME_PATTERN.match(time_value):
            return
        
        # Neither format matched
        raise TimeValidationError(
            f"Invalid time format for parameter '{param_name}'",
            time_value,
            "ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ) or relative format (-1h, -30m, now)"
        )
    
    @classmethod
    def _validate_time_range(cls, from_time: str, to_time: str) -> None:
        """Validate that time range is logical (from_time < to_time).
        
        Args:
            from_time: Start time value
            to_time: End time value
            
        Raises:
            TimeValidationError: If time range is invalid
        """
        # For relative times, we can do basic validation
        if from_time == "now" and to_time != "now":
            # "now" as from_time with a different to_time might be invalid
            if not cls.RELATIVE_TIME_PATTERN.match(to_time):
                raise TimeValidationError(
                    "When using 'now' as from_time, to_time should be a future relative time or 'now'",
                    f"from={from_time}, to={to_time}",
                    "from='now', to='now' or from='-1h', to='now'"
                )
        
        # Check for obviously invalid relative time ranges
        if from_time.startswith('-') and to_time.startswith('-'):
            # Both are negative relative times, from should be more negative (earlier)
            try:
                from_match = re.match(r'^-(\d+)([smhdw])$', from_time)
                to_match = re.match(r'^-(\d+)([smhdw])$', to_time)
                
                if from_match and to_match:
                    from_num, from_unit = int(from_match.group(1)), from_match.group(2)
                    to_num, to_unit = int(to_match.group(1)), to_match.group(2)
                    
                    # Convert to minutes for comparison
                    unit_multipliers = {'s': 1/60, 'm': 1, 'h': 60, 'd': 1440, 'w': 10080}
                    from_minutes = from_num * unit_multipliers.get(from_unit, 1)
                    to_minutes = to_num * unit_multipliers.get(to_unit, 1)
                    
                    if from_minutes <= to_minutes:
                        raise TimeValidationError(
                            "from_time must be earlier than to_time",
                            f"from={from_time}, to={to_time}",
                            "from_time should represent an earlier time than to_time (e.g., from='-2h', to='-1h')"
                        )
            except (ValueError, AttributeError):
                # If parsing fails, skip validation
                pass
    
    @classmethod
    def get_official_param_mapping(cls) -> Dict[str, Dict[str, Any]]:
        """Get mapping of correct parameter names and types for all APIs.
        
        Returns:
            Dictionary mapping API names to their parameter schemas
        """
        return {
            "search": cls.SEARCH_API_SCHEMA,
            "monitor": cls.MONITOR_API_SCHEMA
        }
    
    @classmethod
    def get_parameter_documentation(cls, api_name: str, param_name: str) -> Optional[str]:
        """Get documentation for a specific parameter.
        
        Args:
            api_name: Name of the API (e.g., 'search', 'monitor')
            param_name: Name of the parameter
            
        Returns:
            Documentation string for the parameter, or None if not found
        """
        schemas = cls.get_official_param_mapping()
        
        if api_name not in schemas:
            return None
        
        param_schema = schemas[api_name].get(param_name)
        if not param_schema:
            return None
        
        return param_schema.get("description", "No documentation available")
    
    @classmethod
    def validate_content_type_filter(cls, content_type: str) -> str:
        """Validate content type filter for monitor searches.
        
        Args:
            content_type: Content type filter value
            
        Returns:
            Validated content type filter
            
        Raises:
            APIParameterError: If content type is invalid
        """
        valid_types = ["MonitorsLibraryMonitor", "MonitorsLibraryFolder", "*"]
        
        if content_type not in valid_types:
            raise APIParameterError(
                param_name="type",
                param_value=content_type,
                expected_type=f"one of {valid_types}",
                api_endpoint="monitor API"
            )
        
        return content_type