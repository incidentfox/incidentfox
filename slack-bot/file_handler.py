"""
Image upload/download and file attachment processing for Slack.

Handles base64 image encoding/decoding, Slack file uploads, image downloads
with thumbnail fallback (respecting Claude API's 5MB limit), and file
attachment metadata extraction from Slack events.
"""

import logging
import os

logger = logging.getLogger(__name__)

SRE_AGENT_URL = os.environ.get("SRE_AGENT_URL", "http://localhost:8000")


def _is_image_output(tool_output) -> bool:
    """
    Check if a tool output contains an image.

    SDK format: {'type': 'image', 'file': {'base64': '...'}}
    Alternative format: {'image': base64_data, 'mime_type': str}
    """
    import ast
    import json

    if not tool_output:
        return False

    # Try parsing as JSON or dict
    data = None
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        elif isinstance(tool_output, dict):
            data = tool_output
    except (json.JSONDecodeError, TypeError):
        try:
            if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
                data = ast.literal_eval(tool_output)
        except (ValueError, SyntaxError):
            pass

    if isinstance(data, dict):
        # SDK format: {'type': 'image', 'file': {'base64': '...'}}
        if data.get("type") == "image" and "file" in data:
            return True
        # Alternative format: {'image': base64_data, 'mime_type': str}
        if "image" in data and "mime_type" in data:
            return True

    return False


