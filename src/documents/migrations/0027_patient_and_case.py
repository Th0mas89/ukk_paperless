import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0026_alter_document_archive_checksum_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Patient",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "pid",
                    models.CharField(
                        db_index=True,
                        help_text="Eindeutige Patienten-Identifikationsnummer",
                        max_length=64,
                        unique=True,
                        verbose_name="Patienten-ID (PID)",
                    ),
                ),
                (
                    "first_name",
                    models.CharField(max_length=128, verbose_name="Vorname"),
                ),
                (
                    "last_name",
                    models.CharField(max_length=128, verbose_name="Nachname"),
                ),
                (
                    "date_of_birth",
                    models.DateField(verbose_name="Geburtsdatum"),
                ),
            ],
            options={
                "verbose_name": "Patient",
                "verbose_name_plural": "Patienten",
                "ordering": ("last_name", "first_name"),
            },
        ),
        migrations.CreateModel(
            name="Case",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "case_number",
                    models.CharField(
                        db_index=True,
                        help_text="Eindeutige Fallnummer",
                        max_length=64,
                        unique=True,
                        verbose_name="Fallnummer",
                    ),
                ),
                (
                    "case_start",
                    models.DateTimeField(verbose_name="Fallstart"),
                ),
                (
                    "case_end",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Fallende",
                    ),
                ),
                (
                    "organizational_unit",
                    models.CharField(
                        blank=True,
                        max_length=128,
                        verbose_name="Organisationseinheit",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cases",
                        to="documents.patient",
                        to_field="pid",
                        verbose_name="Patient (PID)",
                    ),
                ),
            ],
            options={
                "verbose_name": "Fall",
                "verbose_name_plural": "Fälle",
                "ordering": ("-case_start",),
            },
        ),
    ]
