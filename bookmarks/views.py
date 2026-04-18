from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.core.cache import cache
from django.db import models
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Bookmark

if TYPE_CHECKING:
    from django.http import HttpRequest

# Get logger for this module
logger = logging.getLogger(__name__)
PLACEHOLDER_PATTERN = re.compile(r"#\{(\w+)\}")


def _encode_placeholder_value(url_template: str, placeholder: str, value: str) -> str:
    """Encode placeholder values while preserving path separators when needed."""
    token = f"#{{{placeholder}}}"
    placeholder_start = url_template.index(token)
    query_start = url_template.rfind("?", 0, placeholder_start)
    last_ampersand = url_template.rfind("&", 0, placeholder_start)
    last_equals = url_template.rfind("=", 0, placeholder_start)

    if last_equals > max(query_start, last_ampersand):
        return quote(value, safe="")

    return quote(value, safe="/:@-._~")


def _substitute_placeholder_values(
    url_template: str, param_mapping: dict[str, str]
) -> str:
    """Replace URL placeholders with encoded values."""
    substituted_url = url_template

    for placeholder, value in param_mapping.items():
        encoded_value = _encode_placeholder_value(url_template, placeholder, value)
        substituted_url = substituted_url.replace(f"#{{{placeholder}}}", encoded_value)

    return substituted_url


@require_http_methods(["GET"])
def search_redirect(request: HttpRequest) -> HttpResponse:
    """
    Handle search queries in the format: "key param1 param2 ..."
    Example: "pr 12345" or "pr 12345 Shopify/shopify-build" or "g django tutorial"
    Special: "h" shows all bookmarks

    For bookmarks with multiple parameters, splits by space.
    For bookmarks with single parameter, passes everything after key as the value.
    """
    query_param = request.GET.get("q", "")
    query = str(query_param).strip() if query_param else ""
    logger.info(f"Search redirect request: query='{query}'")

    if not query:
        logger.warning("Empty search query received")
        return HttpResponseNotFound(content="No search query provided")

    # Split the query into parts
    parts = query.split(None, 1)  # Split into key and rest

    if not parts:
        return HttpResponseNotFound(content="Empty search query")

    key = parts[0]

    # Special case: "h", "help", "cmd" - internal commands
    if key in ("h", "help"):
        logger.info(f"Redirecting to help/list page for key='{key}'")
        return redirect("/list/")

    if key == "cmd":
        logger.info(f"Redirecting to command palette for key='{key}'")
        return redirect("/cmd/")

    param_string = parts[1] if len(parts) > 1 else ""

    # Try to find the bookmark
    try:
        bookmark = Bookmark.objects.get(key=key)
        logger.info(
            f"Found bookmark: key='{key}', url='{bookmark.url}', params='{param_string}'"
        )
    except Bookmark.DoesNotExist:
        logger.warning(f"Bookmark not found: key='{key}'")
        return HttpResponseNotFound(content=f"Bookmark '{key}' not found")

    url = bookmark.url

    # Find all placeholders in the URL (e.g., #{pr_id}, #{repo})
    placeholders = PLACEHOLDER_PATTERN.findall(url)

    if placeholders:
        # Build parameter mapping
        param_mapping = {}

        if len(placeholders) == 1:
            # Single parameter - use entire param_string
            if param_string or (
                bookmark.defaults and placeholders[0] in bookmark.defaults
            ):
                param_mapping[placeholders[0]] = (
                    param_string if param_string else bookmark.defaults[placeholders[0]]
                )
            else:
                return HttpResponse(
                    f"Bookmark '{key}' requires a parameter.\n" f"Usage: {key} <value>",
                    status=400,
                )
        else:
            # Multiple parameters - split by whitespace
            param_values = param_string.split() if param_string else []

            if len(param_values) > len(placeholders):
                return HttpResponse(
                    f"Too many parameters for bookmark '{key}'.",
                    status=400,
                )

            # Assign args to placeholders from the end (right-to-left in template
            # order). This lets optional leading params use their defaults when
            # the user provides fewer args than there are placeholders.
            # Example: placeholders=[repo, pr_number], defaults={repo: "org/repo"}
            #   "pr 194"               -> repo=default, pr_number=194
            #   "pr the-hcma/fpdf 194" -> repo=the-hcma/fpdf, pr_number=194
            arg_offset = len(placeholders) - len(param_values)
            for i, placeholder in enumerate(placeholders):
                arg_idx = i - arg_offset
                if arg_idx >= 0:
                    param_mapping[placeholder] = param_values[arg_idx]
                elif placeholder in (bookmark.defaults or {}):
                    param_mapping[placeholder] = bookmark.defaults[placeholder]
                else:
                    required_params = [
                        p for p in placeholders if p not in (bookmark.defaults or {})
                    ]
                    optional_params = [
                        p for p in placeholders if p in (bookmark.defaults or {})
                    ]
                    return HttpResponse(
                        f"Bookmark '{key}' requires parameter(s): {', '.join(required_params)}\n"
                        f"Usage: {key} {' '.join(f'<{p}>' for p in required_params)}"
                        + (
                            f" [{' '.join(optional_params)}]" if optional_params else ""
                        ),
                        status=400,
                    )

        # Replace all placeholders with their values
        url = _substitute_placeholder_values(url, param_mapping)

    # Check if this is a special protocol (chrome://, about://, etc.)
    # Browsers block navigation to these URLs from web pages for security
    # So we display the URL with copy-paste instructions
    if url.startswith(("chrome://", "about://", "file://")):
        return render(request, "bookmarks/browser_url.html", {"url": url})

    # For normal HTTP(S) URLs, use a standard 302 redirect
    response = HttpResponse(status=302)
    response["Location"] = url
    return response


