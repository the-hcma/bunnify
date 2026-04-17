from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.db import models
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Bookmark

if TYPE_CHECKING:
    from django.http import HttpRequest

# Get logger for this module
logger = logging.getLogger(__name__)


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
    placeholders = re.findall(r"#\{(\w+)\}", url)

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
        for placeholder, value in param_mapping.items():
            url = url.replace(f"#{{{placeholder}}}", value)

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
    placeholders = re.findall(r"#\{(\w+)\}", url)

    if placeholders:
        logger.debug(f"URL contains placeholders: {placeholders}")
        # Get parameters from query string
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
            # Replace the placeholder with the actual value
            url = url.replace(f"#{{{placeholder}}}", param_value)

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
        placeholders = re.findall(r"#\{(\w+)\}", bookmark.url)
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
        placeholders = re.findall(r"#\{(\w+)\}", bookmark.url)
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
def request_copilot_review(
    request: HttpRequest,
) -> HttpResponse | StreamingHttpResponse:
    """
    Request a GitHub Copilot review for a PR and display it in Bunnify with live updates.
    """
    import html as html_module
    import subprocess
    from pathlib import Path

    from django.http import StreamingHttpResponse

    pr_param = request.GET.get("pr", "")
    pr_number = str(pr_param) if pr_param else ""
    repo_param = request.GET.get("repo", "shop/world")
    repo = str(repo_param) if repo_param else "shop/world"

    # Validate PR number (must be numeric)
    if not pr_number:
        return HttpResponse(
            content="Error: PR number is required. Usage: /review-pr/?pr=12345&repo=shop/world",
            status=400,
        )

    if not pr_number.isdigit():
        logger.warning(f"Invalid PR number provided: {pr_number}")
        return HttpResponse(content="Error: PR number must be numeric.", status=400)

    # Validate repo format (owner/name)
    if not re.match(r"^[\w\-\.]+/[\w\-\.]+$", repo):
        logger.warning(f"Invalid repo format provided: {repo}")
        return HttpResponse(
            content="Error: Repository must be in format 'owner/name'.", status=400
        )

    logger.info(
        f"Requesting private Copilot review with live updates for PR #{pr_number} in {repo}"
    )

    # Path to the private review script
    script_path = Path(__file__).parent.parent / "scripts" / "get_copilot_review.sh"

    if not script_path.exists():
        logger.error(f"Helper script not found: {script_path}")
        return HttpResponse(
            content=f"Error: Helper script not found at {script_path}", status=500
        )

    def stream_review():
        """Generator that yields HTML chunks as the script progresses"""
        # Yield the initial HTML with live update script
        yield f"""<!DOCTYPE html>
<html>
<head>
    <title>Copilot Review - PR #{pr_number}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 900px;
            margin: 30px auto;
            padding: 20px;
            line-height: 1.6;
            background: #f6f8fa;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .header h1 {{
            margin: 0 0 10px 0;
            font-size: 24px;
        }}
        .pr-link {{
            color: #0969da;
            text-decoration: none;
            font-size: 14px;
        }}
        .status {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .status h2 {{
            margin-top: 0;
            color: #24292f;
            font-size: 18px;
        }}
        .spinner {{
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid #d0d7de;
            border-top-color: #0969da;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        .log-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .log-container h2 {{
            margin-top: 0;
            color: #24292f;
            font-size: 18px;
            border-bottom: 1px solid #d0d7de;
            padding-bottom: 10px;
        }}
        #log-output {{
            background: #f6f8fa;
            padding: 15px;
            border-radius: 6px;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 13px;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: #24292f;
            max-height: 400px;
            overflow-y: auto;
        }}
        .review-container {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: none;
        }}
        .review-container.show {{
            display: block;
        }}
        .review-container h2 {{
            margin-top: 0;
            color: #24292f;
            font-size: 20px;
            border-bottom: 1px solid #d0d7de;
            padding-bottom: 10px;
        }}
        .review-content {{
            color: #24292f;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 14px;
            line-height: 1.6;
        }}
        .complete {{
            color: #1a7f37;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 GitHub Copilot Review</h1>
        <a href="https://github.com/{repo}/pull/{pr_number}" class="pr-link" target="_blank">
            View PR #{pr_number} in {repo} →
        </a>
    </div>
    
    <div class="status">
        <h2><span class="spinner"></span><span id="status-text">Requesting review...</span></h2>
    </div>
    
    <div class="log-container">
        <h2>📋 Processing Log</h2>
        <div id="log-output"></div>
    </div>
    
    <div class="review-container" id="review-section">
        <h2>Review Analysis</h2>
        <div class="review-content" id="review-content"></div>
    </div>
</body>
</html>
"""

        # Now run the script and stream output
        try:
            import fcntl
            import os
            import select

            process = subprocess.Popen(
                [str(script_path), pr_number, repo],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Make stdout non-blocking
            if process.stdout:
                fd = process.stdout.fileno()
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            output_buffer = []
            review_content = ""
            in_review_section = False

            while True:
                # Check if process has finished
                if process.poll() is not None:
                    # Read any remaining output
                    if process.stdout:
                        remaining = process.stdout.read()
                        if remaining:
                            output_buffer.append(remaining)
                            for line in remaining.split("\\n"):
                                if line.strip():
                                    escaped_line = html_module.escape(line)
                                    yield f'<script>document.getElementById("log-output").innerHTML += "{escaped_line}\\n";</script>'
                    break

                # Try to read output
                if process.stdout:
                    try:
                        line = process.stdout.readline()
                        if line:
                            output_buffer.append(line)

                            # Check for review markers
                            if "---COPILOT_REVIEW_START---" in line:
                                in_review_section = True
                                yield '<script>document.getElementById("status-text").innerHTML = "Processing review...";</script>'
                                continue
                            elif "---COPILOT_REVIEW_END---" in line:
                                in_review_section = False
                                # Display the review
                                if review_content:
                                    escaped_review = html_module.escape(
                                        review_content.strip()
                                    )
                                    yield f'<script>document.getElementById("review-content").textContent = "{escaped_review}"; document.getElementById("review-section").classList.add("show"); document.querySelector(".spinner").style.display = "none"; document.getElementById("status-text").className = "complete"; document.getElementById("status-text").innerHTML = "✅ Review complete!";</script>'
                                continue

                            if in_review_section:
                                review_content += line
                            else:
                                # Update log output
                                escaped_line = html_module.escape(line.rstrip())
                                if escaped_line:
                                    yield f'<script>var log = document.getElementById("log-output"); log.innerHTML += "{escaped_line}\\n"; log.scrollTop = log.scrollHeight;</script>'

                                # Update status based on content
                                if "Posting review request" in line:
                                    yield '<script>document.getElementById("status-text").innerHTML = "Posting review request...";</script>'
                                elif "Waiting for Copilot" in line:
                                    yield '<script>document.getElementById("status-text").innerHTML = "Waiting for Copilot response (max 60s)...";</script>'
                                elif "Cleaning up" in line:
                                    yield '<script>document.getElementById("status-text").innerHTML = "Cleaning up...";</script>'
                                elif "Copilot did not respond" in line:
                                    yield '<script>document.querySelector(".spinner").style.display = "none"; document.getElementById("status-text").innerHTML = "⏱️ Copilot did not respond within timeout";</script>'
                    except IOError, BlockingIOError:
                        # No data available, wait a bit
                        import time

                        time.sleep(0.1)

            # Final status
            if not review_content:
                yield '<script>document.querySelector(".spinner").style.display = "none"; document.getElementById("status-text").className = "complete"; document.getElementById("status-text").innerHTML = "⏱️ Review completed (timeout or no response)";</script>'

            process.wait()

        except Exception as e:
            logger.error(f"Error during streaming: {e}", exc_info=True)
            yield f'<script>document.querySelector(".spinner").style.display = "none"; document.getElementById("status-text").innerHTML = "❌ Error: {html_module.escape(str(e))}";</script>'

    return StreamingHttpResponse(stream_review(), content_type="text/html")


@require_http_methods(["GET"])
def health_check(request: HttpRequest) -> HttpResponse:
    """
    Simple health check endpoint that returns 'ok'
    Used by systemd and monitoring tools to verify the service is alive.
    """
    return HttpResponse("ok", content_type="text/plain")
