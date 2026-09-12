"""
Schema extensions for drf-spectacular.

Imported from CoreConfig.ready() - an extension has to be imported to register
itself, and without this one every endpoint is documented as unauthenticated
and Swagger UI has no Authorize button.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ObservedJWTScheme(OpenApiAuthenticationExtension):
    """
    ObservedJWTAuthentication is SimpleJWT's class plus Sentry context, so it
    is documented exactly as bearer JWT.
    """

    target_class = "apps.core.authentication.ObservedJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
