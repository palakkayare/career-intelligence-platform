from django.db.models import Q
from rest_framework import generics, permissions

from .models import Skill
from .serializers import SkillSerializer


class SkillListView(generics.ListAPIView):
    """
    GET /api/v1/skills/
    Optional: ?q=python (search), ?category=programming
    """

    serializer_class = SkillSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Skills list small enough for autocomplete

    def get_queryset(self):
        qs = Skill.objects.filter(is_approved=True, is_deprecated=False)

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(aliases__icontains=q))

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        return qs[:50]  # Cap at 50 results
