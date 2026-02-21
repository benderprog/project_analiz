from django.test import SimpleTestCase

from apps.analysis_app.svodka_templates import (
    DocElement,
    SegmentAnchors,
    apply_template_segments,
    build_template_segments,
    slice_by_markers,
)


class MarkerSlicingTests(SimpleTestCase):
    def test_two_segments_with_gap_keeps_only_segment_content(self):
        elements = [
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="A1"),
            DocElement(kind="paragraph", text="[END]"),
            DocElement(kind="paragraph", text="GAP"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="B1"),
            DocElement(kind="paragraph", text="[END]"),
        ]

        kept, debug = slice_by_markers(elements, "[BEGIN]", "[END]")

        self.assertEqual([item.text for item in kept], ["A1", "B1"])
        self.assertTrue(debug["markers_found"])
        self.assertEqual(debug["segments_count"], 2)
        self.assertEqual(debug["kept_elements"], 2)

    def test_unclosed_segment_keeps_until_document_end(self):
        elements = [
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="A1"),
            DocElement(kind="paragraph", text="A2"),
        ]

        kept, debug = slice_by_markers(elements, "[BEGIN]", "[END]")

        self.assertEqual([item.text for item in kept], ["A1", "A2"])
        self.assertTrue(debug["markers_found"])
        self.assertEqual(debug["segments_count"], 1)
        self.assertEqual(debug["kept_elements"], 2)

    def test_end_without_begin_keeps_nothing_for_direct_marker_slicing(self):
        elements = [
            DocElement(kind="paragraph", text="X"),
            DocElement(kind="paragraph", text="[END]"),
            DocElement(kind="paragraph", text="Y"),
        ]

        kept, debug = slice_by_markers(elements, "[BEGIN]", "[END]")

        self.assertEqual(kept, [])
        self.assertTrue(debug["markers_found"])
        self.assertEqual(debug["segments_count"], 0)
        self.assertEqual(debug["kept_elements"], 0)


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

        sliced, applied, failed = apply_template_segments(target, segments)

        self.assertEqual(applied, 1)
        self.assertEqual(failed, 0)
        self.assertEqual([e.text for e in sliced], [target[1].text, target[2].text, target[3].text])

    def test_template_with_two_segments_keeps_union_in_order(self):
        template_elements = [
            DocElement(kind="paragraph", text="Header"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="A middle"),
            DocElement(kind="paragraph", text="A end [END]"),
            DocElement(kind="paragraph", text="Between"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="B start"),
            DocElement(kind="paragraph", text="B middle"),
            DocElement(kind="paragraph", text="B end [END]"),
        ]
        segments = build_template_segments(template_elements, "[BEGIN]", "[END]")

        target = [
            DocElement(kind="paragraph", text="preamble"),
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="A body"),
            DocElement(kind="paragraph", text="A end"),
            DocElement(kind="paragraph", text="skip"),
            DocElement(kind="paragraph", text="B start"),
            DocElement(kind="paragraph", text="B body"),
            DocElement(kind="paragraph", text="B end"),
            DocElement(kind="paragraph", text="tail"),
        ]

        sliced, applied, failed = apply_template_segments(target, segments)

        self.assertEqual(applied, 2)
        self.assertEqual(failed, 0)
        self.assertEqual([e.text for e in sliced], ["A start", "A body", "A end", "B start", "B body", "B end"])

    def test_one_segment_matches_second_fails_keeps_first_without_fallback(self):
        anchors = [
            SegmentAnchors(start_anchor_text="A start", end_anchor_text="A end"),
            SegmentAnchors(start_anchor_text="Missing start", end_anchor_text="Missing end"),
        ]
        target = [
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="A body"),
            DocElement(kind="paragraph", text="A end"),
            DocElement(kind="paragraph", text="outside"),
        ]

        sliced, applied, failed = apply_template_segments(target, anchors)

        self.assertEqual(applied, 1)
        self.assertEqual(failed, 1)
        self.assertEqual([e.text for e in sliced], ["A start", "A body", "A end"])

    def test_sequential_matching_uses_later_duplicate_anchors(self):
        anchors = [
            SegmentAnchors(start_anchor_text="Start", end_anchor_text="End"),
            SegmentAnchors(start_anchor_text="Start", end_anchor_text="End"),
        ]
        target = [
            DocElement(kind="paragraph", text="Start"),
            DocElement(kind="paragraph", text="noise"),
            DocElement(kind="paragraph", text="End"),
            DocElement(kind="paragraph", text="gap"),
            DocElement(kind="paragraph", text="Start"),
            DocElement(kind="paragraph", text="inside second"),
            DocElement(kind="paragraph", text="End"),
        ]

        sliced, applied, failed = apply_template_segments(target, anchors)

        self.assertEqual(applied, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(
            [e.text for e in sliced],
            ["Start", "noise", "End", "Start", "inside second", "End"],
        )

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

        sliced, applied, failed = apply_template_segments(target, anchors)

        self.assertEqual(sliced, [])
        self.assertEqual(applied, 0)
        self.assertEqual(failed, 1)
