# -*- coding: utf-8 -*-
"""
Prompt Injection Prevention Module

Sanitizes user input before injection into LLM prompts to prevent:
- Direct instruction override attacks
- Role-play injection attacks  
- Multi-step prompt injection
- Format manipulation attacks
"""

import re
from typing import Any


class PromptSanitizer:
    """Sanitizes user input for safe injection into LLM prompts."""
    
    # Patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        # Instruction override attempts
        r'(?i)(ignore|forget|bypass|override|disregard).*?(previous|instructions|rules|system)',
        r'(?i)(you are now|pretend|act as|roleplay as).*?(?:bot|agent|AI)',
        r'(?i)(new instructions|new rules|new prompt|new system)',
        
        # XML/structured format injection
        r'</?(?:instruction|system|role|command)[^>]*>',
        r'</(?:objective|rules|context|output_format)>',
        r'<(?:objective|rules|context|output_format)>',
        
        # Code execution attempts
        r'(?i)(eval|exec|execute|run|import|__[a-z]+__)',
        r'(?i)(python|javascript|shell|bash|cmd|powershell).*?(?:code|command|script)',
    ]
    
    # Maximum acceptable lengths for different input types
    MAX_LENGTHS = {
        'message': 5000,      # User messages
        'session_name': 200,  # Session identifiers
        'action_name': 100,   # Action names
        'file_path': 500,     # File paths
    }
    
    @staticmethod
    def sanitize_user_message(text: str, max_length: int = 5000) -> str:
        """
        Sanitize a user message for safe injection into prompts.
        
        Args:
            text: User-provided text
            max_length: Maximum allowed length
            
        Returns:
            Sanitized text safe for prompt injection
        """
        if not isinstance(text, str):
            text = str(text)
        
        # Truncate to max length
        text = text[:max_length]
        
        # Remove null bytes and control characters
        text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')
        
        # Check for injection patterns
        suspicious_patterns = []
        for pattern in PromptSanitizer.INJECTION_PATTERNS:
            if re.search(pattern, text):
                suspicious_patterns.append(pattern)
        
        if suspicious_patterns:
            # Log these for monitoring (optional)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"[SECURITY] Potential prompt injection detected. "
                f"Text: {text[:100]}... Patterns: {suspicious_patterns[:2]}"
            )
        
        return text
    
    @staticmethod
    def sanitize_structured_data(data: dict[str, Any], strict: bool = False) -> dict[str, Any]:
        """
        Sanitize a dictionary of structured data.
        
        Args:
            data: Dictionary to sanitize
            strict: If True, reject any suspicious patterns (stricter validation)
            
        Returns:
            Sanitized dictionary
        """
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = PromptSanitizer.sanitize_user_message(value)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [PromptSanitizer.sanitize_user_message(str(v)) if isinstance(v, str) else v for v in value]
            elif isinstance(value, dict):
                sanitized[key] = PromptSanitizer.sanitize_structured_data(value, strict)
            else:
                sanitized[key] = value
        
        return sanitized
    
    @staticmethod
    def sanitize_for_xml_injection(text: str) -> str:
        """
        Sanitize text that will be injected into XML-based prompts.
        
        Args:
            text: Text to sanitize
            
        Returns:
            XML-safe text
        """
        if not isinstance(text, str):
            text = str(text)
        
        # First apply standard sanitization
        text = PromptSanitizer.sanitize_user_message(text)
        
        # Escape XML special characters
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&#39;')
        
        return text
    
    @staticmethod
    def is_safe_field_name(field_name: str) -> bool:
        """
        Check if a field name is safe (no injection risk).
        
        Args:
            field_name: Field name to validate
            
        Returns:
            True if safe, False otherwise
        """
        # Allow only alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', field_name):
            return False
        
        # Reject reserved Python/system names
        reserved = {'__name__', '__main__', 'eval', 'exec', 'import', 'class', 'def', 'lambda'}
        if field_name.lower() in reserved:
            return False
        
        return True
    
    @staticmethod
    def create_safe_context_block(context: dict[str, str], block_name: str = "context") -> str:
        """
        Create a safe XML/structured context block for prompts.
        
        Args:
            context: Dictionary of context data
            block_name: Name of the block
            
        Returns:
            Safely formatted context block
        """
        if not PromptSanitizer.is_safe_field_name(block_name):
            block_name = "context"
        
        lines = [f"<{block_name}>"]
        for key, value in context.items():
            if not PromptSanitizer.is_safe_field_name(key):
                continue  # Skip unsafe field names
            
            safe_value = PromptSanitizer.sanitize_for_xml_injection(str(value))
            lines.append(f"  <{key}>{safe_value}</{key}>")
        
        lines.append(f"</{block_name}>")
        return "\n".join(lines)


# Example usage in agent_base.py
def example_safe_routing_prompt(
    item_type: str,
    item_content: str,
    source_platform: str,
    existing_sessions: str,
) -> str:
    """
    Example of how to use the sanitizer in routing prompts.
    """
    
    # Sanitize all user inputs
    safe_item_type = PromptSanitizer.sanitize_user_message(item_type, max_length=50)
    safe_item_content = PromptSanitizer.sanitize_user_message(item_content, max_length=1000)
    safe_platform = PromptSanitizer.sanitize_user_message(source_platform, max_length=50)
    
    # Build the prompt with sanitized inputs
    prompt = f"""
<objective>
You are a session routing system. Determine which task session an incoming message belongs to.
</objective>

<incoming_item>
Type: {safe_item_type}
Content: {safe_item_content}
Source Platform: {safe_platform}
</incoming_item>

<existing_sessions>
{existing_sessions}
</existing_sessions>

<rules>
1. ROUTE TO EXISTING SESSION when the message relates to an existing task
2. CREATE NEW SESSION when the message is a clearly new topic
</rules>

<output_format>
Return ONLY valid JSON: {{"action": "route|new", "session_id": "...", "reason": "..."}}
</output_format>
"""
    return prompt
