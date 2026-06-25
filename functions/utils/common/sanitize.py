import re

def sanitize_for_prompt(text: str, max_chars: int = 40_000) -> str:
    """
    Sanitizes arbitrary text content before injection into LLM prompts.
    
    Performs:
      1. Truncation to max_chars to keep tokens safe.
      2. Redaction of prompt instruction boundary markers (e.g. '---', '===', '\"\"\"', \"'''\").
    """
    if not text:
        return ""
    
    # 1. Truncate
    truncated = text[:max_chars]
    
    # 2. Redact potential boundary markers and injection dividers
    # Replaces common prompt injection wrappers with a safe placeholder
    redacted = re.sub(r'[-=]{3,}', '[DELETED_SEPARATOR]', truncated)
    redacted = redacted.replace('"""', '[DELETED_QUOTE]')
    redacted = redacted.replace("'''", '[DELETED_QUOTE]')
    
    return redacted

def read_file_content(file_path):
    """Utility to read text from files (prompts, schemas, JSON mockups)."""
    with open(file_path, "r") as f:
        return f.read()

