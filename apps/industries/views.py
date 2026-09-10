from django.db.models import Q
from rest_framework import generics, permissions

from .models import Industry
from .serializers import IndustrySerializer


class IndustryListView(generics.ListAPIView):
    """GET /api/v1/industries/?q=..."""

    serializer_class = IndustrySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Industry.objects.filter(is_active=True)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(aliases__icontains=q))
        return qs[:50]
