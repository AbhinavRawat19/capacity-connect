from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_payment_source_payment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paypalwebhookevent',
            name='status',
            field=models.CharField(default='processed', max_length=32),
        ),
    ]
