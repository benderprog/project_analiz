from apps.analysis_app.portal_db_runtime import apply_portal_db_settings


class PortalDbRuntimeSettingsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        apply_portal_db_settings()
        return self.get_response(request)
