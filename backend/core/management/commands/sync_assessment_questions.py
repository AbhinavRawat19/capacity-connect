from django.core.management.base import BaseCommand
from core.models import Assessment
from core.views import sync_assessment_questions_to_bank


class Command(BaseCommand):
    help = 'Synchronize existing assessment questions into the approved Question Bank.'

    def handle(self, *args, **options):
        count = 0
        for assessment in Assessment.objects.select_related('course', 'created_by').all().iterator():
            before = assessment.questions or []
            sync_assessment_questions_to_bank(assessment)
            assessment.refresh_from_db(fields=['questions'])
            if assessment.questions != before:
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Synchronized Question Bank links for {count} assessment(s).'))
