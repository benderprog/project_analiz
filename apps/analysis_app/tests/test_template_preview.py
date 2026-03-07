from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from apps.analysis_app.models import SvodkaTemplate
from apps.analysis_app.template_preview import build_template_preview_context, detect_template_anchors


class TemplateAnchorDetectorTests(SimpleTestCase):
    def test_single_segment(self):
        data = detect_template_anchors("a\n[BEGIN]\nbody\n[END]\nz")

        self.assertTrue(data.has_markers)
        self.assertEqual(len(data.segments), 1)
        self.assertEqual(len(data.markers), 2)

    def test_multiple_segments(self):
        data = detect_template_anchors("[BEGIN] A [END] x [BEGIN] B [END]")

        self.assertTrue(data.has_markers)
        self.assertEqual(len(data.segments), 2)
        self.assertEqual(len(data.markers), 4)

    def test_no_markers(self):
        data = detect_template_anchors("just text")

        self.assertFalse(data.has_markers)
        self.assertEqual(data.segments, [])
        self.assertEqual(data.markers, [])

    def test_unbalanced_markers_are_reported(self):
        data_begin = detect_template_anchors("[BEGIN] only")
        self.assertGreaterEqual(data_begin.unmatched_begin, 1)
        self.assertEqual(data_begin.unmatched_end, 0)

        data_end = detect_template_anchors("only [END]")
        self.assertEqual(data_end.unmatched_begin, 0)
        self.assertGreaterEqual(data_end.unmatched_end, 1)


class TemplatePreviewViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="staff", password="pass", is_staff=True)
        self.template = SvodkaTemplate.objects.create(
            scope=SvodkaTemplate.Scope.GENERAL,
            pu_id="",
            pu_name="Общая сводка",
            begin_marker="[BEGIN]",
            end_marker="[END]",
            is_active=True,
        )

    def test_staff_can_open_preview_and_see_highlighted_markers(self):
        self.template.file.save(
            "template.txt",
            ContentFile(b"line\n[BEGIN]\nbody\n[END]\n"),
            save=True,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("analysis-template-preview", kwargs={"template_id": self.template.template_id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="template-marker-begin"')
        self.assertContains(response, 'class="template-marker-end"')

    def test_without_markers_shows_warning(self):
        self.template.file.save(
            "template.txt",
            ContentFile(b"line without anchors"),
            save=True,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("analysis-template-preview", kwargs={"template_id": self.template.template_id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Маркеры не обнаружены")


class TemplatePreviewContextTests(SimpleTestCase):
    def test_preview_context_contains_anchor_summary(self):
        context = build_template_preview_context("anchor\n[BEGIN]\nbody\n[END]\nend", "[BEGIN]", "[END]")
        self.assertEqual(context["segments_count"], 1)
        self.assertEqual(context["segments"][0]["start_anchor"], "anchor")
        self.assertEqual(context["segments"][0]["end_anchor"], "end")
