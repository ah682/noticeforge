# NoticeForge demonstration walkthrough

This walkthrough uses owned synthetic notices. Extraction runs locally with the
deterministic baseline. The examples demonstrate product behavior, not measured
performance on real supplier documents.

## Start the workspace

From the project directory:

```sh
make demo
```

Open `http://127.0.0.1:8877`. The demo seeds five notices without replacing existing
review decisions. To restore the demonstration, stop the server, run `make reset`,
then run `make demo` again. Reset removes the local notice database and its review
history, then reseeds the owned fixtures.

## Inspect exact part relationships

Open **AST-PDN-2026-041**, the Aster discontinuation notice. The original PDF sits
beside the extracted part groups. Use **+** above the PDF to enlarge it; scrolling
stays inside the source pane. The percentage button returns to **Fit**. **View
text** exposes the extracted text and its highlighted evidence.

1. Select `00128-Q1` or its **Last buy** value. The source highlights the linked
   identifier or date. Its last-buy date is 31 March 2027.
2. Inspect `00128-Q2`. Its inventory-limited ordering condition belongs to that
   part only. The condition is not a guaranteed purchasing deadline and needs
   explicit review.
3. Inspect the Power group. `NX-4100-A` has a last-buy date of 30 June 2027.
   `NX-4100-B` has 15 July 2027 because source footnote `[1]` modifies its row.
4. Compare `AO10-L` and `A010-L`. They remain separate identifiers; the letter
   `O` and numeral `0` are not merged.
5. The `NX-4200-A` suggestion for `NX-4100-A` is explicitly marked
   **Compatibility not assessed**.

The later-notice banner links to **AST-PDN-2026-041-B**. Open it to inspect the
revised 15 August 2027 last-buy date for `NX-4100-B`. Return to the original:
all six historical part records remain available, and the banner identifies
the five parts outside the subset revision's scope.

## Record a supported review decision

On the original Aster notice, choose **Review** beside a supported deadline,
such as the last-buy date for `00128-Q1`. If a deadline is shared by several
parts, the dialog provides a part selector; saving changes the selected part's
field only.

Keep **Accept source value**, enter a reason tied to the displayed source, add a
reviewer name, and choose **Save decision**. The field gains its accepted status.
**Decision history** shows the field path, recorded value, reason, reviewer, and
record version. Reloading the notice retains the decision.

**Correct this field** preserves the original value. For a correction, enter the
new value and a reason. Expand **Source evidence for this correction** to select
a source page or replace the supporting excerpt. The excerpt must occur exactly
once on that page; an absent or ambiguous excerpt is rejected. Dates use
`YYYY-MM-DD`. Only make a real correction when the source and authorized reviewer
evidence justify it.

## See uncertainty remain explicit

Use **Switch notice** and open **BRS-PDN-2026-018**. The `00CLK-8A` last-buy entry
is `03/04/2027`, with no stated date convention. The compiler retains that text
and marks the relationship for review instead of choosing March 4 or April 3.
Attempting **Accept source value** with a reviewer and reason is rejected; the
unresolved date does not become an exact value merely through acceptance.

`00CLK-8B` has inventory-limited ordering and an unspecified delivery date.
These remain explicit uncertainties. The suggested replacement is not an
approved substitute.

Open **CRS-PDN-2026-009** to see the incomplete-document case. Its source says
**Page 1 of 3**, but only one page is present. The workspace displays the coverage
warning. It does not imply that the visible part is the complete affected list.

## Match a BOM literally

Return to **AST-PDN-2026-041**, open **BOM matching**, and paste the contents of
`fixtures/bom.csv`. Choose **Match parts**.

| Input | Expected result |
| --- | --- |
| `00128-Q1`, Aster Semiconductor | Literal match |
| `NX-4100-B`, Aster Semiconductor | Literal match |
| `00128-Q1`, Borealis Devices | Unmatched manufacturer |
| `128-Q1`, Aster Semiconductor | Unmatched identifier; leading zeros matter |
| `AO10-L`, no manufacturer | Ambiguous manufacturer scope |
| `MISSING-99`, Aster Semiconductor | Unmatched identifier |

**Use notice parts** fills the input with the current notice's exact identifiers
and manufacturers. It is a convenience for examining the matching workflow, not
an independent customer BOM or an engineering substitution assessment.

## Export a supported record and inspect a blocked export

**Export record → Canonical JSON** includes the full canonical record, source
evidence, review states, qualifiers, revision relationships, and provenance.
It remains available for uncertain and incomplete notices.

For the supported XML example, switch to **AST-PCN-2026-052**, the Aster site
transfer notice, and choose **Export record → smartPCN**. This owned fixture
contains the contact, item, category, and exact-date data required by the
restricted exporter. A returned XML body is validated against the pinned
**SmartPCN_3.08 XSD for smartPCN 3.0**. The download is an XML body, not a complete
`.smartPCN` transport package. See [SMARTPCN.md](SMARTPCN.md) for the profile and
extension boundaries.

Try XML export from the Borealis review notice or the incomplete Crest notice.
The UI displays the exporter's reason for blocking it. An unresolved value or
missing page is not filled with invented data to make the schema pass.

## Request and review optional model proposals

