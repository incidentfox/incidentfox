"""Google Docs and Drive integration tools."""

import json
import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_google_docs_config() -> dict:
    """Get Google Docs configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("google_docs")
        if config and (
            config.get("credentials_file") or config.get("service_account_key")
        ):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("GOOGLE_CREDENTIALS_FILE") or os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"):
        return {
            "credentials_file": os.getenv("GOOGLE_CREDENTIALS_FILE"),
            "service_account_key": os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="google_docs",
        tool_id="google_docs_tools",
        missing_fields=["credentials_file", "service_account_key"],
    )


def _get_google_docs_service(readonly: bool = False):
    """Get Google Docs API service."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        config = _get_google_docs_config()

        # Support both file path and JSON string
        creds_file = config.get("credentials_file")
        creds_json = config.get("service_account_key")

        if readonly:
            SCOPES = [
                "https://www.googleapis.com/auth/documents.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
        else:
            SCOPES = [
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive.file",
            ]

        if creds_json:
            # Load from JSON string
            creds_dict = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
        elif creds_file:
            # Load from file path
            creds = service_account.Credentials.from_service_account_file(
                creds_file, scopes=SCOPES
            )
        else:
            raise ValueError(
                "Neither credentials_file nor service_account_key is set in config"
            )

        return build("docs", "v1", credentials=creds), build(
            "drive", "v3", credentials=creds
        )

    except ImportError:
        raise ToolExecutionError("google", "google-api-python-client not installed")


def read_google_doc(document_id: str) -> dict[str, Any]:
    """
    Read content from a Google Doc.

    Args:
        document_id: Google Docs document ID (from URL)

    Returns:
        Document content and metadata
    """
    try:
        docs_service, _ = _get_google_docs_service(readonly=True)

        document = docs_service.documents().get(documentId=document_id).execute()

        # Extract text content
        content_parts = []
        for element in document.get("body", {}).get("content", []):
            if "paragraph" in element:
                paragraph = element["paragraph"]
                for text_run in paragraph.get("elements", []):
                    if "textRun" in text_run:
                        content_parts.append(text_run["textRun"]["content"])

        full_text = "".join(content_parts)

        logger.info("google_doc_read", doc_id=document_id, length=len(full_text))

        return {
            "title": document.get("title"),
            "document_id": document_id,
            "content": full_text,
            "url": f"https://docs.google.com/document/d/{document_id}",
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "read_google_doc", "google_docs")
    except Exception as e:
        logger.error("google_doc_read_failed", error=str(e), doc_id=document_id)
        raise ToolExecutionError("read_google_doc", str(e), e)


def search_google_drive(
    query: str, mime_type: str | None = None, max_results: int = 10
) -> list[dict[str, Any]]:
    """
    Search Google Drive for files.

    Args:
        query: Search query
        mime_type: Optional MIME type filter (e.g., 'application/vnd.google-apps.document')
        max_results: Max results to return

    Returns:
        List of matching files
    """
    try:
        _, drive_service = _get_google_docs_service(readonly=True)

        # Build search query
        search_query = f"name contains '{query}'"
        if mime_type:
            search_query += f" and mimeType = '{mime_type}'"

        response = (
            drive_service.files()
            .list(
                q=search_query,
                pageSize=max_results,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
            )
            .execute()
        )

        files = []
        for file in response.get("files", []):
            files.append(
                {
                    "id": file["id"],
                    "name": file["name"],
                    "type": file["mimeType"],
                    "url": file.get("webViewLink"),
                    "modified": file.get("modifiedTime"),
                }
            )

        logger.info("google_drive_search_completed", query=query, results=len(files))
        return files

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "search_google_drive", "google_docs"
        )
    except Exception as e:
        logger.error("google_drive_search_failed", error=str(e), query=query)
        raise ToolExecutionError("search_google_drive", str(e), e)


def list_folder_contents(folder_id: str) -> list[dict[str, Any]]:
    """
    List contents of a Google Drive folder.

    Args:
        folder_id: Google Drive folder ID

    Returns:
        List of files in folder
    """
    try:
        _, drive_service = _get_google_docs_service(readonly=True)

        response = (
            drive_service.files()
            .list(
                q=f"'{folder_id}' in parents",
                fields="files(id, name, mimeType, webViewLink)",
            )
            .execute()
        )

        files = []
        for file in response.get("files", []):
            files.append(
                {
                    "id": file["id"],
                    "name": file["name"],
                    "type": file["mimeType"],
                    "url": file.get("webViewLink"),
                }
            )

        logger.info("google_folder_listed", folder_id=folder_id, files=len(files))
        return files

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "list_folder_contents", "google_docs"
        )
    except Exception as e:
        logger.error("google_folder_list_failed", error=str(e), folder=folder_id)
        raise ToolExecutionError("list_folder_contents", str(e), e)


