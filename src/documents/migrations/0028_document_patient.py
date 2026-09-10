import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0027_patient_and_case"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="patient",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="documents.patient",
                verbose_name="Patient",
            ),
        ),
    ]