def _upload_image_to_slack(
    tool_output, client, channel_id: str, thread_ts: str, filename: str = "image"
) -> dict | None:
    """
    Upload a base64-encoded image from tool output to Slack.

    Args:
        tool_output: Tool output in one of these formats:
            - SDK format: {'type': 'image', 'file': {'base64': '...'}}
            - Alternative: {'image': base64, 'mime_type': str}
        client: Slack client
        channel_id: Channel to upload to (unused - we upload without channel for embedding)
        thread_ts: Thread timestamp (unused)
        filename: Name for the uploaded file

    Returns:
        Dict with 'file_id' and 'permalink_public' if successful, None otherwise
    """
    import ast
    import base64
    import json
    import os as temp_os
    import tempfile

    # Parse the output
    data = None
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        elif isinstance(tool_output, dict):
            data = tool_output
    except (json.JSONDecodeError, TypeError):
        try:
            if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
                data = ast.literal_eval(tool_output)
        except (ValueError, SyntaxError):
            pass

    if not data:
        logger.warning("Could not parse tool output as dict")
        return None

    # Extract base64 data and mime_type based on format
    base64_data = None
    mime_type = None

    # SDK format: {'type': 'image', 'file': {'base64': '...'}}
    if data.get("type") == "image" and "file" in data:
        file_info = data["file"]
        base64_data = file_info.get("base64")
        # SDK may not include mime_type, guess from filename or default to jpeg
        mime_type = file_info.get("mime_type") or data.get("mime_type")
        if not mime_type:
            # Guess from filename extension
            if filename.lower().endswith(".png"):
                mime_type = "image/png"
            elif filename.lower().endswith(".gif"):
                mime_type = "image/gif"
            elif filename.lower().endswith(".webp"):
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"  # Default
        logger.info(f"Detected SDK image format, mime_type={mime_type}")
    # Alternative format: {'image': base64, 'mime_type': str}
    elif "image" in data and "mime_type" in data:
        base64_data = data["image"]
        mime_type = data["mime_type"]
        logger.info(f"Detected alternative image format, mime_type={mime_type}")

    if not base64_data:
        logger.warning(
            f"Invalid image output format - could not extract base64 data. Keys: {list(data.keys())}"
        )
        return None

    try:
        # Decode base64 image
        image_data = base64.b64decode(base64_data)

        # Determine file extension
        ext = mime_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(image_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITHOUT channel - makes it embeddable via slack_file
            # We intentionally do NOT call files.sharedPublicURL to keep images private
            # (only accessible within the Slack workspace)
            response = client.files_upload_v2(
                file=tmp_path,
                filename=f"{filename}.{ext}",
                title=filename,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(f"Image uploaded to Slack (private): file_id={file_id}")
                return file_id
            else:
                logger.warning(f"Failed to upload image: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to Slack: {e}")
        return None


def _upload_base64_image_to_slack(
    client, image_data: str, filename: str, media_type: str
) -> str | None:
    """
    Upload a base64-encoded image to Slack and return the file ID.

    Args:
        client: Slack client
        image_data: Base64-encoded image data
        filename: Filename for the uploaded file
        media_type: MIME type (e.g., 'image/png')

    Returns:
        Slack file ID if successful, None otherwise
    """
    import base64
    import os as temp_os
    import tempfile

    try:
        # Decode base64 image
        decoded_data = base64.b64decode(image_data)

        # Determine file extension
        ext = media_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"

        # Ensure filename has correct extension
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(decoded_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITHOUT channel - makes it embeddable via slack_file
            response = client.files_upload_v2(
                file=tmp_path,
                filename=filename,
                title=filename,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(
                    f"Image uploaded to Slack: file_id={file_id}, filename={filename}"
                )
                return file_id
            else:
                logger.warning(f"Failed to upload image: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to Slack: {e}")
        return None


def _upload_base64_file_to_slack(
    client,
    file_data: str,
    filename: str,
    media_type: str,
    channel_id: str,
    thread_ts: str,
) -> str | None:
    """
    Upload a base64-encoded file to Slack and return the file ID.

    Unlike images (which are uploaded without a channel for embedding via slack_file),
    files are uploaded TO a channel/thread so they appear as attachments.

    Args:
        client: Slack client
        file_data: Base64-encoded file data
        filename: Filename for the uploaded file
        media_type: MIME type (e.g., 'text/csv')
        channel_id: Channel to upload to
        thread_ts: Thread timestamp to attach to

    Returns:
        Slack file ID if successful, None otherwise
    """
    import base64
    import os as temp_os
    import tempfile

    try:
        # Decode base64 file
        decoded_data = base64.b64decode(file_data)

        # Determine file extension from media type or filename
        ext = filename.split(".")[-1] if "." in filename else ""
        if not ext:
            # Try to guess from media type
            type_to_ext = {
                "text/csv": "csv",
                "text/plain": "txt",
                "application/json": "json",
                "application/pdf": "pdf",
                "application/zip": "zip",
            }
            ext = type_to_ext.get(media_type, "bin")

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(decoded_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITH channel - appears as attachment in thread
            response = client.files_upload_v2(
                file=tmp_path,
                filename=filename,
                title=filename,
                channel=channel_id,
                thread_ts=thread_ts,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(
                    f"File uploaded to Slack: file_id={file_id}, filename={filename}"
                )
                return file_id
            else:
                logger.warning(f"Failed to upload file: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading file to Slack: {e}")
        return None


def _get_image_extension(media_type: str) -> str:
    """Get file extension for a media type."""
    ext = media_type.split("/")[-1] if "/" in media_type else "png"
    if ext == "jpeg":
        ext = "jpg"
    return f".{ext}"


def _download_slack_image(
    file_info: dict, client, thumbnail_only: bool = False
) -> dict | None:
    """
    Download an image from Slack and return its content as base64.

    Enforces the Claude API's 5MB per-image limit. If the full-size image
    exceeds that, falls back to Slack's pre-generated thumbnails (1024 -> 720
    -> 480px) which are much smaller. Skips the image if even thumbnails
    are too large.

    Args:
        file_info: File object from Slack event
        client: Slack client
        thumbnail_only: If True, skip full-size and use thumbnails directly
            (useful for thread context images where full resolution isn't needed)

    Returns:
        dict with {data: base64_string, media_type: str, filename: str, size: int} or None
    """
    import base64

    import requests

    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Claude API limit: 5MB per image

    mimetype = file_info.get("mimetype", "")
    filename = file_info.get("name", "image")

    # Only handle images
    if not mimetype.startswith("image/"):
        return None

    # Build list of URLs to try
    urls_to_try = []

    if not thumbnail_only:
        url_private = file_info.get("url_private_download") or file_info.get(
            "url_private"
        )
        if url_private:
            urls_to_try.append(("full", url_private))

    # Slack provides pre-generated thumbnails at various sizes
    for thumb_key in ("thumb_1024", "thumb_720", "thumb_480"):
        thumb_url = file_info.get(thumb_key)
        if thumb_url:
            urls_to_try.append((thumb_key, thumb_url))

    # Fallback: if thumbnail_only but no thumbnails found, try full-size
    if thumbnail_only and not urls_to_try:
        url_private = file_info.get("url_private_download") or file_info.get(
            "url_private"
        )
        if url_private:
            logger.info(f"No thumbnails for {filename}, falling back to full-size")
            urls_to_try.append(("full", url_private))

    if not urls_to_try:
        logger.warning(
            f"No download URL for image: {filename} "
            f"(available keys: {sorted(file_info.keys())})"
        )
        return None

    auth_headers = {"Authorization": f"Bearer {client.token}"}

    for variant, url in urls_to_try:
        try:
            response = requests.get(url, headers=auth_headers, timeout=60)
            response.raise_for_status()

            if len(response.content) <= MAX_IMAGE_BYTES:
                image_data = base64.b64encode(response.content).decode("utf-8")
                if variant != "full":
                    logger.info(
                        f"Image {filename} exceeded 5MB, using {variant} thumbnail "
                        f"({len(response.content) / 1024 / 1024:.1f}MB)"
                    )
                return {
                    "data": image_data,
                    "media_type": mimetype,
                    "filename": filename,
                    "size": len(response.content),
                }
            else:
                logger.info(
                    f"Image {filename} ({variant}) is {len(response.content) / 1024 / 1024:.1f}MB, "
                    f"exceeds 5MB limit, trying smaller variant..."
                )
        except Exception as e:
            logger.warning(f"Failed to download image {filename} ({variant}): {e}")

    logger.warning(f"All variants of image {filename} exceed 5MB, skipping inline")
    return None


def _get_file_attachment_metadata(file_info: dict, client) -> dict | None:
    """
    Get metadata for a non-image file attachment.

    Instead of downloading the file (which could be huge), we return metadata
    that the sre-agent server will use to set up a proxy download.
    The actual download happens in the sandbox via the proxy pattern.

    Args:
        file_info: File object from Slack event
        client: Slack client

    Returns:
        dict with {filename, size, media_type, download_url, auth_header} or None
    """
    mimetype = file_info.get("mimetype", "")
    filename = file_info.get("name", "file")
    file_size = file_info.get("size", 0)

    # Skip images (handled separately)
    if mimetype.startswith("image/"):
        return None

    # Get the download URL
    url_private = file_info.get("url_private_download") or file_info.get("url_private")
    if not url_private:
        logger.warning(f"No download URL for file: {filename}")
        return None

    return {
        "filename": filename,
        "size": file_size,
        "media_type": mimetype,
        "download_url": url_private,
        "auth_header": f"Bearer {client.token}",
    }


def _extract_images_from_event(event: dict, client) -> list:
    """
    Extract all images from a Slack event.

    Images are downloaded and converted to base64 (they're typically small).

    Args:
        event: Slack event object
        client: Slack client

    Returns:
        List of image dicts: [{data: base64, media_type: str, filename: str}, ...]
    """
    images = []
    files = event.get("files", [])

    for file_info in files:
        image = _download_slack_image(file_info, client)
        if image:
            images.append(image)
            logger.info(
                f"Downloaded image: {image['filename']} ({image['size']} bytes)"
            )

    return images


def _extract_file_attachments_from_event(event: dict, client) -> list:
    """
    Extract metadata for all non-image file attachments from a Slack event.

    Instead of downloading files (which could be very large), we extract metadata
    that will be used by the sre-agent server to set up proxy downloads.
    Files are downloaded in the sandbox via the proxy pattern.

    Args:
        event: Slack event object
        client: Slack client

    Returns:
        List of file attachment metadata dicts:
        [{filename, size, media_type, download_url, auth_header}, ...]
    """
    attachments = []
    files = event.get("files", [])

    for file_info in files:
        attachment = _get_file_attachment_metadata(file_info, client)
        if attachment:
            attachments.append(attachment)
            logger.info(
                f"File attachment: {attachment['filename']} ({attachment['size']} bytes, {attachment['media_type']})"
            )

    return attachments
