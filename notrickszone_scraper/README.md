# NoTricksZone Scraper

Web scraper for [notrickszone.com](https://notrickszone.com) for linguistic
research on climate change discourse. Companion to
[LinguisticsResearchClimate](https://github.com/alextodd1/LinguisticsResearchClimate)
(WUWT) and
[LinguisticsResearchClimate_Principia](https://github.com/alextodd1/LinguisticsResearchClimate_Principia)
(Principia Scientific) — same output schema, different source site.

## Features

- Scrapes articles from January 20, 2017 to January 20, 2026
- Discovers articles via the WordPress core XML sitemap index
  (`/sitemap.xml` → `wp-sitemap-posts-post-N.xml`)
- Extracts full native-WordPress comment threads:
  - Timestamps (handles German month names — P Gosselin posts dates as
    "24. April 2026")
  - Reply threading and nesting depth (via `<ol class="children">` recursion)
  - Comment images
- Three output formats: plain text, standard XML, Sketch Engine vertical XML
- Resumable (SQLite progress tracking)
- Polite rate limiting (configurable delays, rotating user agents)

## Installation

```bash
cd LinguisticsResearchClimate_NoTricksZone
pip install -r notrickszone_scraper/requirements.txt

# Optional: Install spaCy for better tokenization
pip install spacy
python -m spacy download en_core_web_sm
```

## Usage

### Full Scrape

```bash
# Run full scrape from 2017-01-20 to 2026-01-20
python -m notrickszone_scraper.main

# With custom output directory and delay
python -m notrickszone_scraper.main --output ./my_output --delay 3

# Limit to first 100 articles
python -m notrickszone_scraper.main --limit 100
```

### Discovery Only

```bash
# Just discover article URLs from sitemaps without scraping
python -m notrickszone_scraper.main --discover-only
```

### Resume Scraping

```bash
# Continue from where you left off
python -m notrickszone_scraper.main --scrape-only
```

### Test Single Article

```bash
# Test scraping a single article
python -m notrickszone_scraper.main --test "https://notrickszone.com/2026/04/24/european-institute-for-climate-and-energy-climate-debate-is-seldom-about-science/"
```

### Check Progress

```bash
# Show current statistics
python -m notrickszone_scraper.main --stats
```

## Output Structure

```
output/
├── vertical_xml/
│   └── YYYY/MM/YYYYMMDD_article-slug.xml
├── xml/
│   └── YYYY/MM/YYYYMMDD_article-slug.xml
├── txt/
│   └── YYYY/MM/YYYYMMDD_article-slug.txt
├── corpus/
├── images/
├── metadata/
├── logs/
└── scraper_progress.db
```

## Output Formats

### Plain Text (.txt)
Human-readable format with article metadata, body text, and threaded comments.

### Standard XML (.xml)
Structured XML with article and comment data as elements and attributes.

### Sketch Engine Vertical XML (.xml)
Tokenized output for Sketch Engine corpus analysis with one token per line.

## Configuration

Create a `config.yaml` file for custom settings:

```yaml
scraper:
  base_url: "https://notrickszone.com"
  start_date: "2017-01-20"
  end_date: "2026-01-20"
  request_delay: 2
  max_retries: 5
  timeout: 30

output:
  base_dir: "./output"

processing:
  download_images: false
```

Then run with:

```bash
python -m notrickszone_scraper.main --config config.yaml
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--config, -c` | Path to YAML config file |
| `--output, -o` | Output directory (default: ./output) |
| `--delay, -d` | Request delay in seconds (default: 2.0) |
| `--start-date` | Start date YYYY-MM-DD (default: 2017-01-20) |
| `--end-date` | End date YYYY-MM-DD (default: 2026-01-20) |
| `--discover-only` | Only discover articles from sitemaps |
| `--scrape-only` | Skip discovery, scrape pending |
| `--comments-only` | Only scrape comments |
| `--limit, -l` | Max articles to scrape |
| `--test, -t` | Test single article URL |
| `--stats` | Show statistics |
| `--verbose, -v` | Verbose logging |
| `--no-images` | Skip image downloads |

## Notes

- The scraper uses polite delays (default 2s) to avoid overloading the server
- Progress is saved in SQLite, so you can resume if interrupted
- Article discovery uses XML sitemaps for efficient enumeration
- Comment threading (replies) is preserved via DOM nesting detection
- Date range filtering uses sitemap `lastmod` dates for initial filtering, then verifies actual publish dates during scraping
