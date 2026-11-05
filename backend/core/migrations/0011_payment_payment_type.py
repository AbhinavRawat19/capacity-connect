from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0010_trainer_payout_workflow'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='payment_type',
            field=models.CharField(
                choices=[('purchase', 'Course purchase'), ('reinstatement', 'Refund repayment')],
                default='purchase',
                max_length=16,
            ),
        ),
    ]
