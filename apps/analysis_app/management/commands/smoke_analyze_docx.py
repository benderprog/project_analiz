from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analysis_app.services import extract_attributes, match_event, parse_docx
from apps.analysis_app.utils.dt_display import format_local_naive


class Command(BaseCommand):
    help = "Run DOCX analysis pipeline and print a short paragraph summary."

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True, help="Path to DOCX file")

    def handle(self, *args, **options):
        docx_path = Path(options["path"]).expanduser()
        if not docx_path.exists():
            raise CommandError(f"DOCX file not found: {docx_path}")

        try:
            paragraphs = parse_docx(str(docx_path))
            if not paragraphs:
                self.stdout.write("No event paragraphs found after filtering.")
                return

            for idx, text in enumerate(paragraphs, start=1):
                attributes = extract_attributes(text)
                match_result = match_event(attributes, text)
                date_label = format_local_naive(attributes.date_time) or "<none>"
                subdivision_label = attributes.subdivision_name or "<none>"
                matched_label = "yes" if match_result.get("matched") else "no"
                self.stdout.write(
                    f"#{idx}: date={date_label} subdivision={subdivision_label} matched={matched_label}"
                )
        except Exception as exc:  # noqa: BLE001 - ensure non-zero exit
            raise CommandError(f"Smoke analyze failed: {exc}")