@require_http_methods(["GET"])
def redirect_bookmark(request: HttpRequest, key: str) -> HttpResponse:
    """
    Redirect to the bookmark URL, handling parameter substitution
    """
    logger.info(f"Direct bookmark redirect request: key='{key}'")

    # Internal special commands
    if key in ("h", "help"):
        return redirect("/list/")
    if key == "cmd":
        return redirect("/cmd/")

    try:
        bookmark = Bookmark.objects.get(key=key)
    except Bookmark.DoesNotExist:
        logger.warning(f"Bookmark not found for direct access: key='{key}'")
        return HttpResponseNotFound(content=f"Bookmark '{key}' not found")

    url = bookmark.url

    # Find all placeholders in the URL (e.g., #{pr_id}, #{search_terms})
    placeholders = PLACEHOLDER_PATTERN.findall(url)

    if placeholders:
        logger.debug(f"URL contains placeholders: {placeholders}")
        # Get parameters from query string
        param_mapping: dict[str, str] = {}
        for placeholder in placeholders:
            param_value = request.GET.get(placeholder, "")
            if not param_value:
                logger.warning(
                    f"Missing required parameter '{placeholder}' for bookmark '{key}'"
                )
                # Return a helpful error message
                return HttpResponse(
                    f"Missing required parameter: {placeholder}\n"
                    f"Usage: /{key}/?{placeholder}=value",
                    status=400,
                )
            param_mapping[placeholder] = param_value

        url = _substitute_placeholder_values(url, param_mapping)

    logger.info(f"Redirecting to: {url}")
    # Check if this is a special protocol (chrome://, about://, etc.)
    # Browsers block navigation to these URLs from web pages for security
    # So we display the URL with copy-paste instructions
    if url.startswith(("chrome://", "about://", "file://")):
        return render(request, "bookmarks/browser_url.html", {"url": url})

    # For normal HTTP(S) URLs, use a standard 302 redirect
    response = HttpResponse(status=302)
    response["Location"] = url
    return response


@never_cache
@require_http_methods(["GET"])
def list_bookmarks(request: HttpRequest) -> HttpResponse:
    """
    List all available bookmarks, sorted lexicographically by key
    """
    logger.info("List bookmarks request")
    bookmarks = Bookmark.objects.all().order_by("key")
    count = bookmarks.count()
    logger.debug(f"Retrieved {count} bookmarks for listing")

    # Extract parameter names from URLs for display
    bookmarks_with_params = []
    for bookmark in bookmarks:
        placeholders = PLACEHOLDER_PATTERN.findall(bookmark.url)
        bookmarks_with_params.append({"bookmark": bookmark, "params": placeholders})

    return render(
        request, "bookmarks/list.html", {"bookmarks_with_params": bookmarks_with_params}
    )


@never_cache
@require_http_methods(["GET"])
def cmd_palette(request: HttpRequest) -> HttpResponse:
    """
    Command palette with autocomplete for bookmarks
    """
    logger.info("Command palette request")
    bookmarks = Bookmark.objects.all().order_by("key")
    count = bookmarks.count()
    logger.debug(f"Retrieved {count} bookmarks for command palette")

    # Prepare bookmark data with params for JavaScript
    bookmarks_data = []
    for bookmark in bookmarks:
        placeholders = PLACEHOLDER_PATTERN.findall(bookmark.url)
        bookmarks_data.append(
            {
                "key": bookmark.key,
                "description": bookmark.description,
                "url": bookmark.url,
                "params": placeholders,
            }
        )

    return render(
        request, "bookmarks/cmd.html", {"bookmarks_json": json.dumps(bookmarks_data)}
    )


