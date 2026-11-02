from django.core.management.base import BaseCommand

from sales.services.notifications.processor import (
    process_order_notifications,
)


class Command(BaseCommand):
    help = "Обработка очереди уведомлений о заказах"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if limit < 1:
            raise ValueError("limit должен быть больше нуля")

        processed = process_order_notifications(limit=limit)

        self.stdout.write(
            self.style.SUCCESS(
                f"Обработано уведомлений: {processed}"
            )
        )