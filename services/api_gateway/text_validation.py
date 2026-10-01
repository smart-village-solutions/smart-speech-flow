"""Text input checks: length, encoding, spam and harmful content."""

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class TextValidationError(Exception):
    """Custom exception for text validation errors"""

    pass


@dataclass
class TextSpecs:
    """Text specification requirements"""

    MAX_LENGTH: int = 500  # Maximum 500 characters
    MIN_LENGTH: int = 1  # Minimum 1 character
    ALLOWED_ENCODINGS: Optional[List[str]] = None  # UTF-8 primary

    def __post_init__(self) -> None:
        if self.ALLOWED_ENCODINGS is None:
            self.ALLOWED_ENCODINGS = ["utf-8"]


@dataclass
class TextValidationResult:
    """Result of text validation"""

    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    # Text properties
    length: Optional[int] = None
    encoding: Optional[str] = None
    contains_spam: Optional[bool] = None
    contains_harmful_content: Optional[bool] = None
    validation_time_ms: Optional[int] = None
    normalized_text: Optional[str] = None


def validate_text_input(
    text: object, enable_content_filtering: bool = True
) -> TextValidationResult:
    """
    Comprehensive text validation and content filtering

    Validates:
    - Text length (1-500 characters)
    - UTF-8 encoding
    - Spam detection
    - Harmful content filtering

    Args:
        text: Input to validate; anything but a string is refused as INVALID_TYPE
        enable_content_filtering: Whether to apply content filtering

    Returns:
        TextValidationResult with validation status and details
    """
    start_time = time.perf_counter()
    specs = TextSpecs()

    # Step 1: Basic validation
    if not isinstance(text, str):
        return TextValidationResult(
            is_valid=False,
            error_code="INVALID_TYPE",
            error_message="Input must be a string",
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 2: Length validation
    text_length = len(text)
    if text_length < specs.MIN_LENGTH:
        return TextValidationResult(
            is_valid=False,
            error_code="TEXT_TOO_SHORT",
            error_message=f"Text too short: {text_length} characters. Minimum: {specs.MIN_LENGTH}",
            details={"length": text_length, "min_length": specs.MIN_LENGTH},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    if text_length > specs.MAX_LENGTH:
        return TextValidationResult(
            is_valid=False,
            error_code="TEXT_TOO_LONG",
            error_message=f"Text too long: {text_length} characters. Maximum: {specs.MAX_LENGTH}",
            details={"length": text_length, "max_length": specs.MAX_LENGTH},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 3: Encoding validation
    try:
        text.encode("utf-8")
        encoding = "utf-8"
    except UnicodeEncodeError:
        return TextValidationResult(
            is_valid=False,
            error_code="INVALID_ENCODING",
            error_message="Text contains invalid UTF-8 characters",
            details={"encoding_error": "utf-8 encoding failed"},
            length=text_length,
            validation_time_ms=int((time.perf_counter() - start_time) * 1000),
        )

    # Step 4: Text normalization
    normalized_text = normalize_text(text)

    # Step 5: Content filtering (always detect, optionally block)
    contains_spam = detect_spam(normalized_text)
    contains_harmful_content = detect_harmful_content(normalized_text)

    if enable_content_filtering:
        if contains_spam:
            return TextValidationResult(
                is_valid=False,
                error_code="SPAM_DETECTED",
                error_message="Text appears to be spam",
                details={"spam_patterns": "multiple repetitive patterns detected"},
                length=text_length,
                encoding=encoding,
                contains_spam=True,
                normalized_text=normalized_text,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

        if contains_harmful_content:
            return TextValidationResult(
                is_valid=False,
                error_code="HARMFUL_CONTENT",
                error_message="Text contains potentially harmful content",
                details={"content_filter": "harmful patterns detected"},
                length=text_length,
                encoding=encoding,
                contains_harmful_content=True,
                normalized_text=normalized_text,
                validation_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    # Step 6: Success
    return TextValidationResult(
        is_valid=True,
        length=text_length,
        encoding=encoding,
        contains_spam=contains_spam,
        contains_harmful_content=contains_harmful_content,
        normalized_text=normalized_text,
        validation_time_ms=int((time.perf_counter() - start_time) * 1000),
    )


def normalize_text(text: str) -> str:
    """
    Normalize text for processing

    - Strip whitespace
    - Normalize unicode characters
    - Remove excessive whitespace
    """
    # Strip leading/trailing whitespace
    text = text.strip()

    # Normalize unicode (NFC - canonical composition)
    text = unicodedata.normalize("NFC", text)

    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)

    return text


def detect_spam(text: str) -> bool:
    """
    Simple spam detection

    Detects:
    - Excessive repetition
    - ALL CAPS text
    - Common spam patterns
    """
    # Check for excessive repetition
    words = text.lower().split()
    if len(words) > 3 and len(set(words)) < len(words) * 0.5:
        return True

    # Check for excessive caps (more than 60% uppercase letters)
    letter_chars = [c for c in text if c.isalpha()]
    if len(letter_chars) > 10:
        caps_ratio = len([c for c in letter_chars if c.isupper()]) / len(letter_chars)
        if caps_ratio > 0.6:
            return True

    # Check for common spam patterns
    spam_patterns = [
        r"(.)\1{4,}",  # Same character repeated 5+ times
        r"(..)\1{3,}",  # Same 2-char pattern repeated 4+ times
        r"(?i)(buy now|click here|free money|act now).*\1",  # Common spam phrases repeated
        r"!!!.*!!!.*!!!",  # Multiple exclamation patterns
    ]

    for pattern in spam_patterns:
        if re.search(pattern, text):
            return True

    return False


def detect_harmful_content(text: str) -> bool:
    """
    Basic harmful content detection

    Note: This is a simple implementation.
    In production, use dedicated content moderation APIs.
    """
    # Simple keyword-based filtering
    harmful_patterns = [
        r"(?i)(hate|kill|die|death)\s+(all|every)",
        r"(?i)(bomb|weapon|terror|attack)\s+(plan|how to|instructions|making)",
        r"(?i)(suicide|self\s*harm|hurt\s*myself)",
    ]

    for pattern in harmful_patterns:
        if re.search(pattern, text):
            return True

    return False
