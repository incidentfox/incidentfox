"""
Output handlers for multi-destination output system.

Each handler knows how to format and post agent output to a specific destination.
"""

from .github import GitHubIssueCommentHandler, GitHubPRCommentHandler
from .slack import SlackOutputHandler

__all__ = [
    "SlackOutputHandler",
    "GitHubPRCommentHandler",
    "GitHubIssueCommentHandler",
]
