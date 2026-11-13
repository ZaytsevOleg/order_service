
import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models, transaction, close_old_connections
from sales.models import OrderSyncTask
from sales.services.onec_order_sync import sync_order_to_onec


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 60
STALE_AFTER_MINUTES = 15



def recover_stale_tasks():
    """
    Восстанавливает задачи синхронизации с 1С,
    прерванные при остановке единственного worker.

    Вызывается один раз при запуске worker.
    """
    now = timezone.now()
    recovered_count = 0

    with transaction.atomic():
        tasks = (
            OrderSyncTask.objects
            .select_for_update(skip_locked=True)
            .filter(
                status=OrderSyncTask.STATUS_PROCESSING,
            )
        )

        for task in tasks:
            task.status = OrderSyncTask.STATUS_FAILED

            if task.attempts < MAX_ATTEMPTS:
                task.next_retry_at = now
            else:
                task.next_retry_at = None

            task.last_error = (
                "Предыдущая обработка была прервана. "
                "Задача восстановлена после перезапуска worker."
            )

            task.finished_at = now

            task.save(
                update_fields=[
                    "status",
                    "next_retry_at",
                    "last_error",
                    "finished_at",
                ]
            )

            recovered_count += 1

    if recovered_count:
        logger.warning(
            "Восстановлено прерванных задач синхронизации: %s",
            recovered_count,
        )

    return recovered_count



def claim_task():
    """
    Атомарно забираем одну задачу.
    """
    now = timezone.now()

    with transaction.atomic():
        task = (
            OrderSyncTask.objects
            .select_for_update(skip_locked=True)
            .filter(
                status__in=[
                    OrderSyncTask.STATUS_PENDING,
                    OrderSyncTask.STATUS_FAILED,
                ],
                attempts__lt=MAX_ATTEMPTS,
            )
            .filter(
                models.Q(next_retry_at__isnull=True)
                | models.Q(next_retry_at__lte=now)
            )
            .order_by("created_at")
            .first()
        )

        if task is None:
            return None

        task.status = OrderSyncTask.STATUS_PROCESSING
        task.attempts += 1
        task.started_at = now
        task.last_error = ""
        task.save(
            update_fields=[
                "status",
                "attempts",
                "started_at",
                "last_error",
            ]
        )

        return task.pk


def process_task(task_id):
    task = OrderSyncTask.objects.get(pk=task_id)

    try:
        sync_order_to_onec(task.order_id)

    except Exception as exc:
        logger.exception(
            "Ошибка синхронизации заказа %s",
            task.order_id,
        )

        task.status = OrderSyncTask.STATUS_FAILED
        task.last_error = str(exc)

        if task.attempts < MAX_ATTEMPTS:
            task.next_retry_at = (
                timezone.now()
                + timedelta(seconds=RETRY_DELAY_SECONDS)
            )
        else:
            task.next_retry_at = None

        task.finished_at = timezone.now()

        task.save(
            update_fields=[
                "status",
                "last_error",
                "next_retry_at",
                "finished_at",
            ]
        )

    else:
        task.status = OrderSyncTask.STATUS_SUCCESS
        task.last_error = ""
        task.next_retry_at = None
        task.finished_at = timezone.now()

        task.save(
            update_fields=[
                "status",
                "last_error",
                "next_retry_at",
                "finished_at",
            ]
        )

        logger.info(
            "Заказ %s успешно синхронизирован",
            task.order_id,
        )


class Command(BaseCommand):
    help = "Фоновая синхронизация заказов с 1С"

    def handle(self, *args, **options):
        self.stdout.write(
            "Worker синхронизации с 1С запущен"
        )

        close_old_connections()
        recover_stale_tasks()

        while True:
            close_old_connections()

            task_id = claim_task()

            if task_id is not None:
                process_task(task_id)
            else:
                time.sleep(2)
