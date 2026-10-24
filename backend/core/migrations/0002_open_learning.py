from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

def approve_existing_accounts(apps, schema_editor):
    User = apps.get_model('core', 'User')
    User.objects.filter(role__in=['trainee', 'trainer']).update(is_approved=True)

class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [
        migrations.RunPython(approve_existing_accounts, migrations.RunPython.noop),
        migrations.CreateModel(
            name='CourseLesson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('description', models.TextField(blank=True)),
                ('position', models.PositiveIntegerField(default=1)),
                ('video_url', models.URLField(blank=True)),
                ('video_file', models.FileField(blank=True, null=True, upload_to='lectures/%Y/%m/')),
                ('resource_file', models.FileField(blank=True, null=True, upload_to='resources/%Y/%m/')),
                ('duration_minutes', models.PositiveIntegerField(default=0)),
                ('is_preview', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lessons', to='core.course')),
            ],
            options={'ordering': ['position', 'id']},
        ),
        migrations.CreateModel(
            name='Assignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('instructions', models.TextField()),
                ('due_at', models.DateTimeField(blank=True, null=True)),
                ('max_score', models.PositiveIntegerField(default=100)),
                ('attachment', models.FileField(blank=True, null=True, upload_to='assignments/%Y/%m/')),
                ('is_published', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='core.course')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['due_at', '-created_at']},
        ),
        migrations.CreateModel(
            name='AssignmentSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('response_text', models.TextField(blank=True)),
                ('submission_url', models.URLField(blank=True)),
                ('attachment', models.FileField(blank=True, null=True, upload_to='assignment_submissions/%Y/%m/')),
                ('status', models.CharField(choices=[('submitted', 'Submitted'), ('reviewed', 'Reviewed'), ('revision', 'Revision requested')], default='submitted', max_length=12)),
                ('score', models.PositiveIntegerField(blank=True, null=True)),
                ('feedback', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='core.assignment')),
                ('learner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignment_submissions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-submitted_at']},
        ),
        migrations.CreateModel(
            name='CourseDiscussion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(max_length=5000)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='course_discussions', to=settings.AUTH_USER_MODEL)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='discussion_posts', to='core.course')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='assignmentsubmission',
            constraint=models.UniqueConstraint(fields=('assignment', 'learner'), name='unique_assignment_submission_per_learner'),
        ),
    ]
