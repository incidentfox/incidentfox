"""
Browser tools for screenshots and web scraping.

Ported from cto-ai-agent, adapted for OpenAI Agents SDK.
Requires: playwright (pip install playwright && playwright install chromium)
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import logging
import os

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _optional_import(module_name: str):
    """Import a module, returning None if not available."""
    try:
        import importlib

        return importlib.import_module(module_name)
    except ImportError:
        return None


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an event loop, create a new one in a thread
            import threading

            result = [None]
            exception = [None]

            @function_tool
            def run():
                try:
                    result[0] = asyncio.run(coro)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=run)
            thread.start()
            thread.join(timeout=60)

            if exception[0]:
                raise exception[0]
            return result[0]
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@function_tool
def browser_screenshot(
    url: str,
    output_path: str = "",
    full_page: bool = False,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    wait_ms: int = 1000,
    selector: str = "",
) -> str:
    """
    Take a screenshot of a web page.

    Use cases:
    - Capture visual state of a web application
    - Document UI bugs or design issues
    - Verify visual rendering

    Args:
        url: Full URL to screenshot
        output_path: Where to save the image (returns base64 if empty)
        full_page: Capture entire scrollable page
        viewport_width: Browser width (default 1280)
        viewport_height: Browser height (default 720)
        wait_ms: Wait time after load (default 1000)
        selector: CSS selector to screenshot specific element

    Returns:
        JSON with ok, url, size_bytes, and saved_to or base64
    """
    if not url:
        return json.dumps({"ok": False, "error": "url is required"})

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("browser_screenshot", url=url)

    pw = _optional_import("playwright.async_api")
    if pw is None:
        return json.dumps(
            {
                "ok": False,
                "error": "playwright not installed. Install: pip install playwright && playwright install chromium",
            }
        )

    async def _take_screenshot():
        async with pw.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height}
                )
                page = await context.new_page()

                await page.goto(url, wait_until="networkidle", timeout=30000)

                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

                if selector:
                    element = await page.query_selector(selector)
                    if not element:
                        return {"ok": False, "error": f"selector_not_found: {selector}"}
                    screenshot_bytes = await element.screenshot()
                else:
                    screenshot_bytes = await page.screenshot(full_page=full_page)

                result = {
                    "ok": True,
                    "url": url,
                    "width": viewport_width,
                    "height": viewport_height,
                    "full_page": full_page,
                    "size_bytes": len(screenshot_bytes),
                }

                if output_path:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(screenshot_bytes)
                    result["saved_to"] = output_path
                else:
                    result["base64"] = base64.b64encode(screenshot_bytes).decode(
                        "utf-8"
                    )

                return result
            finally:
                await browser.close()

    try:
        result = _run_async(_take_screenshot())
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def browser_scrape(
    url: str,
    extract_links: bool = True,
    extract_text: bool = True,
    extract_images: bool = False,
    wait_ms: int = 1000,
    javascript: str = "",
) -> str:
    """
    Scrape content from a web page with full JavaScript rendering.

    Use cases:
    - Extract data from dynamic JavaScript-rendered pages
    - Get page text content for analysis
    - Collect all links or images from a page

    Args:
        url: Full URL to scrape
        extract_links: Collect all links (default True)
        extract_text: Get full page text (default True)
        extract_images: Collect all images (default False)
        wait_ms: Wait after load for dynamic content
        javascript: Custom JS to execute

    Returns:
        JSON with ok, url, title, text, links, images, meta
    """
    if not url:
        return json.dumps({"ok": False, "error": "url is required"})

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("browser_scrape", url=url)

    pw = _optional_import("playwright.async_api")
    if pw is None:
        return json.dumps(
            {
                "ok": False,
                "error": "playwright not installed. Install: pip install playwright && playwright install chromium",
            }
        )

    async def _scrape_page():
        async with pw.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                response = await page.goto(url, wait_until="networkidle", timeout=30000)

                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

                result: dict[str, Any] = {
                    "ok": True,
                    "url": url,
                    "status_code": response.status if response else None,
                }

                result["title"] = await page.title()

                if javascript:
                    result["js_result"] = await page.evaluate(javascript)

                if extract_text:
                    body = await page.query_selector("body")
                    if body:
                        text = await body.inner_text()
                        text = re.sub(r"\n\s*\n", "\n\n", text)
                        result["text"] = text[:50000]

                if extract_links:
                    links = []
                    anchors = await page.query_selector_all("a[href]")
                    for anchor in anchors[:200]:
                        href = await anchor.get_attribute("href")
                        text = await anchor.inner_text()
                        if href:
                            full_url = urljoin(url, href)
                            links.append({"url": full_url, "text": text.strip()[:100]})
                    result["links"] = links

                if extract_images:
                    images = []
                    img_elements = await page.query_selector_all("img[src]")
                    for img in img_elements[:100]:
                        src = await img.get_attribute("src")
                        alt = await img.get_attribute("alt") or ""
                        if src:
                            full_url = urljoin(url, src)
                            images.append({"url": full_url, "alt": alt.strip()[:100]})
                    result["images"] = images

                # Get meta tags
                meta_tags = {}
                for meta in await page.query_selector_all("meta[name], meta[property]"):
                    name = await meta.get_attribute("name") or await meta.get_attribute(
                        "property"
                    )
                    content = await meta.get_attribute("content")
                    if name and content:
                        meta_tags[name] = content[:500]
                result["meta"] = meta_tags

                return result
            finally:
                await browser.close()

    try:
        result = _run_async(_scrape_page())
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def browser_fetch_html(url: str, timeout_s: float = 30.0) -> str:
    """
    Fetch raw HTML from a URL (lightweight, no browser rendering).

    Use cases:
    - Quick HTML fetch without JavaScript rendering
    - Lower resource usage than full browser scrape
    - Simple static page extraction

    Args:
        url: Full URL to fetch
        timeout_s: Request timeout in seconds

    Returns:
        JSON with ok, url, status_code, html, content_type
    """
    if not url:
        return json.dumps({"ok": False, "error": "url is required"})

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("browser_fetch_html", url=url)

    httpx = _optional_import("httpx")
    if httpx is None:
        return json.dumps({"ok": False, "error": "httpx not installed"})

    req_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; IncidentFoxAgent/1.0)",
    }

    try:
        response = httpx.get(
            url, headers=req_headers, timeout=timeout_s, follow_redirects=True
        )
        return json.dumps(
            {
                "ok": response.status_code < 400,
                "url": str(response.url),
                "status_code": response.status_code,
                "html": response.text[:100000],
                "content_type": response.headers.get("content-type", ""),
            }
        )
    except Exception as e:
        return json.dumps({"ok": False, "url": url, "error": str(e)})


@function_tool
def browser_pdf(
    url: str,
    output_path: str,
    format: str = "A4",
    landscape: bool = False,
    wait_ms: int = 1000,
) -> str:
    """
    Generate a PDF from a web page.

    Use cases:
    - Create PDF reports from web pages
    - Archive web content
    - Generate printable documents

    Args:
        url: Full URL to convert
        output_path: Where to save the PDF
        format: Paper format (A4, Letter, etc.)
        landscape: Landscape orientation
        wait_ms: Wait after load

    Returns:
        JSON with ok, url, saved_to, size_bytes
    """
    if not url:
        return json.dumps({"ok": False, "error": "url is required"})
    if not output_path:
        return json.dumps({"ok": False, "error": "output_path is required"})

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("browser_pdf", url=url, output_path=output_path)

    pw = _optional_import("playwright.async_api")
    if pw is None:
        return json.dumps(
            {
                "ok": False,
                "error": "playwright not installed. Install: pip install playwright && playwright install chromium",
            }
        )

    async def _generate_pdf():
        async with pw.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)

                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                await page.pdf(
                    path=output_path,
                    format=format,
                    landscape=landscape,
                    print_background=True,
                )

                size = Path(output_path).stat().st_size
                return {
                    "ok": True,
                    "url": url,
                    "saved_to": output_path,
                    "size_bytes": size,
                }
            finally:
                await browser.close()

    try:
        result = _run_async(_generate_pdf())
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("browser_screenshot", browser_screenshot)
register_tool("browser_scrape", browser_scrape)
register_tool("browser_fetch_html", browser_fetch_html)
register_tool("browser_pdf", browser_pdf)