The **Model review** tab reuses the source pane. The default local demo has no
model configured and explains the required setup; it does not substitute fixture
output for live inference. Upload, deterministic extraction, manual review, and
export remain available without a model.

After configuring a provider using [MODELS.md](MODELS.md), the tab identifies its
provider, model, and local or external operating mode. An external provider's
notice-text transfer is stated before the run button. **Run model review** is the
only action that requests inference. Opening a notice, uploading it, or refreshing
saved runs does not invoke the provider.

1. Choose **Run model review**. The request is persisted immediately and moves
   through **Queued** or **Running** while the UI polls for its saved result. You
   can return to ordinary evidence review during the run.
2. Inspect the proposals. The current and proposed part-specific date appear
   together. **Inspect source** highlights the cited text in the source pane.
   Validation-rejected outputs appear separately and have no acceptance action.
3. Choose **Accept** or **Reject** on an individual proposal. Both decisions
   require a reviewer and reason. Acceptance updates only the chosen part/date
   relationship and retains source evidence and model provenance. If an exact
   identifier has multiple records, select the intended manufacturer/part scope;
   multiple existing dates of the same kind require a specific replacement target.
4. An accepted ambiguous or conditional date remains review-required. Acceptance
   does not manufacture an exact deadline or establish complete document coverage.
   Rejection preserves the proposal and decision while leaving part facts intact.
5. **Decision history** records the request, result, and reviewer decisions.
   Reloading preserves them. **Canonical JSON** includes the applied relationship,
   evidence, run identifiers, model configuration hashes, and both acceptance and
   rejection provenance. XML remains subject to its independent restricted-profile
   validation.

No-result, failed, and unavailable runs remain visible with their saved outcomes.
The workspace reports included source characters and makes truncated model
context prominent. An unrelated edit can make an older proposal stale; the server
blocks applying it and asks for a fresh run. Model generation never silently
overwrites the canonical record.

For a credential-free workflow test, the repository includes an explicitly
labelled fixture-only server:

```sh
.venv/bin/python scripts/model_review_demo.py --port 8878 --data-dir /tmp/noticeforge-model-review-demo
```

Open `http://127.0.0.1:8878`, select **AST-PCN-2026-052**, and open **Model review**.
The fixture returns two source-matching proposals for `AMP-230-A` and `AMP-230-B`,
plus an invented identifier that source validation rejects. Accept the first and
reject the second to inspect persistence, audit, and export. This is a hard-coded
owned fixture for the review workflow, **not live model inference or a model
quality evaluation**.

With that server running, the browser verification command is:

```sh
node scripts/browser-qa.mjs --model
```

Its `reports/browser-model/result.json` separates end-to-end fixture-provider
checks from UI-only mocked response-state checks. The latter exercise error,
unavailable, empty, truncation, and setup messages without claiming that those
mocked responses came from an actual model run.

## Import your own authorized source

Choose **Import notice**, select a `.pdf` or `.txt` file up to **10 MiB**, then
choose **Import & extract**. The result opens in the same evidence workspace.
Unsupported layouts, OCR uncertainty, missing relationships, and incomplete
coverage require review. A file is not guaranteed to match the fixture templates.

For a credential-free import exercise, use a file from
`fixtures/development/`. Reimporting identical bytes returns the existing record
instead of duplicating it. The import dialog rejects empty or unsupported files;
the server independently validates file type, size, and content.

## Reproduce the acceptance checks

```sh
make test
make check
```

The API tests cover persistence, evidence validation, review correction and
stale-write rejection, subset revisions, manufacturer-aware matching, and the
successful/blocked export paths described above. Export tests validate the
supported fixture against the actual XSD and reject invalid XML. The browser
artifacts in `reports/browser/` document the inspected workspace; they do not
establish review-time savings or real-world extraction accuracy.

Browser acceptance checks make review decisions and import a synthetic notice.
Run them against a separate, freshly seeded data directory so existing review
history remains independent. For example, start the default service in one
terminal, then run the suite in another:

```sh
NOTICEFORGE_DATA_DIR=/tmp/noticeforge-browser-check NOTICEFORGE_PORT=8879 make demo
```

```sh
npm ci
node scripts/browser-qa.mjs --base http://127.0.0.1:8879 --output reports/browser-release
```

With the default service on 8879 and the explicitly labelled fixture model
service on 8878, verify keyboard paths and run the pinned axe-core 4.14.0 scanner:

```sh
node scripts/browser-qa.mjs --a11y --base http://127.0.0.1:8879 --model-base http://127.0.0.1:8878
```

This checks desktop and mobile review screens, model proposals, and review/import/
export dialogs. Keyboard checks cover the skip link, workspace tabs, dialog focus
containment, and Escape returning focus to the triggering control. Results and
screenshots are saved under `reports/accessibility/`. Raw axe `incomplete` findings
remain in the reports; they are not silently counted as passes. A native-dialog
evidence contrast diagnostic also records computed contrast and visibility samples
for inspection alongside its screenshot.

These are automated rule and interaction checks with visual inspection, not a
human screen-reader evaluation or a component-engineer usability study. They do
not establish full WCAG conformance, extraction quality, or time saved in review.
