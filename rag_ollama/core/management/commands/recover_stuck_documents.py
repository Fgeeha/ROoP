"""
Management command: recover_stuck_documents

Marks every Document whose status is 'processing' as 'error'.

When to call:
    Called from entrypoint.sh after `migrate`, before starting Gunicorn.
    Any document stuck in 'processing' means the server was killed (OOM, power
    loss, SIGKILL) while a background indexing thread was running.  The daemon
    thread is gone; the status will never advance on its own.

Why NOT in AppConfig.ready():
    ready() runs during `manage.py migrate` and test collection — before the
    schema exists.  A management command called from entrypoint.sh runs only
    on a real server start, after migrations have been applied.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = 'Индексация прервана при перезапуске сервиса. Удалите документ и загрузите его повторно.'


class Command(BaseCommand):
    help = 'Mark documents stuck in "processing" state as "error" after a restart.'

    def handle(self, *args, **options):
        try:
            from core.models import Document

            count = Document.objects.filter(status=Document.Status.PROCESSING).update(
                status=Document.Status.ERROR,
                error_message=_ERROR_MESSAGE,
            )
        except (OperationalError, ProgrammingError) as exc:
            # Table does not exist yet (fresh install before first migration).
            self.stderr.write(f'recover_stuck_documents: skipped — {exc}')
            return

        if count:
            self.stdout.write(self.style.WARNING(f'Recovered {count} document(s) stuck in processing state.'))
            logger.warning('recover_stuck_documents: recovered %d document(s)', count)
        else:
            self.stdout.write('recover_stuck_documents: no stuck documents found.')
