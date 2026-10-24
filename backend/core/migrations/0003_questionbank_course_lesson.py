from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('core', '0002_open_learning')]
    operations = [
        migrations.AddField(model_name='questionsubmission', name='course', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='question_bank_items', to='core.course')),
        migrations.AddField(model_name='questionsubmission', name='lesson', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='question_bank_items', to='core.courselesson')),
    ]
