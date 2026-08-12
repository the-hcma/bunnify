from django.test import Client, TestCase

from app.version import get_build_info

from .models import Bookmark


class SmokeTests(TestCase):
    """Smoke tests to ensure core functionality works"""

    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()
        get_build_info.cache_clear()

        # Create test bookmarks
        Bookmark.objects.create(
            key="g",
            description="Google Search",
            url="https://www.google.com/search?q=#{search_terms}",
        )
        Bookmark.objects.create(
            key="gh", description="GitHub", url="https://github.com"
        )
        Bookmark.objects.create(
            key="pr",
            description="Pull Request",
            url="https://github.com/#{repo}/pull/#{pr_number}",
            defaults={"repo": "default-org/default-repo"},
        )

    def test_index_page_loads(self):
        """Test that the index page loads successfully"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        package, commit = get_build_info()
        self.assertContains(response, package)
        self.assertContains(response, f'data-commit="commit {commit}"')
        self.assertContains(response, "Chrome or Edge")
        self.assertContains(response, "bunnylol")

    def test_list_page_loads(self):
        """Test that the list page loads and shows bookmarks"""
        response = self.client.get("/list/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "g")
        self.assertContains(response, "Google Search")
        self.assertContains(response, "gh")
        self.assertContains(response, "GitHub")

    def test_cmd_page_loads(self):
        """Test that the command palette page loads"""
        response = self.client.get("/cmd/")
        self.assertEqual(response.status_code, 200)

    def test_search_with_parameter(self):
        """Test search redirect with parameter substitution"""
        response = self.client.get("/search/", {"q": "g django tutorial"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "https://www.google.com/search?q=django%20tutorial"
        )

    def test_search_with_unicode_parameter(self):
        """Test search redirect percent-encodes Unicode query parameters."""
        response = self.client.get("/search/", {"q": "g canción romántica"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://www.google.com/search?q=canci%C3%B3n%20rom%C3%A1ntica",
        )

    def test_search_without_parameter(self):
        """Test search redirect for bookmark without parameters"""
        response = self.client.get("/search/", {"q": "gh"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://github.com")

    def test_search_missing_required_parameter(self):
        """Test that bookmarks requiring parameters fail without them"""
        response = self.client.get("/search/", {"q": "pr"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "requires parameter(s):", status_code=400)

    def test_search_nonexistent_bookmark(self):
        """Test that unmatched queries fall back to Google search"""
        response = self.client.get("/search/", {"q": "nonexistent query"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://www.google.com/search?q=nonexistent%20query",
        )

    def test_search_printer_shortcut(self):
        """Test printer shortcut redirect"""
        Bookmark.objects.create(
            key="printer",
            description="House printer",
            url="http://printer.house.hcma",
        )
        response = self.client.get("/search/", {"q": "printer"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://printer.house.hcma")

    def test_search_sony_shortcut(self):
        """Test sony shortcut redirect"""
        Bookmark.objects.create(
            key="sony",
            description="Sony TV",
            url="http://sony.house.hcma",
        )
        response = self.client.get("/search/", {"q": "sony"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://sony.house.hcma")

    def test_search_direct_url_http(self):
        """Test that http(s) URLs are passed through directly"""
        response = self.client.get("/search/", {"q": "http://example.com/path"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://example.com/path")

    def test_search_direct_url_https(self):
        """Test that https URLs are passed through directly"""
        response = self.client.get("/search/", {"q": "https://example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com")

    def test_direct_bookmark_redirect(self):
        """Test direct URL redirect via /key/"""
        response = self.client.get("/gh/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://github.com")

    def test_direct_bookmark_redirect_encodes_query_parameter(self):
        """Test direct URL redirect encodes query parameters before redirecting."""
        response = self.client.get("/g/", {"search_terms": "café con leche"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://www.google.com/search?q=caf%C3%A9%20con%20leche",
        )

    def test_help_command(self):
        """Test that 'h' redirects to list page"""
        response = self.client.get("/search/", {"q": "h"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/list/", response["Location"])

    def test_api_autocomplete(self):
        """Test API suggestions endpoint (OpenSearch format)"""
        response = self.client.get("/api/suggestions/", {"q": "g"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # OpenSearch format: [query, [suggestions], [descriptions], [urls]]
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0], "g")  # Query echo
        suggestions = data[1]
        # Should include 'g' and 'gh'
        self.assertIn("g", suggestions)
        self.assertIn("gh", suggestions)

    def test_opensearch_xml_loads(self):
        """Test that OpenSearch XML description loads"""
        response = self.client.get("/opensearch.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "application/opensearchdescription+xml"
        )

    def test_bookmark_model_str(self):
        """Test bookmark model string representation"""
        bookmark = Bookmark.objects.get(key="g")
        self.assertEqual(str(bookmark), "g: Google Search")

    def test_bookmark_ordering(self):
        """Test that bookmarks are ordered by key"""
        bookmarks = list(Bookmark.objects.all())
        keys = [b.key for b in bookmarks]
        self.assertEqual(keys, sorted(keys))

    def test_multi_param_with_default(self):
        """Test multi-parameter bookmark with default value"""
        response = self.client.get("/search/", {"q": "pr 12345"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://github.com/default-org/default-repo/pull/12345",
        )

    def test_multi_param_override_default(self):
        """Test multi-parameter bookmark overriding default"""
        response = self.client.get("/search/", {"q": "pr Shopify/shopify-build 12345"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "https://github.com/Shopify/shopify-build/pull/12345"
        )

    def test_issue_shortcut_redirect(self):
        """Test GitHub issue bookmark parameter substitution"""
        Bookmark.objects.create(
            key="i",
            description="GitHub Issue",
            url="https://github.com/#{repo}/issues/#{issue_number}",
        )
        response = self.client.get("/search/", {"q": "i the-hcma/bunnify 42"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "https://github.com/the-hcma/bunnify/issues/42"
        )

    def test_org_issues_list_shortcut(self):
        """Test org-scoped issues list bookmark (ih)"""
        Bookmark.objects.create(
            key="ih",
            description="the-hcma GitHub Issues",
            url="https://github.com/the-hcma/#{repo}/issues",
        )
        response = self.client.get("/search/", {"q": "ih bunnify"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "https://github.com/the-hcma/bunnify/issues"
        )

    def test_single_token_placeholder_rejects_extra_args(self):
        """``prh repo 476`` must not glue extras into ``#{repo}`` (broken %20 URL)."""
        Bookmark.objects.create(
            key="prh",
            description="the-hcma GitHub Pull Requests",
            url="https://github.com/the-hcma/#{repo}/pulls",
        )
        response = self.client.get("/search/", {"q": "prh repository-helpers 476"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "Too many parameters for bookmark 'prh'", status_code=400
        )
        self.assertContains(response, "Usage: prh <repo>", status_code=400)

    def test_zero_arg_shortcut_rejects_extra_args(self):
        response = self.client.get("/search/", {"q": "gh extra"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "Too many parameters for bookmark 'gh'", status_code=400
        )
        self.assertContains(response, "Usage: gh", status_code=400)

    def test_multi_param_rejects_extra_args_with_usage(self):
        response = self.client.get("/search/", {"q": "pr org/repo 1 leftover"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "Too many parameters for bookmark 'pr'", status_code=400
        )
        self.assertContains(response, "Usage: pr [repo] <pr_number>", status_code=400)

    def test_single_token_placeholder_accepts_one_arg(self):
        Bookmark.objects.create(
            key="prh",
            description="the-hcma GitHub Pull Requests",
            url="https://github.com/the-hcma/#{repo}/pulls",
        )
        response = self.client.get("/search/", {"q": "prh repository-helpers"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://github.com/the-hcma/repository-helpers/pulls",
        )

    def test_health_check_loads(self):
        """Test that the health check endpoint loads successfully"""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok")
        self.assertEqual(response["Content-Type"], "text/plain")

    def test_health_check_json_includes_version_and_commit(self):
        """JSON clients receive version/commit alongside status."""
        package, commit = get_build_info()
        response = self.client.get("/health", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], package)
        self.assertEqual(payload["commit"], commit)

    def test_same_placeholder_path_and_query_encoding(self):
        """Same placeholder in path vs query uses per-occurrence encoding."""
        Bookmark.objects.create(
            key="dual",
            description="Path and query reuse",
            url="https://example.com/#{phrase}?q=#{phrase}",
        )
        response = self.client.get("/search/", {"q": "dual a/b c"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "https://example.com/a/b%20c?q=a%2Fb%20c",
        )
