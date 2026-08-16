from rest_framework import generics, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SeekerProfile
from .permissions import IsSeeker, CanViewProfile
from .serializers import (
    SeekerProfileSerializer,
    WorkExperienceSerializer,
    EducationSerializer,
    SeekerSkillSerializer,
    PhotoUploadSerializer,
)


class MyProfileView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/seekers/me/  — full nested profile
    PATCH /api/v1/seekers/me/  — update basic fields
    """
    serializer_class = SeekerProfileSerializer
    permission_classes = [IsSeeker]

    def get_object(self):
        # Profile auto-created via signal on signup.
        # Explicit queryset (instead of user.seeker_profile) so that the nested
        # skills / experiences / educations come in bulk instead of one query each.
        return (
            SeekerProfile.objects
            .select_related('user')
            .prefetch_related(
                'seeker_skills__skill',
                'experiences__skills_used',
                'educations',
            )
            .get(user=self.request.user)
        )


class PublicProfileView(generics.RetrieveAPIView):
    """
    GET /api/v1/seekers/<public_id>/  — view someone else's profile
    """
    serializer_class = SeekerProfileSerializer
    permission_classes = [permissions.IsAuthenticated, CanViewProfile]
    lookup_field = 'user__public_id'
    lookup_url_kwarg = 'public_id'

    def get_queryset(self):
        return SeekerProfile.objects.select_related('user')


class PhotoUploadView(APIView):
    """
    POST /api/v1/seekers/me/photo/ (multipart)
    """
    permission_classes = [IsSeeker]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        profile = request.user.seeker_profile
        serializer = PhotoUploadSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'profile_photo': profile.profile_photo.url if profile.profile_photo else None
        })


# ─── Sub-resource CRUD ────────────────────────────────

class WorkExperienceListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/seekers/me/experiences/
    POST /api/v1/seekers/me/experiences/
    """
    serializer_class = WorkExperienceSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.experiences.all()

    def perform_create(self, serializer):
        serializer.save(seeker=self.request.user.seeker_profile)


class WorkExperienceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/v1/seekers/me/experiences/<id>/
    """
    serializer_class = WorkExperienceSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.experiences.all()

    def perform_destroy(self, instance):
        instance.soft_delete()


class EducationListCreateView(generics.ListCreateAPIView):
    serializer_class = EducationSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.educations.all()

    def perform_create(self, serializer):
        serializer.save(seeker=self.request.user.seeker_profile)


class EducationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EducationSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.educations.all()

    def perform_destroy(self, instance):
        instance.soft_delete()


class SkillListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/seekers/me/skills/
    POST /api/v1/seekers/me/skills/
    Body: { "skill_id": 5, "proficiency": "advanced", "years_of_experience": 3 }
    """
    serializer_class = SeekerSkillSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.seeker_skills.select_related('skill')

    def perform_create(self, serializer):
        serializer.save(seeker=self.request.user.seeker_profile)


class SkillDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SeekerSkillSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.seeker_skills.all()