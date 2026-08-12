from django.templatetags.static import static


def brand_context(request):
    site = getattr(
        request,
        "brand_site",
        None,
    ) or {}

    code = site.get(
        "code",
        "default",
    )

    if code == "guinot":
        return {
            "brand_code": "guinot",
            "brand_title": "Guinot",
            "brand_theme_css": "orders/themes/guinot.css",
            "brand_logo": "orders/img/guinot/logo.png",
            "brand_favicon": "orders/img/guinot/favicon.png",
        }

    if code == "rhea":
        return {
            "brand_code": "rhea",
            "brand_title": "Rhea Cosmetics",
            "brand_theme_css": "orders/themes/rhea.css",
            "brand_logo": "orders/img/rhea/logo.png",
            "brand_favicon": "orders/img/rhea/favicon.png",
        }

    return {
        "brand_code": "default",
        "brand_title": "Order Service",
        "brand_theme_css": "orders/themes/default.css",
        "brand_logo": "",
        "brand_favicon": "",
    }