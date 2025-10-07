"""Resilience patterns for Sumo Logic MCP server.

This module implements retry logic, circuit breaker patterns, and other resilience
mechanisms to handle transient failures and improve system reliability.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Type, Union, List
from datetime import datetime, timedelta

from .exceptions import APIError, RateLimitError, TimeoutError, SumoLogicError


logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (
        APIError, RateLimitError, TimeoutError, ConnectionError, OSError
    )
    
    def __post_init__(self):
        """Validate retry configuration."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if self.exponential_base < 1:
            raise ValueError("exponential_base must be >= 1")


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: Type[Exception] = Exception
    success_threshold: int = 3  # Successes needed in half-open to close
    
    def __post_init__(self):
        """Validate circuit breaker configuration."""
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.recovery_timeout < 0:
            raise ValueError("recovery_timeout must be non-negative")
        if self.success_threshold < 1:
            raise ValueError("success_threshold must be at least 1")


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    state_changes: List[Dict[str, Any]] = field(default_factory=list)
    
    def record_success(self):
        """Record a successful operation."""
        self.success_count += 1
        self.total_successes += 1
        self.total_requests += 1
        self.last_success_time = datetime.utcnow()
    
    def record_failure(self):
        """Record a failed operation."""
        self.failure_count += 1
        self.total_failures += 1
        self.total_requests += 1
        self.last_failure_time = datetime.utcnow()
    
    def record_state_change(self, old_state: CircuitState, new_state: CircuitState, reason: str):
        """Record a state change."""
        self.state_changes.append({
            "timestamp": datetime.utcnow().isoformat(),
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason
        })
    
    def get_failure_rate(self) -> float:
        """Calculate failure rate."""
        if self.total_requests == 0:
            return 0.0
        return self.total_failures / self.total_requests
    
    def get_recent_failure_rate(self, window_minutes: int = 5) -> float:
        """Calculate failure rate in recent time window."""
        # This is a simplified implementation
        # In production, you'd want to track time-windowed metrics
        return self.get_failure_rate()


class CircuitBreakerError(SumoLogicError):
    """Raised when circuit breaker is open."""
    
    def __init__(self, message: str, circuit_name: str, state: CircuitState):
        super().__init__(message)
        self.circuit_name = circuit_name
        self.state = state


