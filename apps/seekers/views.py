from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SeekerProfile
from .permissions import CanViewProfile, IsSeeker
from .serializers import (
    EducationSerializer,
    PhotoUploadSerializer,
    SeekerProfileSerializer,
    SeekerSkillSerializer,
    WorkExperienceSerializer,
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
            SeekerProfile.objects.select_related("user")
            .prefetch_related(
                "seeker_skills__skill",
                "experiences__skills_used",
                "educations",
            )
            .get(user=self.request.user)
        )


class PublicProfileView(generics.RetrieveAPIView):
    """
    GET /api/v1/seekers/<public_id>/  — view someone else's profile
    """

    serializer_class = SeekerProfileSerializer
    permission_classes = [permissions.IsAuthenticated, CanViewProfile]
    lookup_field = "user__public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return SeekerProfile.objects.select_related("user")


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
        return Response(
            {"profile_photo": (profile.profile_photo.url if profile.profile_photo else None)}
        )


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
        return self.request.user.seeker_profile.seeker_skills.select_related("skill")

    def perform_create(self, serializer):
        serializer.save(seeker=self.request.user.seeker_profile)


class SkillDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SeekerSkillSerializer
    permission_classes = [IsSeeker]

    def get_queryset(self):
        return self.request.user.seeker_profile.seeker_skills.all()


class SkillEndorsementView(APIView):
    """
    POST   /api/v1/seekers/skills/<int:pk>/endorse/   - vouch for a skill
    DELETE /api/v1/seekers/skills/<int:pk>/endorse/   - take it back

    Any authenticated user can endorse any discoverable seeker's skill,
    except their own. Blueprint Feature 12.
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_skill(self, pk):
        from .models import SeekerSkill

        return get_object_or_404(
            SeekerSkill.objects.select_related("seeker", "seeker__user", "skill"),
            pk=pk,
            seeker__is_deleted=False,
        )

    def post(self, request, pk):
        from .services import SkillEndorsementService

        seeker_skill = self._get_skill(pk)
        _, created = SkillEndorsementService.endorse(seeker_skill, request.user)
        seeker_skill.refresh_from_db()

        return Response(
            {
                "skill": seeker_skill.skill.name,
                "endorsement_count": seeker_skill.endorsement_count,
                "endorsed": True,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        from .services import SkillEndorsementService

        seeker_skill = self._get_skill(pk)
        removed = SkillEndorsementService.withdraw(seeker_skill, request.user)

        if not removed:
            return Response(
                {"detail": "You have not endorsed this skill."},
                status=status.HTTP_404_NOT_FOUND,
            )

        seeker_skill.refresh_from_db()
        return Response(
            {
                "skill": seeker_skill.skill.name,
                "endorsement_count": seeker_skill.endorsement_count,
                "endorsed": False,
            }
        )
