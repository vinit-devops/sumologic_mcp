"""Authentication manager for Sumo Logic MCP server."""

import asyncio
import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from .config import SumoLogicConfig
from .exceptions import AuthenticationError, APIError, ConfigurationError, TimeoutError


logger = logging.getLogger(__name__)


class AuthSession(BaseModel):
    """Model for authentication session data."""
    
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    session_id: Optional[str] = None
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True


class SumoLogicAuth:
    """Handles Sumo Logic authentication and session management.
    
    This class manages authentication with Sumo Logic APIs using access ID/key
    credentials and handles session management including token refresh.
    
    Attributes:
        config: Sumo Logic configuration containing credentials and settings
        session: Current authentication session data
        http_client: HTTP client for making authentication requests
    """
    
    def __init__(self, config: SumoLogicConfig):
        """Initialize authentication manager with configuration.
        
        Args:
            config: SumoLogic configuration containing credentials and settings
            
        Raises:
            ConfigurationError: If required credentials are missing or invalid
        """
        self.config = config
        self.session = AuthSession()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._auth_lock = asyncio.Lock()
        
        # Validate credentials on initialization
        self._validate_credentials()
        
        logger.info(
            "Initialized SumoLogic authentication manager",
            extra={
                "endpoint": self.config.endpoint,
                "access_id": self.config.access_id[:8] + "..." if self.config.access_id else None
            }
        )
    
    def _validate_credentials(self) -> None:
        """Validate that required credentials are provided.
        
        Raises:
            ConfigurationError: If credentials are missing or invalid
        """
        if not self.config.access_id:
            raise ConfigurationError(
                "Sumo Logic Access ID is required",
                config_key="access_id"
            )
        
        if not self.config.access_key:
            raise ConfigurationError(
                "Sumo Logic Access Key is required", 
                config_key="access_key"
            )
        
        if not self.config.endpoint:
            raise ConfigurationError(
                "Sumo Logic API endpoint is required",
                config_key="endpoint"
            )
        
        # Validate endpoint format
        try:
            parsed = urlparse(self.config.endpoint)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL format")
            if not parsed.netloc.endswith('.sumologic.com'):
                raise ValueError("Must be a Sumo Logic domain")
        except Exception as e:
            raise ConfigurationError(
                f"Invalid Sumo Logic endpoint: {e}",
                config_key="endpoint",
                config_value=self.config.endpoint
            )
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for authentication requests.
        
        Returns:
            Configured HTTP client instance
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                headers={
                    "User-Agent": f"sumologic-mcp-server/{self.config.server_version}",
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            )
        return self._http_client
    
    async def authenticate(self) -> bool:
        """Authenticate with Sumo Logic and establish session.
        
        This method performs initial authentication using access ID/key credentials
        and detects the correct API endpoint if needed.
        
        Returns:
            True if authentication successful, False otherwise
            
        Raises:
            AuthenticationError: If authentication fails
            APIError: If API communication fails
            TimeoutError: If authentication request times out
        """
        async with self._auth_lock:
            try:
                logger.info("Starting Sumo Logic authentication")
                
                # First, validate the endpoint by making a test request
                await self._validate_endpoint()
                
                # For access ID/key authentication, we use basic auth
                # Sumo Logic doesn't use traditional session tokens for API access
                # Instead, we validate the credentials and store them for use
                auth_headers = self._create_basic_auth_headers()
                
                # Test authentication by making a simple API call
                test_url = f"{self.config.endpoint}/api/v1/collectors"
                
                try:
                    response = await self.http_client.get(
                        test_url,
                        headers=auth_headers,
                        timeout=self.config.timeout
                    )
                    
                    if response.status_code == 401:
                        raise AuthenticationError(
                            "Invalid Sumo Logic credentials",
                            auth_type="access_key",
                            context={
                                "status_code": response.status_code,
                                "access_id": self.config.access_id[:8] + "..." if self.config.access_id else None
                            }
                        )
                    elif response.status_code == 403:
                        raise AuthenticationError(
                            "Access denied - insufficient permissions",
                            auth_type="access_key", 
                            context={
                                "status_code": response.status_code,
                                "access_id": self.config.access_id[:8] + "..." if self.config.access_id else None
                            }
                        )
                    elif not response.is_success:
                        raise APIError(
                            f"Authentication test failed: {response.text}",
                            status_code=response.status_code,
                            response_body=response.text
                        )
                    
                    # Authentication successful - store session info
                    self.session = AuthSession(
                        expires_at=datetime.utcnow() + timedelta(hours=24),  # Assume 24h validity
                        session_id=f"auth_{datetime.utcnow().isoformat()}"
                    )
                    
                    logger.info(
                        "Sumo Logic authentication successful",
                        extra={
                            "session_id": self.session.session_id,
                            "expires_at": self.session.expires_at.isoformat() if self.session.expires_at else None
                        }
                    )
                    
                    return True
                    
                except httpx.TimeoutException as e:
                    raise TimeoutError(
                        f"Authentication request timed out after {self.config.timeout} seconds",
                        timeout_seconds=self.config.timeout,
                        operation="authenticate"
                    ) from e
                except httpx.RequestError as e:
                    raise APIError(
                        f"Failed to connect to Sumo Logic API: {e}",
                        context={"endpoint": self.config.endpoint}
                    ) from e
                    
            except (AuthenticationError, APIError, TimeoutError):
                # Re-raise our custom exceptions
                raise
            except Exception as e:
                logger.error(f"Unexpected error during authentication: {e}")
                raise AuthenticationError(
                    f"Authentication failed due to unexpected error: {e}",
                    context={"error_type": type(e).__name__}
                ) from e
    
    async def _validate_endpoint(self) -> None:
        """Validate that the API endpoint is reachable.
        
        Raises:
            APIError: If endpoint is not reachable
            TimeoutError: If endpoint validation times out
        """
        try:
            # Make a simple HEAD request to check endpoint availability
            response = await self.http_client.head(
                self.config.endpoint,
                timeout=self.config.timeout
            )
            
            # We expect some response, even if it's an auth error
            # A connection error or timeout would raise an exception
            logger.debug(f"Endpoint validation response: {response.status_code}")
            
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Endpoint validation timed out after {self.config.timeout} seconds",
                timeout_seconds=self.config.timeout,
                operation="validate_endpoint"
            ) from e
        except httpx.RequestError as e:
            raise APIError(
                f"Cannot reach Sumo Logic endpoint: {e}",
                context={"endpoint": self.config.endpoint}
            ) from e
    
    def _create_basic_auth_headers(self) -> Dict[str, str]:
        """Create basic authentication headers.
        
        Returns:
            Dictionary containing authorization headers
        """
        # Create basic auth string
        auth_string = f"{self.config.access_id}:{self.config.access_key}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        return {
            "Authorization": f"Basic {auth_b64}",
            "User-Agent": f"sumologic-mcp-server/{self.config.server_version}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests.
        
        This method returns the headers needed to authenticate API requests.
        It will refresh the session if needed.
        
        Returns:
            Dictionary containing authentication headers
            
        Raises:
            AuthenticationError: If authentication is not valid and refresh fails
        """
        # Check if we need to refresh authentication
        if await self._needs_refresh():
            await self.refresh_session()
        
        return self._create_basic_auth_headers()
    
    async def _needs_refresh(self) -> bool:
        """Check if authentication session needs refresh.
        
        Returns:
            True if session needs refresh, False otherwise
        """
        if not self.session.expires_at:
            return True
        
        # Refresh if expiring within 5 minutes
        refresh_threshold = datetime.utcnow() + timedelta(minutes=5)
        return self.session.expires_at <= refresh_threshold
    
    async def refresh_session(self) -> bool:
        """Refresh authentication session if needed.
        
        For Sumo Logic access ID/key authentication, this mainly involves
        re-validating the credentials and updating the session timestamp.
        
        Returns:
            True if refresh successful, False otherwise
            
        Raises:
            AuthenticationError: If session refresh fails
        """
        async with self._auth_lock:
            try:
                logger.info("Refreshing Sumo Logic authentication session")
                
                # For access ID/key auth, we just need to re-validate
                # by making a test API call
                auth_headers = self._create_basic_auth_headers()
                test_url = f"{self.config.endpoint}/api/v1/collectors"
                
                try:
                    response = await self.http_client.get(
                        test_url,
                        headers=auth_headers,
                        timeout=self.config.timeout
                    )
                    
                    if response.status_code == 401:
                        raise AuthenticationError(
                            "Session refresh failed - invalid credentials",
                            auth_type="access_key",
                            context={"status_code": response.status_code}
                        )
                    elif not response.is_success:
                        raise APIError(
                            f"Session refresh test failed: {response.text}",
                            status_code=response.status_code,
                            response_body=response.text
                        )
                    
                    # Update session expiry
                    self.session.expires_at = datetime.utcnow() + timedelta(hours=24)
                    self.session.session_id = f"refresh_{datetime.utcnow().isoformat()}"
                    
                    logger.info(
                        "Authentication session refreshed successfully",
                        extra={
                            "session_id": self.session.session_id,
                            "expires_at": self.session.expires_at.isoformat()
                        }
                    )
                    
                    return True
                    
                except httpx.TimeoutException as e:
                    raise TimeoutError(
                        f"Session refresh timed out after {self.config.timeout} seconds",
                        timeout_seconds=self.config.timeout,
                        operation="refresh_session"
                    ) from e
                except httpx.RequestError as e:
                    raise APIError(
                        f"Failed to refresh session: {e}",
                        context={"endpoint": self.config.endpoint}
                    ) from e
                    
            except (AuthenticationError, APIError, TimeoutError):
                # Re-raise our custom exceptions
                raise
            except Exception as e:
                logger.error(f"Unexpected error during session refresh: {e}")
                raise AuthenticationError(
                    f"Session refresh failed due to unexpected error: {e}",
                    context={"error_type": type(e).__name__}
                ) from e
    
    async def is_authenticated(self) -> bool:
        """Check if currently authenticated.
        
        Returns:
            True if authenticated and session is valid, False otherwise
        """
        if not self.session.expires_at:
            return False
        
        return datetime.utcnow() < self.session.expires_at
    
    async def logout(self) -> None:
        """Logout and clear authentication session.
        
        This clears the current session data and closes the HTTP client.
        """
        logger.info("Logging out of Sumo Logic session")
        
        # Clear session data
        self.session = AuthSession()
        
        # Close HTTP client if it exists
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        
        logger.info("Logout completed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.authenticate()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.logout()