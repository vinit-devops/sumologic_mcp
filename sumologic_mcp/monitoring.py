"""Monitoring and health check functionality for Sumo Logic MCP server.

This module provides comprehensive monitoring capabilities including health checks,
metrics collection, and connection status monitoring for the Sumo Logic APIs.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union
from collections import defaultdict, deque

from .exceptions import SumoLogicError, APIError, TimeoutError


logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class MetricType(Enum):
    """Types of metrics that can be collected."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    timestamp: datetime
    duration_ms: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "details": self.details
        }


@dataclass
class MetricValue:
    """A metric value with timestamp."""
    value: Union[int, float]
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels
        }


class MetricsCollector:
    """Collects and stores metrics for monitoring."""
    
    def __init__(self, max_history: int = 1000):
        """Initialize metrics collector.
        
        Args:
            max_history: Maximum number of metric values to keep in history
        """
        self.max_history = max_history
        self._metrics: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "type": MetricType.COUNTER,
            "values": deque(maxlen=max_history),
            "current_value": 0,
            "labels": {}
        })
        self._lock = asyncio.Lock()
        
        logger.info(f"Initialized metrics collector with max_history={max_history}")
    
    async def increment_counter(
        self,
        name: str,
        value: Union[int, float] = 1,
        labels: Optional[Dict[str, str]] = None
    ):
        """Increment a counter metric.
        
        Args:
            name: Metric name
            value: Value to increment by
            labels: Optional labels for the metric
        """
        async with self._lock:
            metric = self._metrics[name]
            metric["type"] = MetricType.COUNTER
            metric["current_value"] += value
            
            metric_value = MetricValue(
                value=metric["current_value"],
                timestamp=datetime.utcnow(),
                labels=labels or {}
            )
            metric["values"].append(metric_value)
            
            if labels:
                metric["labels"].update(labels)
        
        logger.debug(f"Incremented counter '{name}' by {value}")
    
    async def set_gauge(
        self,
        name: str,
        value: Union[int, float],
        labels: Optional[Dict[str, str]] = None
    ):
        """Set a gauge metric value.
        
        Args:
            name: Metric name
            value: Gauge value
            labels: Optional labels for the metric
        """
        async with self._lock:
            metric = self._metrics[name]
            metric["type"] = MetricType.GAUGE
            metric["current_value"] = value
            
            metric_value = MetricValue(
                value=value,
                timestamp=datetime.utcnow(),
                labels=labels or {}
            )
            metric["values"].append(metric_value)
            
            if labels:
                metric["labels"].update(labels)
        
        logger.debug(f"Set gauge '{name}' to {value}")
    
    async def record_timer(
        self,
        name: str,
        duration_ms: float,
        labels: Optional[Dict[str, str]] = None
    ):
        """Record a timer metric.
        
        Args:
            name: Metric name
            duration_ms: Duration in milliseconds
            labels: Optional labels for the metric
        """
        async with self._lock:
            metric = self._metrics[name]
            metric["type"] = MetricType.TIMER
            
            metric_value = MetricValue(
                value=duration_ms,
                timestamp=datetime.utcnow(),
                labels=labels or {}
            )
            metric["values"].append(metric_value)
            
            if labels:
                metric["labels"].update(labels)
        
        logger.debug(f"Recorded timer '{name}': {duration_ms}ms")
    
    async def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a metric by name.
        
        Args:
            name: Metric name
            
        Returns:
            Metric data or None if not found
        """
        async with self._lock:
            if name not in self._metrics:
                return None
            
            metric = self._metrics[name]
            return {
                "name": name,
                "type": metric["type"].value,
                "current_value": metric["current_value"],
                "labels": metric["labels"],
                "history_count": len(metric["values"]),
                "latest_values": [v.to_dict() for v in list(metric["values"])[-10:]]
            }
    
    async def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics.
        
        Returns:
            Dictionary of all metrics
        """
        async with self._lock:
            result = {}
            for name in self._metrics:
                result[name] = await self.get_metric(name)
            return result
    
    async def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics.
        
        Returns:
            Summary of metrics
        """
        async with self._lock:
            summary = {
                "total_metrics": len(self._metrics),
                "metrics_by_type": defaultdict(int),
                "total_data_points": 0
            }
            
            for metric in self._metrics.values():
                summary["metrics_by_type"][metric["type"].value] += 1
                summary["total_data_points"] += len(metric["values"])
            
            return dict(summary)


class ConnectionMonitor:
    """Monitors connection status to Sumo Logic APIs."""
    
    def __init__(self, check_interval: float = 60.0):
        """Initialize connection monitor.
        
        Args:
            check_interval: Interval between connection checks in seconds
        """
        self.check_interval = check_interval
        self._connection_status: Dict[str, Dict[str, Any]] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        
        logger.info(f"Initialized connection monitor with check_interval={check_interval}s")
    
    async def start_monitoring(self):
        """Start connection monitoring."""
        if self._monitoring_task and not self._monitoring_task.done():
            logger.warning("Connection monitoring is already running")
            return
        
        self._stop_event.clear()
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Started connection monitoring")
    
    async def stop_monitoring(self):
        """Stop connection monitoring."""
        self._stop_event.set()
        
        if self._monitoring_task:
            try:
                await asyncio.wait_for(self._monitoring_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Connection monitoring task did not stop gracefully")
                self._monitoring_task.cancel()
        
        logger.info("Stopped connection monitoring")
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                await self._check_all_connections()
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.check_interval
                )
            except asyncio.TimeoutError:
                # Expected timeout, continue monitoring
                continue
            except Exception as e:
                logger.error(f"Error in connection monitoring loop: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying
    
    async def _check_all_connections(self):
        """Check all registered connections."""
        # This would be implemented to check actual API endpoints
        # For now, we'll simulate connection checks
        pass
    
    async def register_connection(
        self,
        name: str,
        endpoint: str,
        check_func: Optional[Callable] = None
    ):
        """Register a connection to monitor.
        
        Args:
            name: Connection name
            endpoint: API endpoint URL
            check_func: Optional function to check connection health
        """
        async with self._lock:
            self._connection_status[name] = {
                "endpoint": endpoint,
                "check_func": check_func,
                "status": HealthStatus.UNKNOWN,
                "last_check": None,
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
                "total_checks": 0,
                "total_successes": 0,
                "total_failures": 0
            }
        
        logger.info(f"Registered connection '{name}' for monitoring")
    
    async def check_connection(self, name: str) -> HealthCheckResult:
        """Check a specific connection.
        
        Args:
            name: Connection name
            
        Returns:
            Health check result
        """
        start_time = time.time()
        
        async with self._lock:
            if name not in self._connection_status:
                return HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNKNOWN,
                    message="Connection not registered",
                    timestamp=datetime.utcnow(),
                    duration_ms=0
                )
            
            connection = self._connection_status[name]
        
        # Perform the actual check
        try:
            if connection["check_func"]:
                await connection["check_func"]()
            
            # Update success metrics
            async with self._lock:
                connection["status"] = HealthStatus.HEALTHY
                connection["last_check"] = datetime.utcnow()
                connection["last_success"] = datetime.utcnow()
                connection["consecutive_failures"] = 0
                connection["total_checks"] += 1
                connection["total_successes"] += 1
            
            duration_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                name=name,
                status=HealthStatus.HEALTHY,
                message="Connection successful",
                timestamp=datetime.utcnow(),
                duration_ms=duration_ms,
                details={
                    "endpoint": connection["endpoint"],
                    "consecutive_failures": 0
                }
            )
            
        except Exception as e:
            # Update failure metrics
            async with self._lock:
                connection["last_check"] = datetime.utcnow()
                connection["last_failure"] = datetime.utcnow()
                connection["consecutive_failures"] += 1
                connection["total_checks"] += 1
                connection["total_failures"] += 1
                
                # Determine status based on consecutive failures
                if connection["consecutive_failures"] >= 3:
                    connection["status"] = HealthStatus.UNHEALTHY
                else:
                    connection["status"] = HealthStatus.DEGRADED
            
            duration_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                name=name,
                status=connection["status"],
                message=f"Connection failed: {str(e)}",
                timestamp=datetime.utcnow(),
                duration_ms=duration_ms,
                details={
                    "endpoint": connection["endpoint"],
                    "consecutive_failures": connection["consecutive_failures"],
                    "error_type": type(e).__name__
                }
            )
    
    async def get_connection_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific connection.
        
        Args:
            name: Connection name
            
        Returns:
            Connection status or None if not found
        """
        async with self._lock:
            if name not in self._connection_status:
                return None
            
            connection = self._connection_status[name]
            return {
                "name": name,
                "endpoint": connection["endpoint"],
                "status": connection["status"].value,
                "last_check": connection["last_check"].isoformat() if connection["last_check"] else None,
                "last_success": connection["last_success"].isoformat() if connection["last_success"] else None,
                "last_failure": connection["last_failure"].isoformat() if connection["last_failure"] else None,
                "consecutive_failures": connection["consecutive_failures"],
                "total_checks": connection["total_checks"],
                "total_successes": connection["total_successes"],
                "total_failures": connection["total_failures"],
                "success_rate": (
                    connection["total_successes"] / connection["total_checks"]
                    if connection["total_checks"] > 0 else 0
                )
            }
    
    async def get_all_connections_status(self) -> Dict[str, Any]:
        """Get status of all connections.
        
        Returns:
            Status of all connections
        """
        async with self._lock:
            result = {}
            for name in self._connection_status:
                result[name] = await self.get_connection_status(name)
            return result


