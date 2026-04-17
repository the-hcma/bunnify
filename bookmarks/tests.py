from django.test import Client, TestCase
from django.urls import reverse

from .models import Bookmark


class SmokeTests(TestCase):
    """Smoke tests to ensure core functionality works"""

    def setUp(self):
        """Set up test fixtures"""
        self.client = Client()

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
            response["Location"], "https://www.google.com/search?q=django tutorial"
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
        """Test that searching for nonexistent bookmark returns 404"""
        response = self.client.get("/search/", {"q": "nonexistent"})
        self.assertEqual(response.status_code, 404)

    def test_direct_bookmark_redirect(self):
        """Test direct URL redirect via /key/"""
        response = self.client.get("/gh/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://github.com")

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

    def test_health_check_loads(self):
        """Test that the health check endpoint loads successfully"""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok")
        self.assertEqual(response["Content-Type"], "text/plain")
