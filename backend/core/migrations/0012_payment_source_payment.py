# Scope each refund repayment to the original purchase it restores.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0011_payment_payment_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='source_payment',
            field=models.ForeignKey(
                blank=True,
                help_text='Original purchase whose refunded amount this reinstatement repays.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='reinstatement_payments',
                to='core.payment',
            ),
        ),
    ]
