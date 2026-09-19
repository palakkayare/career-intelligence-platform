"""
Recording a job search.

Every request used to write its own row, so one person narrowing a search
left a trail instead of a memory: "backend developer", then the same words
with a city, then the same search with On-site, Hybrid and Remote tried in
turn - five rows for one piece of work, and the ten-row history filled with
a single afternoon.

A search is treated as a continuation of the previous one, and updates it in
place, when it arrives soon after and is recognisably the same work:

  * exactly the same query and filters (the person paged, or came back);
  * the same filters and a query that extends the previous one (typing);
  * the same query with different filters (narrowing what was just searched).

Anything else is a new search and gets its own row.
"""

from datetime import timedelta

from django.utils import timezone

from .models import SearchHistory

# How long a search stays "the one I am working on". Long enough to cover
# reading a page of results and trying another filter; short enough that
# tomorrow's search for the same words is its own row.
CONTINUATION_WINDOW = timedelta(minutes=15)


def _continues(previous, query_text, filters):
    """Is this the same piece of work as `previous`?"""
    same_query = previous.query_text == query_text
    same_filters = previous.filters == filters

    if same_query and same_filters:
        return True
    if same_filters and query_text and previous.query_text:
        # Typing: "back" → "backend developer". Either direction, because a
        # person also deletes words to widen a search.
        return query_text.startswith(previous.query_text) or previous.query_text.startswith(
            query_text
        )
    if same_query:
        # Same words, different filters: narrowing the same search.
        return True
    return False


def record_search(user, query_text, filters, result_count, now=None):
    """
    Store a search for this user, collapsing it into the previous one when it
    is a continuation. Returns the row, or None when there was nothing worth
    recording.
    """
    query_text = (query_text or "").strip()
    filters = filters or {}

    if not query_text and not filters:
        return None

    now = now or timezone.now()
    previous = SearchHistory.objects.filter(user=user).order_by("-created_at").first()

    if (
        previous
        and now - previous.created_at <= CONTINUATION_WINDOW
        and _continues(previous, query_text, filters)
    ):
        # Keep the latest state of the search, not the first keystroke of it.
        previous.query_text = query_text
        previous.filters = filters
        previous.result_count = result_count
        previous.created_at = now
        previous.save(update_fields=["query_text", "filters", "result_count", "created_at"])
        return previous

    row = SearchHistory.objects.create(
        user=user,
        query_text=query_text,
        filters=filters,
        result_count=result_count,
    )
    _prune(user)
    return row


def _prune(user):
    """Keep only the most recent MAX_PER_USER rows."""
    cutoff = (
        SearchHistory.objects.filter(user=user)
        .order_by("-created_at")
        .values_list("id", flat=True)[SearchHistory.MAX_PER_USER :]
    )
    SearchHistory.objects.filter(id__in=list(cutoff)).delete()