class CircuitBreaker:
    """Circuit breaker implementation for handling persistent failures."""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        """Initialize circuit breaker.
        
        Args:
            name: Name of the circuit breaker for logging/monitoring
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized circuit breaker '{name}'",
            extra={
                "failure_threshold": config.failure_threshold,
                "recovery_timeout": config.recovery_timeout,
                "success_threshold": config.success_threshold
            }
        )
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Any exception raised by the function
        """
        async with self._lock:
            # Check if circuit should transition states
            await self._check_state_transition()
            
            # Fail fast if circuit is open
            if self.stats.state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is open",
                    circuit_name=self.name,
                    state=self.stats.state
                )
        
        # Execute function
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Record success
            async with self._lock:
                await self._record_success()
            
            return result
            
        except self.config.expected_exception as e:
            # Record failure
            async with self._lock:
                await self._record_failure()
            raise
    
    async def _check_state_transition(self):
        """Check if circuit breaker should transition states."""
        current_time = datetime.utcnow()
        
        if self.stats.state == CircuitState.CLOSED:
            # Check if we should open the circuit
            if self.stats.failure_count >= self.config.failure_threshold:
                await self._transition_to_open("Failure threshold exceeded")
        
        elif self.stats.state == CircuitState.OPEN:
            # Check if we should try half-open
            if (self.stats.last_failure_time and 
                current_time - self.stats.last_failure_time >= 
                timedelta(seconds=self.config.recovery_timeout)):
                await self._transition_to_half_open("Recovery timeout elapsed")
        
        elif self.stats.state == CircuitState.HALF_OPEN:
            # Check if we should close or open
            if self.stats.success_count >= self.config.success_threshold:
                await self._transition_to_closed("Success threshold met")
            elif self.stats.failure_count > 0:
                await self._transition_to_open("Failure in half-open state")
    
    async def _record_success(self):
        """Record successful operation."""
        self.stats.record_success()
        
        logger.debug(
            f"Circuit breaker '{self.name}' recorded success",
            extra={
                "state": self.stats.state.value,
                "success_count": self.stats.success_count,
                "failure_count": self.stats.failure_count
            }
        )
    
    async def _record_failure(self):
        """Record failed operation."""
        self.stats.record_failure()
        
        logger.warning(
            f"Circuit breaker '{self.name}' recorded failure",
            extra={
                "state": self.stats.state.value,
                "success_count": self.stats.success_count,
                "failure_count": self.stats.failure_count
            }
        )
    
    async def _transition_to_open(self, reason: str):
        """Transition circuit to open state."""
        old_state = self.stats.state
        self.stats.state = CircuitState.OPEN
        self.stats.record_state_change(old_state, CircuitState.OPEN, reason)
        
        logger.error(
            f"Circuit breaker '{self.name}' opened",
            extra={
                "reason": reason,
                "failure_count": self.stats.failure_count,
                "total_failures": self.stats.total_failures
            }
        )
    
    async def _transition_to_half_open(self, reason: str):
        """Transition circuit to half-open state."""
        old_state = self.stats.state
        self.stats.state = CircuitState.HALF_OPEN
        self.stats.success_count = 0
        self.stats.failure_count = 0
        self.stats.record_state_change(old_state, CircuitState.HALF_OPEN, reason)
        
        logger.info(
            f"Circuit breaker '{self.name}' half-opened",
            extra={"reason": reason}
        )
    
    async def _transition_to_closed(self, reason: str):
        """Transition circuit to closed state."""
        old_state = self.stats.state
        self.stats.state = CircuitState.CLOSED
        self.stats.success_count = 0
        self.stats.failure_count = 0
        self.stats.record_state_change(old_state, CircuitState.CLOSED, reason)
        
        logger.info(
            f"Circuit breaker '{self.name}' closed",
            extra={"reason": reason}
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "success_count": self.stats.success_count,
            "total_requests": self.stats.total_requests,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "failure_rate": self.stats.get_failure_rate(),
            "last_failure_time": self.stats.last_failure_time.isoformat() if self.stats.last_failure_time else None,
            "last_success_time": self.stats.last_success_time.isoformat() if self.stats.last_success_time else None,
            "state_changes": self.stats.state_changes[-10:]  # Last 10 state changes
        }


class RetryableOperation:
    """Wrapper for operations that should be retried on failure."""
    
    def __init__(self, config: RetryConfig):
        """Initialize retryable operation.
        
        Args:
            config: Retry configuration
        """
        self.config = config
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with retry logic.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: Last exception if all retries fail
        """
        last_exception = None
        
        for attempt in range(self.config.max_attempts):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
                    
            except Exception as e:
                last_exception = e
                
                # Check if exception is retryable
                if not isinstance(e, self.config.retryable_exceptions):
                    logger.debug(
                        f"Exception {type(e).__name__} is not retryable, failing immediately"
                    )
                    raise
                
                # Don't retry on last attempt
                if attempt == self.config.max_attempts - 1:
                    break
                
                # Calculate delay with exponential backoff and jitter
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    f"Operation failed (attempt {attempt + 1}/{self.config.max_attempts}), "
                    f"retrying in {delay:.2f}s: {e}",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": self.config.max_attempts,
                        "delay": delay,
                        "exception_type": type(e).__name__
                    }
                )
                
                await asyncio.sleep(delay)
        
        # All retries failed
        logger.error(
            f"Operation failed after {self.config.max_attempts} attempts",
            extra={
                "max_attempts": self.config.max_attempts,
                "final_exception": str(last_exception)
            }
        )
        
        raise last_exception
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt.
        
        Args:
            attempt: Current attempt number (0-based)
            
        Returns:
            Delay in seconds
        """
        # Exponential backoff
        delay = self.config.base_delay * (self.config.exponential_base ** attempt)
        
        # Cap at max delay
        delay = min(delay, self.config.max_delay)
        
        # Add jitter to avoid thundering herd
        if self.config.jitter:
            import random
            jitter_range = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


