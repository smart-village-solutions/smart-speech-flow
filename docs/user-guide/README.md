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