@require_http_methods(["GET"])
def index(request: HttpRequest) -> HttpResponse:
    """
    Home page with instructions
    """
    logger.debug("Index page request")
    return render(request, "bookmarks/index.html")


@require_http_methods(["GET"])
def opensearch(request: HttpRequest) -> HttpResponse:
    """
    Serve OpenSearch description for browser integration
    """
    logger.debug("OpenSearch XML request")
    return render(
        request,
        "bookmarks/opensearch.xml",
        content_type="application/opensearchdescription+xml",
    )


@never_cache
@require_http_methods(["GET"])
def bookmark_status(request: HttpRequest) -> JsonResponse:
    """
    Return current bookmark count and content hash for auto-refresh detection
    """
    count = Bookmark.objects.count()

    # Generate a hash of all bookmark data to detect any changes
    bookmarks = (
        Bookmark.objects.all().values("key", "url", "description").order_by("key")
    )
    content = json.dumps(list(bookmarks), sort_keys=True)
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    logger.debug(f"Bookmark status check: count={count}, hash={content_hash}")

    return JsonResponse({"count": count, "hash": content_hash[:16]})


@never_cache
@require_http_methods(["GET"])
def search_suggestions(request: HttpRequest) -> JsonResponse:
    """
    OpenSearch suggestions API - provides autocomplete suggestions for bookmarks
    Returns suggestions in OpenSearch format: [query, [suggestions], [descriptions], [urls]]
    """
    query_param = request.GET.get("q", "")
    query = str(query_param).strip().lower() if query_param else ""

    if not query:
        return JsonResponse([query, [], [], []], safe=False)

    # Split query into parts (key and params)
    parts = query.split(None, 1)
    search_key = parts[0] if parts else query

    # Get matching bookmarks (key starts with search_key or description contains it)
    bookmarks = Bookmark.objects.filter(
        models.Q(key__istartswith=search_key)
        | models.Q(description__icontains=search_key)
    )[
        :10
    ]  # Limit to 10 suggestions

    # Also include special commands
    special_commands = []
    if "help".startswith(search_key) or "h".startswith(search_key):
        special_commands.append(("h", "Show all bookmarks", "/list/"))

    suggestions = []
    descriptions = []
    urls = []

    # Add special commands first
    for cmd, desc, url in special_commands:
        suggestions.append(cmd)
        descriptions.append(desc)
        urls.append(f"http://127.0.0.1:8000{url}")

    # Add matching bookmarks
    for bookmark in bookmarks:
        suggestions.append(bookmark.key)
        descriptions.append(bookmark.description or f"Redirect to {bookmark.url}")
        # Generate a preview URL
        urls.append(f"http://127.0.0.1:8000/{bookmark.key}/")

    logger.debug(f"Search suggestions for '{query}': {len(suggestions)} results")

    # OpenSearch format: [query, [completions], [descriptions], [urls]]
    return JsonResponse([query, suggestions, descriptions, urls], safe=False)


@never_cache
@require_http_methods(["GET", "POST"])
def command_history(request: HttpRequest) -> JsonResponse:
    """
    Command history API - stores and retrieves command history
    GET: Returns recent command history
    POST: Adds a command to history
    """
    # For simplicity, we'll use session storage for per-user history
    if request.method == "POST":
        command_param = request.POST.get("command", "")
        command = str(command_param).strip() if command_param else ""
        if command:
            history = request.session.get("command_history", [])
            # Remove duplicates and add to front
            if command in history:
                history.remove(command)
            history.insert(0, command)
            # Keep only last 50 commands
            history = history[:50]
            request.session["command_history"] = history
            logger.debug(f"Added command to history: {command}")
            return JsonResponse({"status": "ok", "history": history})

    # GET request - return history
    history = request.session.get("command_history", [])
    return JsonResponse({"history": history})


@require_http_methods(["GET"])
def health_check(request: HttpRequest) -> HttpResponse:
    """
    Simple health check endpoint that returns 'ok'
    Used by systemd and monitoring tools to verify the service is alive.
    """
    return HttpResponse("ok", content_type="text/plain")
