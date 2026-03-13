# -*- coding: utf-8 -*-
"""
Secure Error Handling Module

Provides safe error handling that:
- Prevents information disclosure via tracebacks
- Logs full details internally for debugging
- Returns sanitized errors to users
"""

import logging
import traceback
import sys
from typing import Optional, Tuple


class SecureErrorHandler:
    """Handles errors securely without exposing sensitive information."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    @staticmethod
    def sanitize_error_message(error: Exception, max_length: int = 200) -> str:
        """
        Sanitize error message to prevent information disclosure.
        
        Args:
            error: The exception to sanitize
            max_length: Maximum returned message length
            
        Returns:
            Safe, user-friendly error message
        """
        error_str = str(error)
        
        # Remove sensitive patterns
        sensitive_patterns = [
            r'/[^/\s]+\.py',  # File paths
            r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)',  # Email addresses
            r'(:\/\/[^/\s]+)',  # URLs/hostnames
            r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})',  # IP addresses
        ]
        
        import re
        for pattern in sensitive_patterns:
            error_str = re.sub(pattern, '[REDACTED]', error_str)
        
        # Truncate to max length
        if len(error_str) > max_length:
            error_str = error_str[:max_length] + "..."
        
        return error_str
    
    def handle_exception(
        self,
        exc: Exception,
        context: str = "Unknown operation",
        log_traceback: bool = True
    ) -> str:
        """
        Handle exception securely.
        
        Args:
            exc: The exception to handle
            context: Description of what was being done
            log_traceback: Whether to log full traceback internally
            
        Returns:
            Safe error message for user
        """
        # Log full details internally (for debugging)
        if log_traceback:
            self.logger.error(f"[ERROR] {context}")
            self.logger.error(f"Exception: {type(exc).__name__}: {exc}")
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(traceback.format_exc())
        else:
            self.logger.error(f"[ERROR] {context}: {type(exc).__name__}")
        
        # Return sanitized message to user
        safe_message = self.sanitize_error_message(exc)
        return safe_message
    
    def safe_execute(
        self,
        func,
        *args,
        context: str = "Executing operation",
        **kwargs
    ) -> Tuple[Optional[any], Optional[str]]:
        """
        Safely execute a function with error handling.
        
        Args:
            func: Function to execute
            *args: Arguments to pass
            context: Description of operation
            **kwargs: Keyword arguments to pass
            
        Returns:
            Tuple of (result, error_message)
            - If successful: (result, None)
            - If error: (None, error_message)
        """
        try:
            result = func(*args, **kwargs)
            return result, None
        except Exception as e:
            error_msg = self.handle_exception(e, context=context)
            return None, error_msg


def setup_secure_exception_hook():
    """
    Install a global exception hook that prevents traceback disclosure.
    Call this at application startup.
    """
    def secure_excepthook(exc_type, exc_value, exc_traceback):
        """Global exception handler."""
        # Log full traceback internally
        logger = logging.getLogger("UNCAUGHT_EXCEPTION")
        logger.error(
            f"Uncaught exception: {exc_type.__name__}: {exc_value}",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # Print sanitized message to user
        error_handler = SecureErrorHandler(logger)
        safe_msg = error_handler.sanitize_error_message(exc_value)
        
        print(f"\n❌ An error occurred: {safe_msg}", file=sys.stderr)
        
        # Exit gracefully
        sys.exit(1)
    
    sys.excepthook = secure_excepthook
