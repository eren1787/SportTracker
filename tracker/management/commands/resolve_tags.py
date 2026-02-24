from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Süresi dolan meydan okumaları çöz ve ceza uygula"

    def handle(self, *args, **options):
        from tracker.services import expire_overdue_tags
        count = expire_overdue_tags()
        self.stdout.write(f"{count} meydan okuma süresi doldu, cezalar uygulandı.")
