# Offline release fixtures (not stored in git)

Binary fixture files are intentionally excluded from the repository by policy.

Before running offline release build, obtain these files from approved internal sources
and place them anywhere on local disk:

- `subdivizion_primer.xlsx`
- `test_svodka_semantic.docx`

Pass absolute paths to `scripts/release/build_release.sh` using:

```bash
--xlsx /abs/path/subdivizion_primer.xlsx --docx /abs/path/test_svodka_semantic.docx
```

Or set:

- `FIXTURE_XLSX=/abs/path/subdivizion_primer.xlsx`
- `FIXTURE_DOCX=/abs/path/test_svodka_semantic.docx`
