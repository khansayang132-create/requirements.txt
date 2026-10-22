# External providers: Azure Document Intelligence and DeepL

What the starter kit's clients assume, and what to re-check against the real project. Provider APIs change: before relying on a detail, confirm it in the provider's current docs (Context7 or the vendor site) and pin the API version in config. Record the version in the processing report.

## Azure AI Document Intelligence (prebuilt-layout)

### Request flow (REST, API version `2024-11-30`, "v4.0 GA")

| Step | Call | Success | Retry rule |
|---|---|---|---|
| Submit | `POST {endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=2024-11-30`, header `Ocp-Apim-Subscription-Key`, body = file bytes with `Content-Type: application/pdf` (or `image/png`, `image/jpeg`, `image/tiff`, `application/octet-stream`) | `202 Accepted`, header `Operation-Location` | **Non-idempotent** (creates a billable operation). Retry only on connection failure before a response, or 429. Never on timeout or 5xx: the operation may exist. |
| Poll | `GET {Operation-Location}` same key header | `200` with `status`: `notStarted` / `running` / `succeeded` / `failed` (`canceled` exists in some versions) | Idempotent: retry any retryable error. Wait `Retry-After` between polls when present, else a default (1–2 s). |
| Result | Final poll body, `analyzeResult` | `pages`, `paragraphs`, `tables`, `figures`, `sections`, `content` | n/a |

Older projects may use the v3.x path `/formrecognizer/documentModels/prebuilt-layout:analyze?api-version=2023-07-31`. Same shape, different path. Check which one the code calls; don't silently switch.

The Java SDK (`com.azure:azure-ai-documentintelligence`) wraps this in a `SyncPoller`. If the project uses the SDK, keep it and apply the same three rules through its `RetryOptions`/poll strategy instead of the hand-rolled client.

### Response facts that matter for layout

| Field | Meaning | Trap |
|---|---|---|
| `pages[].unit` | `"inch"` for PDF/TIFF, `"pixel"` for images | Code that assumes pixels everywhere puts every PDF block in the top-left corner (8.5 "pixels" wide). |
| `pages[].width/height` | In that unit | A missing or zero value must fail validation (`PageInfo` does). |
| `pages[].angle` | Detected **text skew** in degrees, (-180, 180] | It is not the PDF `/Rotate` value. Don't rotate boxes by it. |
| `boundingRegions[].polygon` | Flat array `[x1,y1,x2,y2,...]`, clockwise from top-left of the text, in page units | May be slightly outside the page for text at the edge: clamp within tolerance, error beyond. |
| `paragraphs[].role` | `title`, `sectionHeading`, `pageHeader`, `pageFooter`, `footnote`, `pageNumber`, or absent (body) | Headers/footers belong in the DOCX header/footer parts, not the body. |
| `paragraphs` | Includes the text of **table cells** too | Drop paragraphs whose span offset falls inside a table span, or table text appears twice (`AzureLayoutMapper` does this). |
| `tables[].cells[]` | `rowIndex`, `columnIndex`, `rowSpan`, `columnSpan`, `kind` (`columnHeader`, `rowHeader`, `stubHead`, `description`, `content`), `content` | Merged cells: write the content once at the anchor, mark the covered positions; don't duplicate. |
| `spans[]` | `offset`/`length` into `content` | Reading order. Sort blocks by first span offset. |
| `figures[]` | Images/charts with bounding regions | Signatures and stamps are not a dedicated layout output. Detect them in the vision stage, or treat figures + selection marks as candidates. |
| `selectionMarks` | Checkboxes (`selected`/`unselected`) | Easy to lose; map them explicitly if the documents have forms. |

### Limits to check per tier
File size, page count per request and image resolution limits differ by pricing tier and version. Read them from the docs for the tier in use, enforce them in TSK-6.7 **before** upload, and fail with a clear message instead of letting the service reject the file.

## DeepL API

| Fact | Value | Consequence |
|---|---|---|
| Endpoints | Pro `https://api.deepl.com`, Free `https://api-free.deepl.com` (Free keys end in `:fx`) | Pick from config; a wrong host is a 403, not a network error. |
| Auth | Header `Authorization: DeepL-Auth-Key <key>` | Query-string and form-field auth are deprecated. Never log the header. |
| Translate | `POST /v2/translate`, JSON body `{"text":[...], "target_lang":"ES", ...}` | Response `{"translations":[{"detected_source_language","text"}]}` in input order. Check the count. |
| Batch size | Up to 50 texts per request; request body up to 128 KiB | `DeepLTranslator.batches` splits by both; one block that is too large is an error, not a silent cut. |
| Target codes | `EN` and `PT` as targets are deprecated: use `EN-US`/`EN-GB`, `PT-BR`/`PT-PT` | `CliOptions` rejects bare `EN`/`PT` targets. Source codes never have a variant. |
| Tags | `tag_handling: "xml"` + `ignore_tags: ["ph"]` keeps placeholders untouched | With XML handling the text **is XML**: escape `& < >` before sending and unescape after, or "A & B" breaks. |
| Formatting | `preserve_formatting: true` stops DeepL from fixing punctuation/case | Useful for legal text; test both settings on real documents. |
| Formality | `formality: "more"|"less"|"prefer_more"|"prefer_less"` for some languages (ES, DE, FR, ...) | Make it config; legal documents usually want `prefer_more`. |
| Glossaries | `glossary_id` with an explicit `source_lang` | Glossary requires source_lang; without it the request is rejected. |
| Errors | 400 bad request, 403 auth, 404, 413 too large, 429 too many requests, **456 quota exceeded**, 5xx/503 | 456 is permanent until the quota resets: do not retry. 429 honours `Retry-After`. |
| Usage | `GET /v2/usage` returns `character_count` / `character_limit` | Check before a big job; fail early instead of at block 900. |
| Billing | Characters are billed per request | A retry after a timeout can bill twice. Acceptable, but count retries in the report. |

## Live tests

- Tag them `@Tag("live")`. Surefire and Failsafe exclude that tag; run with `mvn verify -Dgroups=live`.
- Read keys from environment variables (`AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`, `DEEPL_AUTH_KEY`). If a key is missing, **skip** with a message (`Assumptions.assumeTrue`), never pass.
- Use the smallest fixture; these cost money.
- A live run that passes is evidence for that date and API version only. Record both.
- To refresh a mock: run the live call once, save the response JSON to `src/test/resources/mocks/`, scrub identifiers, and note the date and API version in a sibling `.md`.
