from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0009_withdrawnenrollment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='payout', name='status',
            field=models.CharField(choices=[('pending', 'Pending approval'), ('approved', 'Approved'), ('processing', 'Processing'), ('completed', 'Completed'), ('rejected', 'Rejected'), ('failed', 'Failed')], default='pending', max_length=12),
        ),
        migrations.AddField(model_name='payout', name='sender_batch_id', field=models.CharField(blank=True, max_length=80, null=True, unique=True)),
        migrations.AddField(model_name='payout', name='rejection_reason', field=models.CharField(blank=True, max_length=500)),
        migrations.AddField(model_name='payout', name='failure_reason', field=models.CharField(blank=True, max_length=1000)),
        migrations.AddField(model_name='payout', name='processed_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='processed_course_payouts', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='payout', name='updated_at', field=models.DateTimeField(auto_now=True)),
    ]
