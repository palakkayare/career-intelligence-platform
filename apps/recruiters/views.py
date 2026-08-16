from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, serializers
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Company, RecruiterProfile
from .permissions import IsRecruiter, IsCompanyAdminOrReadOnly
from .serializers import (
    CompanyListSerializer,
    CompanyDetailSerializer,
    CompanyLogoSerializer,
    RecruiterProfileSerializer,
    RecruiterProfileUpdateSerializer,
)


class CompanyListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/companies/  ← Anyone authenticated
    POST /api/v1/companies/  ← Recruiters only
    """

    def get_serializer_class(self):
        return CompanyListSerializer if self.request.method == 'GET' else CompanyDetailSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsRecruiter()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = Company.objects.select_related('industry').filter(is_deleted=False)

        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(name__icontains=q)

        industry_id = self.request.query_params.get('industry')
        if industry_id:
            qs = qs.filter(industry_id=industry_id)

        verified_only = self.request.query_params.get('verified') == 'true'
        if verified_only:
            qs = qs.filter(is_verified=True)

        return qs.order_by('-is_verified', 'name')

    def perform_create(self, serializer):
        # Recruiter must NOT already be in a company (Phase 1 rule)
        recruiter = self.request.user.recruiter_profile
        if recruiter.company_id:
            raise serializers.ValidationError({
                'detail': 'You are already part of a company. Leave it first.'
            })

        company = serializer.save(created_by=self.request.user)

        # Creator becomes company admin
        recruiter.company = company
        recruiter.is_company_admin = True
        recruiter.save(update_fields=['company', 'is_company_admin'])
        
class CompanyDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/companies/<id>/  ← Anyone authenticated
    PATCH /api/v1/companies/<id>/  ← Company admin only
    """
    queryset = Company.objects.select_related('industry').filter(is_deleted=False)
    serializer_class = CompanyDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]


class CompanyLogoView(APIView):
    """POST /api/v1/companies/<id>/logo/"""
    permission_classes = [IsRecruiter, IsCompanyAdminOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        company = get_object_or_404(Company, pk=pk, is_deleted=False)
        self.check_object_permissions(request, company)

        serializer = CompanyLogoSerializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'logo': company.logo.url if company.logo else None,
        })


class CompanyTeamView(generics.ListAPIView):
    """GET /api/v1/companies/<id>/team/ ← List recruiters in this company."""
    serializer_class = RecruiterProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        company_id = self.kwargs['pk']
        return (
            RecruiterProfile.objects
            .select_related('user', 'company')
            .filter(company_id=company_id, is_deleted=False)
            .order_by('-is_company_admin', 'full_name')
        )

    def get_serializer_context(self):
        return {'request': self.request}
    
class CompanyJoinView(APIView):
    """
    POST /api/v1/companies/<id>/join/
    Recruiter (not in any company) joins this company.
    Phase 1: no approval flow — direct join. Phase 2 mein add karenge.
    """
    permission_classes = [IsRecruiter]

    def post(self, request, pk):
        company = get_object_or_404(Company, pk=pk, is_deleted=False)
        recruiter = request.user.recruiter_profile

        if recruiter.company_id:
            return Response(
                {'error': 'You are already part of a company. Leave first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recruiter.company = company
        recruiter.is_company_admin = False  # Joining → not admin
        recruiter.save(update_fields=['company', 'is_company_admin'])

        return Response({
            'message': f'Joined {company.name} successfully.',
            'company': CompanyListSerializer(company).data,
        })


class CompanyLeaveView(APIView):
    """POST /api/v1/companies/<id>/leave/"""
    permission_classes = [IsRecruiter]

    def post(self, request, pk):
        recruiter = request.user.recruiter_profile

        if recruiter.company_id != int(pk):
            return Response(
                {'error': 'You are not part of this company.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If admin, ensure another admin exists OR transfer/dissolve
        if recruiter.is_company_admin:
            other_admins = RecruiterProfile.objects.filter(
                company_id=pk,
                is_company_admin=True,
                is_deleted=False,
            ).exclude(id=recruiter.id).count()

            if other_admins == 0:
                return Response({
                    'error': (
                        'You are the only admin. '
                        'Promote another member first or contact support.'
                    )
                }, status=status.HTTP_400_BAD_REQUEST)

        recruiter.company = None
        recruiter.is_company_admin = False
        recruiter.save(update_fields=['company', 'is_company_admin'])

        return Response({'message': 'Left the company.'})
    
class CompanyMemberPromoteView(APIView):
    """
    POST /api/v1/companies/<pk>/members/<recruiter_id>/promote/
    Company admin promotes a member to admin.
    """
    permission_classes = [IsRecruiter]

    def post(self, request, pk, recruiter_id):
        actor = request.user.recruiter_profile

        if actor.company_id != int(pk) or not actor.is_company_admin:
            return Response(
                {'error': 'Only company admins can promote members.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        target = get_object_or_404(
            RecruiterProfile,
            id=recruiter_id,
            company_id=pk,
            is_deleted=False,
        )
        target.is_company_admin = True
        target.save(update_fields=['is_company_admin'])

        return Response({'message': f'{target.full_name} promoted to admin.'})


class CompanyMemberRemoveView(APIView):
    """
    POST /api/v1/companies/<pk>/members/<recruiter_id>/remove/
    Company admin removes a member from the company.
    """
    permission_classes = [IsRecruiter]

    def post(self, request, pk, recruiter_id):
        actor = request.user.recruiter_profile

        if actor.company_id != int(pk) or not actor.is_company_admin:
            return Response(
                {'error': 'Only company admins can remove members.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if actor.id == int(recruiter_id):
            return Response(
                {'error': 'Use /leave/ to remove yourself.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target = get_object_or_404(
            RecruiterProfile,
            id=recruiter_id,
            company_id=pk,
            is_deleted=False,
        )
        target.company = None
        target.is_company_admin = False
        target.save(update_fields=['company', 'is_company_admin'])

        return Response({'message': 'Member removed.'})
    
class MyRecruiterProfileView(generics.RetrieveUpdateAPIView):
    """GET, PATCH /api/v1/recruiters/me/"""
    permission_classes = [IsRecruiter]

    def get_object(self):
        return self.request.user.recruiter_profile

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return RecruiterProfileSerializer
        return RecruiterProfileUpdateSerializer

    def get_serializer_context(self):
        return {'request': self.request}


class PublicRecruiterProfileView(generics.RetrieveAPIView):
    """GET /api/v1/recruiters/<public_id>/"""
    serializer_class = RecruiterProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'user__public_id'
    lookup_url_kwarg = 'public_id'

    def get_queryset(self):
        return RecruiterProfile.objects.select_related('user', 'company')

    def get_serializer_context(self):
        return {'request': self.request}