class ResilientAPIClient:
    """Wrapper that adds resilience patterns to API operations."""
    
    def __init__(
        self,
        name: str,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None
    ):
        """Initialize resilient API client.
        
        Args:
            name: Name for logging and monitoring
            retry_config: Retry configuration (uses defaults if None)
            circuit_breaker_config: Circuit breaker configuration (uses defaults if None)
        """
        self.name = name
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        
        self.circuit_breaker = CircuitBreaker(name, self.circuit_breaker_config)
        self.retry_operation = RetryableOperation(self.retry_config)
        
        logger.info(
            f"Initialized resilient API client '{name}'",
            extra={
                "max_retry_attempts": self.retry_config.max_attempts,
                "circuit_breaker_threshold": self.circuit_breaker_config.failure_threshold
            }
        )
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with full resilience patterns.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: If operation fails after all resilience mechanisms
        """
        # Wrap function with retry logic
        async def retryable_func():
            return await self.retry_operation.execute(func, *args, **kwargs)
        
        # Execute with circuit breaker protection
        return await self.circuit_breaker.call(retryable_func)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the resilient client."""
        circuit_stats = self.circuit_breaker.get_stats()
        
        # Determine overall health
        health = "healthy"
        if circuit_stats["state"] == "open":
            health = "unhealthy"
        elif circuit_stats["state"] == "half_open":
            health = "degraded"
        elif circuit_stats["failure_rate"] > 0.5:  # More than 50% failure rate
            health = "degraded"
        
        return {
            "name": self.name,
            "health": health,
            "circuit_breaker": circuit_stats,
            "retry_config": {
                "max_attempts": self.retry_config.max_attempts,
                "base_delay": self.retry_config.base_delay,
                "max_delay": self.retry_config.max_delay
            }
        }


# Timeout handling utilities

class TimeoutManager:
    """Manager for handling configurable timeouts."""
    
    def __init__(self, default_timeout: float = 30.0):
        """Initialize timeout manager.
        
        Args:
            default_timeout: Default timeout in seconds
        """
        self.default_timeout = default_timeout
        self.operation_timeouts: Dict[str, float] = {}
    
    def set_timeout(self, operation: str, timeout: float):
        """Set timeout for specific operation.
        
        Args:
            operation: Operation name
            timeout: Timeout in seconds
        """
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        
        self.operation_timeouts[operation] = timeout
        logger.debug(f"Set timeout for '{operation}': {timeout}s")
    
    def get_timeout(self, operation: str) -> float:
        """Get timeout for operation.
        
        Args:
            operation: Operation name
            
        Returns:
            Timeout in seconds
        """
        return self.operation_timeouts.get(operation, self.default_timeout)
    
    async def execute_with_timeout(
        self,
        func: Callable,
        operation: str,
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """Execute function with timeout.
        
        Args:
            func: Function to execute
            operation: Operation name for timeout lookup
            *args: Positional arguments for function
            timeout: Override timeout (uses configured timeout if None)
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            TimeoutError: If operation times out
        """
        effective_timeout = timeout or self.get_timeout(operation)
        
        try:
            if asyncio.iscoroutinefunction(func):
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=effective_timeout
                )
            else:
                # For sync functions, run in executor with timeout
                loop = asyncio.get_event_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=effective_timeout
                )
                
        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"Operation '{operation}' timed out after {effective_timeout}s",
                timeout_seconds=effective_timeout,
                operation=operation
            ) from e