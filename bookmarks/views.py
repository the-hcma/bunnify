from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from django.db import models
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from app.version import get_build_info

from .keys_catalog import catalog_payload
from .models import Bookmark
from .resolve import PLACEHOLDER_PATTERN, resolve_query, substitute_placeholder_values

if TYPE_CHECKING:
    from django.http import HttpRequest

# Get logger for this module
logger = logging.getLogger(__name__)


def _make_redirect_response(request: HttpRequest, url: str) -> HttpResponse:
    """Return a redirect (or browser_url page for special protocols)."""
    if url.lower().startswith(("chrome://", "about://", "file://")):
        return render(request, "bookmarks/browser_url.html", {"url": url})

    response = HttpResponse(status=302)
    response["Location"] = url
    return response


def _absolute_resolve_url(request: HttpRequest, url: str) -> str:
    """Turn site-relative resolve URLs into absolute ones for the CLI/API."""
    if not url.startswith("/"):
        return url
    script_prefix = request.path.removesuffix(request.path_info).rstrip("/")
    absolute_url = request.build_absolute_uri(f"{script_prefix}/{url.lstrip('/')}")
    return absolute_url if absolute_url is not None else url


def _build_info_context() -> dict[str, str]:
    """Return template context describing this Bunnify build."""
    package, commit = get_build_info()
    return {
        "git_commit": commit,
        "package_version": package,
    }


@require_http_methods(["GET"])
def search_redirect(request: HttpRequest) -> HttpResponse:
    """
    Handle search queries in the format: "key param1 param2 ..."
    Example: "pr 12345" or "pr 12345 Shopify/shopify-build" or "g django tutorial"
    Special: "h" shows all bookmarks

    Token placeholders are whitespace-separated. When a shortcut has a single
    free-text placeholder (``search_terms``, ``phrase``, …), it takes the
    remainder of the query.
    Extra arguments beyond what the shortcut accepts return HTTP 400 with usage.
    """
    query_param = request.GET.get("q", "")
    query = str(query_param).strip() if query_param else ""
    logger.info(f"Search redirect request: query='{query}'")

    result = resolve_query(query)
    if not result.ok:
        if result.error and result.error.startswith("No search query"):
            logger.warning("Empty search query received")
            return HttpResponseNotFound(content=result.error)
        return HttpResponse(result.error or "Resolve failed", status=400)

    assert result.url is not None
    if result.kind == "special":
        logger.info("Redirecting to special page for key=%r", result.key)
        return redirect(result.url)
    if result.kind == "direct_url":
        logger.info(f"Direct URL redirect: url='{query}'")
    elif result.kind == "google_fallback":
        logger.info("No bookmark for key=%r, falling back to Google search", result.key)
    else:
        logger.info("Found bookmark: key=%r, url=%r", result.key, result.url)
    return _make_redirect_response(request, result.url)


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

        url = substitute_placeholder_values(url, param_mapping)

    logger.info(f"Redirecting to: {url}")
    return _make_redirect_response(request, url)


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
        request,
        "bookmarks/list.html",
        {
            **_build_info_context(),
            "bookmarks_with_params": bookmarks_with_params,
        },
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
        request,
        "bookmarks/cmd.html",
        {
            **_build_info_context(),
            "bookmarks_json": json.dumps(bookmarks_data),
        },
    )


@require_http_methods(["GET"])
def index(request: HttpRequest) -> HttpResponse:
    """
    Home page with instructions
    """
    logger.debug("Index page request")
    return render(request, "bookmarks/index.html", _build_info_context())


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
    OpenSearch suggestions API - provides autocomplete suggestions for bookmarks.

    Returns suggestions in OpenSearch format:
    [query, [suggestions], [descriptions], [urls]]
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
    )[:10]  # Limit to 10 suggestions

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
@require_http_methods(["GET"])
def api_resolve(request: HttpRequest) -> JsonResponse:
    """
    JSON resolve API for the CLI.

    Query params:
      q: shortcut query (required)
      strict: if truthy, unknown keys are errors (no Google fallback)
    """
    query_param = request.GET.get("q", "")
    query = str(query_param).strip() if query_param else ""
    strict_raw = str(request.GET.get("strict", "")).strip().lower()
    strict = strict_raw in {"1", "true", "yes", "on"}

    result = resolve_query(query, strict=strict)
    if not result.ok:
        status = 404 if result.error and result.error.startswith("Unknown") else 400
        return JsonResponse(
            {
                "ok": False,
                "error": result.error,
                "key": result.key,
            },
            status=status,
        )

    assert result.url is not None
    return JsonResponse(
        {
            "ok": True,
            "url": _absolute_resolve_url(request, result.url),
            "kind": result.kind,
            "key": result.key,
        }
    )


@never_cache
@require_http_methods(["GET"])
def api_keys(request: HttpRequest) -> JsonResponse:
    """Return shortcut keys plus structured usage entries for the CLI.

    Payload always includes:
      keys: list[str] — backward-compatible flat list for bash completion / fzf
      entries: list[{key, description, url, params}] — short-usage metadata
    """
    del request
    return JsonResponse(catalog_payload())


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
    Health check for systemd and the CLI.

    Plain ``ok`` for text clients; JSON with version/commit when ``Accept``
    contains ``application/json`` (q-values are not consulted).
    """
    package, commit = get_build_info()
    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return JsonResponse(
            {
                "commit": commit,
                "status": "ok",
                "version": package,
            }
        )
    return HttpResponse("ok", content_type="text/plain")