class HealthChecker:
    """Performs comprehensive health checks for the MCP server."""
    
    def __init__(self):
        """Initialize health checker."""
        self._health_checks: Dict[str, Callable] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._lock = asyncio.Lock()
        
        logger.info("Initialized health checker")
    
    async def register_health_check(
        self,
        name: str,
        check_func: Callable,
        description: str = ""
    ):
        """Register a health check function.
        
        Args:
            name: Health check name
            check_func: Async function that performs the check
            description: Description of what the check does
        """
        async with self._lock:
            self._health_checks[name] = {
                "func": check_func,
                "description": description
            }
        
        logger.info(f"Registered health check '{name}': {description}")
    
    async def run_health_check(self, name: str) -> HealthCheckResult:
        """Run a specific health check.
        
        Args:
            name: Health check name
            
        Returns:
            Health check result
        """
        start_time = time.time()
        
        async with self._lock:
            if name not in self._health_checks:
                return HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNKNOWN,
                    message="Health check not found",
                    timestamp=datetime.utcnow(),
                    duration_ms=0
                )
            
            check_info = self._health_checks[name]
        
        try:
            # Run the health check
            await check_info["func"]()
            
            duration_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                name=name,
                status=HealthStatus.HEALTHY,
                message="Health check passed",
                timestamp=datetime.utcnow(),
                duration_ms=duration_ms,
                details={"description": check_info["description"]}
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                timestamp=datetime.utcnow(),
                duration_ms=duration_ms,
                details={
                    "description": check_info["description"],
                    "error_type": type(e).__name__
                }
            )
        
        # Store the result
        async with self._lock:
            self._last_results[name] = result
        
        return result
    
    async def run_all_health_checks(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks.
        
        Returns:
            Dictionary of health check results
        """
        results = {}
        
        async with self._lock:
            check_names = list(self._health_checks.keys())
        
        # Run all checks concurrently
        tasks = [self.run_health_check(name) for name in check_names]
        check_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for name, result in zip(check_names, check_results):
            if isinstance(result, Exception):
                results[name] = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check error: {str(result)}",
                    timestamp=datetime.utcnow(),
                    duration_ms=0
                )
            else:
                results[name] = result
        
        return results
    
    async def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status.
        
        Returns:
            Overall health summary
        """
        results = await self.run_all_health_checks()
        
        if not results:
            return {
                "status": HealthStatus.UNKNOWN.value,
                "message": "No health checks configured",
                "timestamp": datetime.utcnow().isoformat(),
                "checks": {}
            }
        
        # Determine overall status
        statuses = [result.status for result in results.values()]
        
        if all(status == HealthStatus.HEALTHY for status in statuses):
            overall_status = HealthStatus.HEALTHY
            message = "All health checks passed"
        elif any(status == HealthStatus.UNHEALTHY for status in statuses):
            overall_status = HealthStatus.UNHEALTHY
            unhealthy_count = sum(1 for s in statuses if s == HealthStatus.UNHEALTHY)
            message = f"{unhealthy_count} health check(s) failed"
        else:
            overall_status = HealthStatus.DEGRADED
            degraded_count = sum(1 for s in statuses if s == HealthStatus.DEGRADED)
            message = f"{degraded_count} health check(s) degraded"
        
        return {
            "status": overall_status.value,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {name: result.to_dict() for name, result in results.items()},
            "summary": {
                "total": len(results),
                "healthy": sum(1 for s in statuses if s == HealthStatus.HEALTHY),
                "degraded": sum(1 for s in statuses if s == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for s in statuses if s == HealthStatus.UNHEALTHY),
                "unknown": sum(1 for s in statuses if s == HealthStatus.UNKNOWN)
            }
        }


class MonitoringManager:
    """Central manager for all monitoring functionality."""
    
    def __init__(self):
        """Initialize monitoring manager."""
        self.metrics_collector = MetricsCollector()
        self.connection_monitor = ConnectionMonitor()
        self.health_checker = HealthChecker()
        
        # Register default health checks
        asyncio.create_task(self._register_default_health_checks())
        
        logger.info("Initialized monitoring manager")
    
    async def _register_default_health_checks(self):
        """Register default health checks."""
        await self.health_checker.register_health_check(
            "metrics_collector",
            self._check_metrics_collector,
            "Check if metrics collector is functioning"
        )
        
        await self.health_checker.register_health_check(
            "connection_monitor",
            self._check_connection_monitor,
            "Check if connection monitor is functioning"
        )
    
    async def _check_metrics_collector(self):
        """Health check for metrics collector."""
        # Try to get metrics summary
        summary = await self.metrics_collector.get_metrics_summary()
        if not isinstance(summary, dict):
            raise SumoLogicError("Metrics collector returned invalid summary")
    
    async def _check_connection_monitor(self):
        """Health check for connection monitor."""
        # Check if connection monitor is responsive
        status = await self.connection_monitor.get_all_connections_status()
        if not isinstance(status, dict):
            raise SumoLogicError("Connection monitor returned invalid status")
    
    async def start(self):
        """Start all monitoring components."""
        await self.connection_monitor.start_monitoring()
        logger.info("Started monitoring manager")
    
    async def stop(self):
        """Stop all monitoring components."""
        await self.connection_monitor.stop_monitoring()
        logger.info("Stopped monitoring manager")
    
    async def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive monitoring status.
        
        Returns:
            Complete monitoring status including health, metrics, and connections
        """
        # Get all status information concurrently
        health_task = self.health_checker.get_overall_health()
        metrics_task = self.metrics_collector.get_metrics_summary()
        connections_task = self.connection_monitor.get_all_connections_status()
        
        health_status, metrics_summary, connections_status = await asyncio.gather(
            health_task, metrics_task, connections_task
        )
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health": health_status,
            "metrics": metrics_summary,
            "connections": connections_status,
            "monitoring": {
                "metrics_collector_active": True,
                "connection_monitor_active": (
                    self.connection_monitor._monitoring_task is not None and
                    not self.connection_monitor._monitoring_task.done()
                ),
                "health_checker_active": True
            }
        }