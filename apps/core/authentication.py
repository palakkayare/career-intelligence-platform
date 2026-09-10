"""
JWT authentication that tells Sentry whose request failed.

This cannot live in Django middleware. DRF authenticates inside the view, so
while any middleware's request phase runs, request.user is still anonymous
for every token-authenticated call. Tagging here is the first moment the
user is known.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from .observability import tag_user


class ObservedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            tag_user(result[0])
        return result
