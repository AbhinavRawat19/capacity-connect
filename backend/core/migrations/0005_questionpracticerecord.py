# Generated for Question Bank practice persistence and leaderboard scoring.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('core', '0004_alter_user_managers'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='QuestionPracticeRecord', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('submitted_answer', models.PositiveSmallIntegerField()),
        ('is_correct', models.BooleanField(default=False)),
        ('points_earned', models.PositiveIntegerField(default=0)),
        ('first_correct_at', models.DateTimeField(blank=True, null=True)),
        ('updated_at', models.DateTimeField(auto_now=True)),
        ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='practice_records', to='core.questionsubmission')),
        ('trainee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='question_practice_records', to=settings.AUTH_USER_MODEL)),
    ], options={'ordering': ['-updated_at']}),
        migrations.AddConstraint(model_name='questionpracticerecord', constraint=models.UniqueConstraint(fields=('trainee','question'), name='unique_learner_question_practice')),
    ]
