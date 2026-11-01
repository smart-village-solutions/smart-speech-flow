# KasselDIALOG operator guide — working draft

This directory contains a German operator-guide draft, its editable Markdown
sources, screenshots, and designer handoff. The PDF labels every page as a
working draft. Merging these materials does not approve them for publication
or constitute privacy, product, screenshot, or rollout approval.

## Version reference

The interface comparison performed on 1 November 2026 used the deployed
frontend image `ssf-backend-frontend:prod-2acde0bd-clean` and source commit
`2acde0bd`. That snapshot has the conditional guest storage question and does
not contain the newer section-recording interface. The screenshots and guide
must be checked against the deployment selected for publication.

Current `main` includes section recording and the Studio legal-text integration
from PR #648. This draft does not document that newer workflow. Do not present
it as a guide to current `main` without revising the affected instructions and
screenshots. The October editorial date on page 26 is not a verified product
version or release date.

## Before publication

- Confirm and record the target product image/commit, document version, and
  publication date on the title/end pages and in the exported materials.
- Complete the existing [screenshot checklist](screenshot-checklist.md), including
  verification that invitation links, session codes, and QR targets are no
  longer usable and that the images contain only approved test data.
- Confirm the applicable privacy information, access path, retention claims,
  wording, and contact with the responsible reviewers. Pending comments in
  pages 08, 21, 22, 24, and 26 remain unresolved.
- Recheck the optional storage question and recording workflow against the
  chosen deployment. Regenerate and visually review the PDF and designer ZIP.

## Artwork selection and export formats

The Markdown image examples in the editorial templates are for Markdown
preview only. The current exporters do **not** render `![alt](path)` image
references; adding one to a numbered page will not add artwork to the PDF or
DOCX. Keep planned-image notes in HTML comments until artwork is mapped.

For the illustrated PDF:

1. Store approved PNG captures under `screenshots/` with the checklist prefix,
   for example `S05-...png`. Store vector artwork under `graphics/`.
2. In `build_pdf.py`, update `MEDIA` to select a page's screenshot prefix,
   caption, and index. `capture()` sorts matching filenames; an index selects
   a particular match, and S16 selects the German (`-de.png`) capture.
3. Check the special onboarding layouts in `draw_onboarding_images()` for
   pages 04 and 05. Graphics G02–G04 are drawn by `guide_graphics.py`; the PDF
   uses the configured placeholders when a page has no selected artwork.
4. Rebuild and inspect the illustrated PDF, then rebuild the designer package
   so its generated README records the current slide-to-artwork mapping.

The DOCX is a **text-only designer handoff** in landscape format. It contains
slide headings, text, tables, and links, without embedded screenshots or the
PDF's visual layout. The designer ZIP contains that DOCX, separate screenshots
and vector artwork, and a generated README with their page assignments. The
illustrated PDF is the layout reference; the DOCX is not a matching visual
export. Review the two deliverables for their respective purposes.

## Rebuild the draft

Use a dedicated Python environment; these document-generation dependencies do
not belong in the application service images. The review build used Python
3.12, ReportLab 5.1.0, Pillow 13.0.0, and python-docx 1.2.0. The PDF builder
expects DejaVu Sans fonts under `/usr/share/fonts/truetype/dejavu`.

```bash
python3.12 -m venv /tmp/ssf-guide-build
/tmp/ssf-guide-build/bin/pip install reportlab==5.1.0 Pillow==13.0.0 python-docx==1.2.0
/tmp/ssf-guide-build/bin/python docs/user-guide/build_pdf.py
/tmp/ssf-guide-build/bin/python docs/user-guide/build_designer_package.py
```

The builders require exactly 26 numbered Markdown pages. The PDF builder checks
text bounds. Review builds confirmed 26 landscape pages with a draft label on
every page, successful DOCX generation, and a valid designer ZIP containing all
source screenshots. These technical checks do not replace editorial approval.
