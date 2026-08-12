from django.conf import settings

from .models import Brand


class BrandContextMiddleware:
    """
    Определяет текущий бренд по доменному имени.

    Примеры:
        guinot.example.ru -> Guinot
        rhea.example.ru   -> Rhea

    Для внутренней разработки используется
    DEFAULT_BRAND_ID.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = (
            request.get_host()
            .split(":")[0]
            .lower()
        )

        site = settings.BRAND_SITES.get(host)

        if site:
            brand_id = site["brand_id"]
            request.brand_site = site
        else:
            brand_id = settings.DEFAULT_BRAND_ID

            request.brand_site = {
                "code": "default",
                "brand_id": brand_id,
                "title": "Order Service",
                "theme": "default",
            }

        request.brand = (
            Brand.objects
            .filter(
                brand_id=brand_id,
                is_active=True,
            )
            .first()
        )

        return self.get_response(request)