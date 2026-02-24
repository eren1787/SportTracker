from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Haftanın sonunda 10 puan altındaki oyunculara ceza uygula"

    def add_arguments(self, parser):
        parser.add_argument(
            "--week",
            type=int,
            required=True,
            help="Sezon içinde hafta numarası (1 veya 2)",
        )

    def handle(self, *args, **options):
        from tracker.models import Season
        from tracker.services import apply_weekly_penalties

        season = Season.objects.filter(is_active=True).first()
        if not season:
            self.stderr.write("Aktif sezon bulunamadı.")
            return

        apply_weekly_penalties(season, options["week"])
        self.stdout.write(f"Hafta {options['week']} cezaları uygulandı.")