def google_docs_create_document(
    title: str, folder_id: str | None = None
) -> dict[str, Any]:
    """
    Create a new Google Doc.

    Args:
        title: Document title
        folder_id: Optional Google Drive folder ID to create doc in

    Returns:
        Created document info including document ID and URL
    """
    try:
        docs_service, drive_service = _get_google_docs_service(readonly=False)

        # Create document
        doc = docs_service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        # Move to folder if specified
        if folder_id:
            file = drive_service.files().get(fileId=doc_id, fields="parents").execute()
            previous_parents = ",".join(file.get("parents", []))
            drive_service.files().update(
                fileId=doc_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

        logger.info("google_docs_created", doc_id=doc_id, title=title)

        return {
            "document_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "google_docs_create_document", "google_docs"
        )
    except Exception as e:
        logger.error("google_docs_create_failed", error=str(e), title=title)
        raise ToolExecutionError("google_docs_create_document", str(e), e)


def google_docs_write_content(
    document_id: str, content: str, append: bool = True
) -> dict[str, Any]:
    """
    Write content to a Google Doc.

    Args:
        document_id: Google Doc ID
        content: Markdown or plain text content to write
        append: If True, append to document; if False, replace all content

    Returns:
        Write operation result
    """
    try:
        docs_service, _ = _get_google_docs_service(readonly=False)

        requests = []

        if not append:
            # Get document to find end index
            doc = docs_service.documents().get(documentId=document_id).execute()
            end_index = doc["body"]["content"][-1]["endIndex"] - 1

            # Delete all content except the first character (required by API)
            if end_index > 1:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": 1, "endIndex": end_index}
                        }
                    }
                )

        # Insert text at beginning (or after deletion)
        requests.append({"insertText": {"location": {"index": 1}, "text": content}})

        # Apply formatting for markdown-like syntax
        # Convert # headers to actual headers
        lines = content.split("\n")
        current_index = 1

        for line in lines:
            line_length = len(line) + 1  # +1 for newline

            # Header formatting
            if line.startswith("# ") and not line.startswith("## "):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": current_index,
                                "endIndex": current_index + line_length - 1,
                            },
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "fields": "namedStyleType",
                        }
                    }
                )
            elif line.startswith("## ") and not line.startswith("### "):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": current_index,
                                "endIndex": current_index + line_length - 1,
                            },
                            "paragraphStyle": {"namedStyleType": "HEADING_2"},
                            "fields": "namedStyleType",
                        }
                    }
                )
            elif line.startswith("### "):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": current_index,
                                "endIndex": current_index + line_length - 1,
                            },
                            "paragraphStyle": {"namedStyleType": "HEADING_3"},
                            "fields": "namedStyleType",
                        }
                    }
                )

            current_index += line_length

        # Execute all requests
        docs_service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

        logger.info(
            "google_docs_content_written", doc_id=document_id, length=len(content)
        )

        return {
            "document_id": document_id,
            "success": True,
            "characters_written": len(content),
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "google_docs_write_content", "google_docs"
        )
    except Exception as e:
        logger.error("google_docs_write_failed", error=str(e), doc_id=document_id)
        raise ToolExecutionError("google_docs_write_content", str(e), e)


def google_docs_share_document(
    document_id: str,
    email: str | None = None,
    role: str = "reader",
    anyone: bool = False,
) -> dict[str, Any]:
    """
    Share a Google Doc with users or make it publicly accessible.

    Args:
        document_id: Google Doc ID
        email: Email address to share with (optional if anyone=True)
        role: Permission role (reader, writer, commenter)
        anyone: If True, make document accessible to anyone with link

    Returns:
        Share operation result
    """
    try:
        _, drive_service = _get_google_docs_service(readonly=False)

        if anyone:
            # Make document accessible to anyone with link
            permission = {"type": "anyone", "role": role}
            drive_service.permissions().create(
                fileId=document_id, body=permission, fields="id"
            ).execute()

            logger.info("google_docs_shared_publicly", doc_id=document_id, role=role)

            return {
                "document_id": document_id,
                "shared_with": "anyone",
                "role": role,
                "url": f"https://docs.google.com/document/d/{document_id}/edit",
                "success": True,
            }

        elif email:
            # Share with specific email
            permission = {"type": "user", "role": role, "emailAddress": email}
            drive_service.permissions().create(
                fileId=document_id,
                body=permission,
                fields="id",
                sendNotificationEmail=True,
            ).execute()

            logger.info(
                "google_docs_shared_with_user",
                doc_id=document_id,
                email=email,
                role=role,
            )

            return {
                "document_id": document_id,
                "shared_with": email,
                "role": role,
                "success": True,
            }

        else:
            raise ValueError("Must specify either email or anyone=True")

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "google_docs_share_document", "google_docs"
        )
    except Exception as e:
        logger.error("google_docs_share_failed", error=str(e), doc_id=document_id)
        raise ToolExecutionError("google_docs_share_document", str(e), e)


# List of all Google Docs tools for registration
GOOGLE_DOCS_TOOLS = [
    read_google_doc,
    search_google_drive,
    list_folder_contents,
    google_docs_create_document,
    google_docs_write_content,
    google_docs_share_document,
]
