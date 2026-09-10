import logging
import random
import uuid
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from documents.models import Case
from documents.models import Patient

logger = logging.getLogger("paperless.management.seed_patients")

DEFAULT_OES = ["Station A", "Station B", "Station C"]

# `faker` is a testing-only dependency (see pyproject.toml) and is not
# installed in the production image, so demo names are generated from a
# small built-in pool instead.
FIRST_NAMES = [
    "Anna", "Ben", "Clara", "David", "Emma", "Felix", "Greta", "Hannes",
    "Ida", "Jonas", "Katharina", "Lukas", "Mia", "Noah", "Olivia", "Paul",
    "Quentin", "Rosa", "Simon", "Theresa",
]
LAST_NAMES = [
    "Bauer", "Fischer", "Hoffmann", "Klein", "Koch", "Krause", "Lange",
    "Meyer", "Müller", "Neumann", "Richter", "Schmidt", "Schneider",
    "Schulz", "Schwarz", "Wagner", "Weber", "Wolf", "Zimmermann", "Vogel",
]


def _random_date_of_birth():
    today = timezone.now().date()
    age_days = random.randint(0, 95 * 365)
    return today - timedelta(days=age_days)


class Command(BaseCommand):
    help = (
        "Seeds demo Patient and Case records for testing/demo purposes.\n"
        "Ensures each organizational unit (OE) has at least the requested\n"
        "number of patients with an associated case.\n"
        "OEs default to the names of existing groups (or a small built-in\n"
        "demo list if none exist). Safe to run multiple times."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--oe",
            dest="oes",
            nargs="+",
            default=None,
            help=(
                "Names of the organizational units (OE) to seed. Defaults "
                "to the names of all existing groups, or, if none exist, "
                "to a small built-in demo list."
            ),
        )
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of patients to ensure per OE (default: 5).",
        )

    def handle(self, *args, **options) -> None:
        count: int = options["count"]
        oes: list[str] = (
            options["oes"]
            or list(Group.objects.values_list("name", flat=True))
            or DEFAULT_OES
        )

        for oe in oes:
            existing = (
                Case.objects.filter(organizational_unit=oe)
                .values("patient_id")
                .distinct()
                .count()
            )
            to_create = max(0, count - existing)

            if to_create == 0:
                self.stdout.write(
                    f"OE '{oe}': already has {existing} patient(s), skipping.",
                )
                continue

            for _ in range(to_create):
                patient = Patient.objects.create(
                    pid=f"PID-{uuid.uuid4().hex[:10].upper()}",
                    first_name=random.choice(FIRST_NAMES),
                    last_name=random.choice(LAST_NAMES),
                    date_of_birth=_random_date_of_birth(),
                )
                case_start = timezone.now() - timedelta(
                    days=random.randint(0, 30),
                )
                Case.objects.create(
                    case_number=f"F-{uuid.uuid4().hex[:10].upper()}",
                    patient=patient,
                    case_start=case_start,
                    organizational_unit=oe,
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"OE '{oe}': created {to_create} new patient(s) "
                    f"(target {count}, had {existing}).",
                ),
            )
