from django.test import SimpleTestCase, override_settings

from apps.analysis_app.svodka_templates import (
    DocElement,
    SegmentAnchors,
    apply_template_segments,
    build_template_segments,
    parse_template_marker_blocks,
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

    def test_end_without_begin_keeps_nothing_for_direct_marker_slicing(self):
        elements = [
            DocElement(kind="paragraph", text="X"),
            DocElement(kind="paragraph", text="[END]"),
            DocElement(kind="paragraph", text="Y"),
        ]

        kept, debug = slice_by_markers(elements, "[BEGIN]", "[END]")

        self.assertEqual(kept, [])
        self.assertTrue(debug["markers_found"])


class TemplateBlockParsingTests(SimpleTestCase):
    def test_single_segment_extracts_pre_and_post_anchors(self):
        blocks, warnings = parse_template_marker_blocks("pre\n[BEGIN]\nbody\n[END]\npost")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].pre_anchor_text, "pre")
        self.assertEqual(blocks[0].post_anchor_text, "post")
        self.assertEqual(warnings, [])

    def test_multiple_segments_supported(self):
        text = "a\n[BEGIN]\nA\n[END]\nb\n[BEGIN]\nB\n[END]\nc"
        blocks, _ = parse_template_marker_blocks(text)
        self.assertEqual(len(blocks), 2)

    def test_begin_without_end_open_ended(self):
        blocks, warnings = parse_template_marker_blocks("pre\n[BEGIN]\nbody")
        self.assertEqual(len(blocks), 1)
        self.assertIsNone(blocks[0].end_marker_span)
        self.assertTrue(any("BEGIN without END" in item for item in warnings))

    def test_end_without_begin_is_ignored(self):
        blocks, warnings = parse_template_marker_blocks("x\n[END]\ny")
        self.assertEqual(blocks, [])
        self.assertTrue(any("END without BEGIN" in item for item in warnings))


class SvodkaTemplateSlicingTests(SimpleTestCase):
    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_exact_anchors_in_report_slice_between_lines(self):
        anchors = [SegmentAnchors(start_anchor_text="A start", end_anchor_text="A end", index=0)]
        target = [
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="inside"),
            DocElement(kind="paragraph", text="A end"),
        ]

        sliced, applied, failed, _, _ = apply_template_segments(target, anchors)

        self.assertEqual(applied, 1)
        self.assertEqual(failed, 0)
        self.assertEqual([e.text for e in sliced], ["inside"])

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_open_ended_segment_slices_to_end(self):
        anchors = [SegmentAnchors(start_anchor_text="A start", end_anchor_text=None, is_open_ended=True, index=0)]
        target = [
            DocElement(kind="paragraph", text="A start"),
            DocElement(kind="paragraph", text="inside"),
            DocElement(kind="paragraph", text="tail"),
        ]

        sliced, applied, failed, _, _ = apply_template_segments(target, anchors)
        self.assertEqual(applied, 1)
        self.assertEqual(failed, 0)
        self.assertEqual([e.text for e in sliced], ["inside", "tail"])

    @override_settings(SKIP_SEMANTIC_MODEL=True)
    def test_paraphrased_anchor_lexical_match(self):
        anchors = [SegmentAnchors(start_anchor_text="дата нарушения", end_anchor_text="итоги проверки", index=0)]
        target = [
            DocElement(kind="paragraph", text="Дата нарушения и место"),
            DocElement(kind="paragraph", text="тело"),
            DocElement(kind="paragraph", text="Итоги проверки по делу"),
        ]

        sliced, applied, failed, _, _ = apply_template_segments(target, anchors)
        self.assertEqual(applied, 1)
        self.assertEqual(failed, 0)
        self.assertEqual([e.text for e in sliced], ["тело"])

    def test_build_template_segments_supports_open_ended(self):
        template_elements = [
            DocElement(kind="paragraph", text="start line"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="body"),
        ]
        segments = build_template_segments(template_elements, "[BEGIN]", "[END]")
        self.assertEqual(len(segments), 1)
        self.assertTrue(segments[0].is_open_ended)

    def test_regression_literal_markers_path_unchanged(self):
        elements = [
            DocElement(kind="paragraph", text="x"),
            DocElement(kind="paragraph", text="[BEGIN]"),
            DocElement(kind="paragraph", text="y"),
            DocElement(kind="paragraph", text="[END]"),
            DocElement(kind="paragraph", text="z"),
        ]
        kept, _ = slice_by_markers(elements, "[BEGIN]", "[END]")
        self.assertEqual([item.text for item in kept], ["y"])
