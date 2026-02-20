from django.test import SimpleTestCase

from apps.analysis_app.svodka_templates import DocElement, SegmentAnchors, apply_template_segments, build_template_segments


class SvodkaTemplateSlicingTests(SimpleTestCase):
    def test_template_with_one_segment_keeps_only_matched_range(self):
        template_elements = [
            DocElement(kind="paragraph", text="Before"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="Start anchor text"),
            DocElement(kind="paragraph", text="Middle"),
            DocElement(kind="paragraph", text="End anchor text [END]"),
        ]
        segments = build_template_segments(template_elements, "[BEGIN]", "[END]")
        target = [
            DocElement(kind="paragraph", text="unrelated"),
            DocElement(kind="paragraph", text=".. START anchor text .."),
            DocElement(kind="paragraph", text="inside"),
            DocElement(kind="paragraph", text="END anchor text!!!"),
            DocElement(kind="paragraph", text="outside"),
        ]

        sliced, applied = apply_template_segments(target, segments)

        self.assertEqual(applied, 1)
        self.assertEqual([e.text for e in sliced], [target[1].text, target[2].text, target[3].text])

    def test_template_with_two_segments_keeps_union_in_order(self):
        anchors = [
            SegmentAnchors(start_anchor_text="A start", end_anchor_text="A end"),
            SegmentAnchors(start_anchor_text="B start", end_anchor_text="B end"),
        ]
        target = [
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="A body"),
            DocElement(kind="paragraph", text="A end"),
            DocElement(kind="paragraph", text="skip"),
            DocElement(kind="paragraph", text="B start"),
            DocElement(kind="paragraph", text="B end"),
        ]

        sliced, applied = apply_template_segments(target, anchors)

        self.assertEqual(applied, 2)
        self.assertEqual([e.text for e in sliced], ["A start", "A body", "A end", "B start", "B end"])

    def test_missing_markers_returns_no_segments(self):
        template_elements = [
            DocElement(kind="paragraph", text="No markers"),
            DocElement(kind="paragraph", text="Still no markers"),
        ]

        segments = build_template_segments(template_elements, "[BEGIN]", "[END]")

        self.assertEqual(segments, [])

    def test_anchors_not_found_returns_empty_slice(self):
        target = [
            DocElement(kind="paragraph", text="x"),
            DocElement(kind="paragraph", text="y"),
        ]
        anchors = [SegmentAnchors(start_anchor_text="missing start", end_anchor_text="missing end")]

        sliced, applied = apply_template_segments(target, anchors)

        self.assertEqual(sliced, [])
        self.assertEqual(applied, 0)
