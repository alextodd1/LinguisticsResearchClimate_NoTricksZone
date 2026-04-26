# Methodology

This document describes how the NoTricksZone scraper acquires, parses, and emits
its corpus, with the level of detail needed to reproduce the procedure or write
a paper's methods section. It accompanies the operational instructions in
[`notrickszone_scraper/README.md`](notrickszone_scraper/README.md).

It is one of three sibling scrapers that share an output schema and overall
architecture, differing only in site-specific selectors:

- [`LinguisticsResearchClimate`](https://github.com/alextodd1/LinguisticsResearchClimate) — Watts Up With That (wpDiscuz comments, monthly archives)
- [`LinguisticsResearchClimate_Principia`](https://github.com/alextodd1/LinguisticsResearchClimate_Principia) — Principia Scientific International (UIkit-themed comments, Yoast sitemaps)
- **`LinguisticsResearchClimate_NoTricksZone`** *(this repo)* — NoTricksZone (native WordPress comments, WordPress-core sitemaps, mixed German/English dates)

The shared schema means texts from all three sources can be loaded into the same
corpus tools (Sketch Engine, NoSketchEngine, etc.) and queried with identical
structural attributes (`<doc>`, `<article>`, `<comment>` with `depth`,
`parent_id`, etc.).

---

## 1. Source

- **Site**: [notrickszone.com](https://notrickszone.com), edited by Pierre L. Gosselin
- **Platform**: WordPress (custom theme, exact version unknown — older posts
  use `<abbr class="comment-date">` markup, newer posts use a slightly
  modernised variant)
- **Date window**: 20 January 2017 → 20 January 2026 (9 years)
- **Languages observed**: English (vast majority), occasional German
  (P. Gosselin's bilingual cross-posts use German month names in author
  bylines, e.g. *"24. April 2026"*)

## 2. Architecture

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Sitemap Phase   │───▶│   Scrape Phase   │───▶│   Output Phase   │
│ (URL discovery)  │    │ (HTML → models)  │    │ (XML, TXT, vert) │
└────────┬─────────┘    └────────┬─────────┘    └──────────────────┘
         │                       │
         └──────────┬────────────┘
                    ▼
           ┌──────────────────┐
           │   SQLite DB      │
           │ (resumable state)│
           └──────────────────┘
```

Two phases run sequentially within a single process invocation:

1. **Discovery** populates the database with `articles` rows (status `pending`).
2. **Scraping** drains pending articles, fetching HTML, parsing, and writing
   output files plus comment rows.

A run can be interrupted at any point and resumed; the database tracks which
sitemaps and articles have been completed.

## 3. URL Discovery (Phase 1)

NoTricksZone publishes a WordPress-core sitemap index at
`https://notrickszone.com/sitemap.xml`, which references three post sitemaps:

```
wp-sitemap-posts-post-1.xml   (newest 2 000 posts)
wp-sitemap-posts-post-2.xml   (next 2 000)
wp-sitemap-posts-post-3.xml   (oldest 1 797)
```

The discovery code (`scrapers/sitemap.py`) walks the index, fetches each post
sitemap, and extracts `<url><loc>` entries.

### 3.1 URL filtering

NoTricksZone permalinks have the shape `/YYYY/MM/DD/slug/`. Two filters apply:

- **Shape filter** — non-article paths (`/category/`, `/tag/`, `/author/`,
  `/page/`, `/wp-*`, `/feed`, etc.) are excluded; the path must match
  `^\d{4}/\d{2}/\d{2}/[^/]+`.
- **Date filter** — derived from the URL itself, *not* the sitemap's
  `<lastmod>`. This is critical: WordPress updates `<lastmod>` whenever a new
  comment is posted, so a 2010 article with active 2026 comments would have a
  recent `<lastmod>` and would falsely pass a naive `<lastmod>`-based filter.
  Using the URL-derived date as the publish date prevents pre-2017 articles
  from entering the queue.

### 3.2 Outcome (this corpus)

Of 5 797 URLs across the three sitemaps, **2 835** fell within
2017-01-20 → 2026-01-20.

## 4. Article Scraping (Phase 2)

For each pending URL the HTTP client (`utils/http_client.py`) makes a `GET`
with:

- **2-second base delay** between requests (`--delay 2.0`).
- **Rotating user agents** — five contemporary desktop UA strings rotated per
  request to avoid trivial UA blocking.
- **5-attempt retry** with exponential backoff (1s, 2s, 4s, 8s, 16s) on
  transient errors and 429/5xx responses.
- **30-second timeout** per request.

The HTML parser (`parsers/html_parser.py:ArticleParser`) extracts the
following fields, in priority order — earlier sources are preferred when
present:

| Field | Source(s) |
|---|---|
| Title | `h1.entry-title`, fallback `h1`, fallback `<title>` minus site suffix |
| Date | URL-derived `/YYYY/MM/DD/`, then `<meta property="article:published_time">`, then `<time datetime="...">`, then byline regex |
| Author | `a[href*="/author/"]` text, fallback `.entry-author`, fallback meta tags |
| Body | `div.entry-content` with `.sharedaddy`, `.jp-relatedposts`, `<script>`, and ad blocks removed; paragraphs concatenated |
| Categories | `a[rel~="category"]` or `.entry-categories a` |
| Tags | `a[rel~="tag"]` *whose href contains `/tag/`* — older NTZ themes erroneously add `rel="tag"` to category links, so the href check is required to disambiguate |

The `ArticleParser` returns an `Article` dataclass; the scraper writes one
file per output format (see §6) and persists the article record.

### 4.1 Date handling for articles

Article publish dates are taken from the URL whenever the path matches
`/YYYY/MM/DD/`. This is the most reliable signal because:

1. WordPress permalinks are immutable for published posts.
2. It cannot be fooled by `<lastmod>` updates from new comments.
3. It works even when the article HTML's date markup is ambiguous.

Cross-checked against the database: 0 of 2 825 scraped articles had a
URL-year that disagreed with any other date signal on the page.

## 5. Comment Scraping

Comments are the most complex part of the pipeline because NoTricksZone uses
**native WordPress threaded comments** (not wpDiscuz, which WUWT uses).
Native WP renders comments server-side in nested `<ol class="children">`
elements, so JavaScript is not required.

### 5.1 Comment container and IDs

```html
<ol class="commentlist">          <!-- container -->
  <li class="comment" id="comment-1158413">     <!-- root -->
    <div class="comment-body">
      <div class="comment-author">...</div>
      <div class="comment-meta">...</div>
      <div class="comment-content">...</div>
    </div>
    <ol class="children">          <!-- nested replies -->
      <li class="comment" id="comment-1158471">
        ...
      </li>
    </ol>
  </li>
</ol>
```

The integer comment ID is parsed from the `id` attribute. Pingbacks and
trackbacks have a different `class` and are filtered out.

### 5.2 Threading reconstruction

Reply structure is recovered by *DOM nesting*, not by an explicit
`data-parent` attribute (which native WP does not emit):

- **Depth** = number of `<ol class="children">` ancestors of the comment's
  `<li>`.
- **Parent ID** = the `comment-NNNNN` id of the immediate `li.comment`
  ancestor of the parent `<ol class="children">`. Root comments have
  `parent_id = "ROOT"`.

Verified on this corpus: 27 647 of 52 695 comments are replies (52%); all
replies have a `parent_id` that resolves to a comment in the same article
(0 orphans).

### 5.3 Comment date extraction (this is where the bug was)

The parser tries five sources in order; the first to yield a valid date wins:

1. `<time datetime="...">` — ISO timestamp attribute (newer themes only).
2. `<abbr class="comment-date" title="...">` — older NTZ theme stores a clean
   English date in the `title` attribute (e.g.
   *"Saturday, July 21st, 2018, 5:29 pm"*).
3. `<span class="published">` text — date-only, no author noise.
4. `.comment-meta a` permalink anchor text.
5. Last-resort fallback: `.comment-meta` full text, with the author name
   stripped first.

**Why the strict ordering matters**: the older NTZ theme nests
`<span class="comment-author">` *inside* `<div class="comment-meta">`. A naive
fallback to `meta.get_text()` therefore yields strings like
`"AndyG55 21. July 2018 at 5:29 PM | Permalink"`. When this was passed to
`dateutil.parser.parse(..., fuzzy=True)`, the parser absorbed the trailing
digits of the username (`G55`) as a two-digit year, producing comment dates
in the year **2055** for 4 917 comments by `AndyG55` and `spike55`, plus
similar mis-parses for pingback titles like *"Roundup #439"* (parsed as the
year 439 AD).

The fix has two parts (see commit `f3b9097`):

- **Parser**: prefer source 1–4 above, which contain only the date.
- **Date utility**: `parse_date()` now strict-parses first; the `fuzzy=True`
  fallback fires only when the input contains both an English month token
  (`January`–`December` / `Jan`–`Dec`) *and* a 4-digit year in the 19xx/20xx
  range. This neutralises the entire class of digit-leak attacks.

After re-scraping with the fix, 0 of 52 695 comments had a date outside the
plausible range 2017-01-20 → 2026-04-30 (the small window beyond the article
end date accounts for late pingbacks).

### 5.4 German date handling

P. Gosselin posts a small number of articles whose comment-date metadata
uses German month names (e.g. *"24. April 2026 um 15:30"*). `parsers/date_parser.py`
contains a `GERMAN_MONTHS` mapping and a `parse_german_date()` regex that
catches these before the dateutil fallback.

### 5.5 Comment pagination

Articles with > N comments paginate at `<article-url>/comment-page-K/#comments`.
The comment scraper (`scrapers/comments.py`) detects pagination via
`.comment-navigation .page-numbers`, fetches each page sequentially, and
de-duplicates by comment ID (an integer parsed from the `id` attribute), so a
comment appearing on multiple pages is recorded once.

## 6. Output Formats

Each scraped article is written to **three** parallel output trees, all
keyed by the same filename stem `YYYYMMDD_slug`:

```
output/
├── vertical_xml/YYYY/MM/YYYYMMDD_slug.xml
├── xml/         YYYY/MM/YYYYMMDD_slug.xml
└── txt/         YYYY/MM/YYYYMMDD_slug.txt
```

### 6.1 Standard XML

A single `<doc>` root with attributes for metadata, then a `<title>`,
`<article>` (with `<p>` children), and `<comments>` (with `<comment>`
children). Comment elements carry these attributes:

| Attribute | Description |
|---|---|
| `id` | `comment-NNNNN` integer ID |
| `author` | display name |
| `date` | `YYYY-MM-DD HH:MM:SS` |
| `parent_id` | `comment-NNNNN` or `ROOT` |
| `depth` | 0–N nesting level |
| `has_images`, `image_refs` | embedded images, if any |

### 6.2 Plain text

Human-readable, with a metadata header, the article body, and threaded
comments. Reply nesting is rendered visually with `|__` ASCII connectors and
4-space-per-depth indentation, e.g.:

```
--- Comment #1 ---
[Author]: Bitter&twisted
[Date]: 2018-01-12 17:58:00
[Depth]: 0
Fossil fuels are simply stored solar energy...

  |__ --- Comment #2 [REPLY to Comment #1] ---
    [Author]: P Gosselin
    [Depth]: 1
    ...
```

### 6.3 Sketch Engine vertical XML

The format expected by [Sketch Engine](https://www.sketchengine.eu/) and
NoSketchEngine: one **token per line**, with structural tags as XML elements.
The same `<doc>` / `<title>` / `<article>` / `<comment>` structure as 6.1, but
with `<p>` and `<s>` (sentence) inside, and the actual text replaced by
tokens:

```
<doc id="20170120_..." url="..." title="..." author="P Gosselin" date="2017-01-20" ...>
<title>
<s>
Current
Solar
Cycle
3rd
...
</s>
</title>
<article>
<p>
<s>
The
sun
in
December
2016
,
...
```

Tokenisation falls back through a three-tier pipeline (`processors/tokeniser.py`):

1. **spaCy** (`en_core_web_sm`) — preferred when installed.
2. **NLTK** (`punkt` tokenizer) — fallback.
3. **Regex** — final fallback (works without NLP dependencies).

This corpus was tokenised with the regex tokeniser (no spaCy/NLTK installed
in the run environment), which splits on whitespace and isolates punctuation.
Re-tokenising with spaCy is straightforward by re-running with the package
installed; only the `vertical_xml/` tree changes.

## 7. Resumability

A SQLite database at `output/scraper_progress.db` tracks:

- `sitemaps` — which sitemaps have been processed.
- `articles` — every URL discovered, with `status` ∈ {`pending`, `scraped`,
  `failed`}, retry count, and error message.
- `comments` — every comment with full structured fields.
- `sessions` — each scraper run with start/end timestamps.

Re-running the scraper resumes from the last `pending` row; `--scrape-only`
skips re-discovery, `--comments-only` re-fetches comments without re-writing
articles.

## 8. Politeness

- 2-second base inter-request delay, plus retry backoff.
- Exponential backoff on 429 / 5xx.
- No parallel requests — strictly serial.
- Estimated total request volume for this corpus: ≈ 3 200 (one article
  fetch each plus comment-page-K fetches for the small minority with > 50
  comments). Wall-clock time for a full re-scrape: ≈ 1 h 50 min.

## 9. Known limitations

1. **URL-encoding 403s** — 10 of the 2 835 in-range articles return HTTP 403
   on every retry. Their URLs all contain percent-encoded non-ASCII
   characters (the ligature `ﬁ` as `%EF%AC%81`, the symbol `m²` as `m%C2%B2`,
   the thin space as `%E2%80%89`, mathematical italic letters as
   `%F0%9D%98%9B`). The site's WAF rejects these specific encodings even
   though browsers handle them transparently. Workaround would require
   normalising the URL to a different encoding, which is left for a future
   iteration. The 10 affected URLs are listed in commit `53259b5`'s release
   notes and can be retrieved by querying
   `SELECT url FROM articles WHERE status='failed'`.

2. **Comment author for pingbacks** — pingbacks/trackbacks use the *title of
   the linking post* as their "author". This is faithful to what WordPress
   stores, but it means the `author` field on those comment records is a
   sentence rather than a name. Filter `parent_id = 'ROOT' AND text LIKE '%[...]%'`
   if you want to exclude them from author-level analyses.

3. **Tokenisation quality** — see §6.3. The default regex tokeniser is
   adequate for token-frequency and concordance work but does not lemmatise
   or POS-tag. Re-run with spaCy installed for richer annotations.

4. **Image bodies** — comment-embedded images (rare on this site) are
   recorded as `image_refs` (URLs) but not downloaded by default. Use
   `--no-images=false` to download them; storage path is `output/images/`.

## 10. Reproducibility

The full procedure, from a clean checkout, is:

```bash
git clone https://github.com/alextodd1/LinguisticsResearchClimate_NoTricksZone.git
cd LinguisticsResearchClimate_NoTricksZone
python3 -m venv .venv
.venv/bin/pip install -r notrickszone_scraper/requirements.txt
# Optional: better tokenisation
.venv/bin/pip install spacy
.venv/bin/python -m spacy download en_core_web_sm

.venv/bin/python -m notrickszone_scraper.main \
    --start-date 2017-01-20 --end-date 2026-01-20 \
    --delay 2.0 --output ./output --verbose
```

Outputs are deterministic given the site state at the time of the scrape. To
verify a corpus matches this study's, compare:

- Article count: 2 825 successful, 10 failed (the 10 failed URLs are stable
  across runs because the WAF rejects them deterministically).
- Comment count: ≈ 52 695 (small drift over time as new comments are posted
  to old articles).
- File-tree structure (vertical_xml / xml / txt counts must match).

The git history of this repo records every parser change with its motivation
in the commit message; commit `f3b9097` (the comment-date fix) is the most
significant correction made during corpus construction and should be cited
as the parser version used.
