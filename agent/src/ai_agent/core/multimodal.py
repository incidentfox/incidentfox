"""
Multimodal message handling for agent API.

Parses messages containing embedded images and converts them to
the format expected by OpenAI's multimodal models.

The CLI embeds images using:
    <image src="data:image/png;base64,..." />

This module converts that to OpenAI's format:
    [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
"""

import re
from typing import Union

# Pattern to match embedded images
# Supports: <image src="data:image/png;base64,..." />
IMAGE_PATTERN = re.compile(
    r'<image\s+src="(data:image/[^;]+;base64,[^"]+)"\s*/?>',
    re.IGNORECASE | re.DOTALL,
)


def has_embedded_images(message: str) -> bool:
    """
    Check if a message contains embedded images.

    Args:
        message: The message string to check

    Returns:
        True if the message contains <image> tags
    """
    return bool(IMAGE_PATTERN.search(message))


def parse_multimodal_message(message: str) -> Union[str, list]:
    """
    Parse a message and convert embedded images to OpenAI format.

    If the message contains no images, returns it unchanged.
    If it contains images, returns a list of content items.

    Args:
        message: The message string, potentially containing <image> tags

    Returns:
        Either the original string (no images) or a list of content items
    """
    if not has_embedded_images(message):
        return message

    # Find all images and their positions
    content_items = []
    last_end = 0

    for match in IMAGE_PATTERN.finditer(message):
        # Add text before this image (if any)
        text_before = message[last_end : match.start()].strip()
        if text_before:
            content_items.append({"type": "text", "text": text_before})

        # Add the image
        image_url = match.group(1)
        content_items.append({"type": "image_url", "image_url": {"url": image_url}})

        last_end = match.end()

    # Add any remaining text after the last image
    text_after = message[last_end:].strip()
    if text_after:
        content_items.append({"type": "text", "text": text_after})

    # If we only have one text item and no images, return as string
    if len(content_items) == 1 and content_items[0]["type"] == "text":
        return content_items[0]["text"]

    # Ensure there's at least some text if we have images
    if content_items and all(item["type"] == "image_url" for item in content_items):
        content_items.insert(0, {"type": "text", "text": "Please analyze this image."})

    return content_items


def extract_image_count(message: str) -> int:
    """
    Count the number of embedded images in a message.

    Args:
        message: The message string

    Returns:
        Number of embedded images
    """
    return len(IMAGE_PATTERN.findall(message))


def strip_images_from_message(message: str) -> str:
    """
    Remove all embedded images from a message, leaving only text.

    Useful for logging or displaying messages without image data.

    Args:
        message: The message string

    Returns:
        Message with <image> tags replaced by [IMAGE]
    """
    return IMAGE_PATTERN.sub("[IMAGE]", message)


def get_message_preview(message: Union[str, list], max_length: int = 100) -> str:
    """
    Get a preview of a message for logging.

    Handles both string and multimodal list formats.

    Args:
        message: String or list of content items
        max_length: Maximum preview length

    Returns:
        Truncated preview string
    """
    if isinstance(message, str):
        # Strip images and truncate
        preview = strip_images_from_message(message)
    elif isinstance(message, list):
        # Extract text parts
        text_parts = [
            item.get("text", "")
            for item in message
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        image_count = sum(
            1
            for item in message
            if isinstance(item, dict) and item.get("type") == "image_url"
        )
        preview = " ".join(text_parts)
        if image_count:
            preview += f" [+{image_count} image(s)]"
    else:
        preview = str(message)

    if len(preview) > max_length:
        preview = preview[: max_length - 3] + "..."

    return preview
