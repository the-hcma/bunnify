from django.db import models


class Bookmark(models.Model):
    """
    Model to store bookmarks from the JSON file
    """

    key = models.CharField(max_length=100, unique=True, db_index=True)
    description = models.TextField()
    url = models.URLField(max_length=1000)
    old_url = models.URLField(max_length=1000, blank=True, null=True)
    defaults = models.JSONField(
        default=dict, blank=True
    )  # Default values for parameters

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}: {self.description}"
