---
name: yfcc100m
description: "Skill for the Yfcc100m area of shml-platform. 45 symbols across 4 files."
---

# Yfcc100m

45 symbols | 4 files | Cohesion: 93%

## When to Use

- Working with code in `libs/`
- Understanding how get_db_connection, setup_database, has_face_tag work
- Modifying yfcc100m-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/annotation/yfcc100m/yfcc100m_downloader.py` | YFCC100MDownloader, setup_directories, load_progress, save_progress, download_image (+11) |
| `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | get_db_connection, setup_database, has_face_tag, is_commercial_safe, parse_sql_values (+7) |
| `libs/annotation/yfcc100m/yfcc100m_sqlite_extract.py` | is_commercial_safe, has_face_tag, url_decode, setup_local_db, extract_face_images (+4) |
| `libs/annotation/yfcc100m/yfcc100m_sqlite_pipeline.py` | get_db_connection, setup_database, has_face_tag, get_license_id, is_commercial_safe (+3) |

## Entry Points

Start here when exploring this area:

- **`get_db_connection`** (Function) — `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py:188`
- **`setup_database`** (Function) — `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py:211`
- **`has_face_tag`** (Function) — `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py:260`
- **`is_commercial_safe`** (Function) — `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py:268`
- **`parse_sql_values`** (Function) — `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py:273`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `YFCC100MDownloader` | Class | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 139 |
| `ImageMetadata` | Class | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 108 |
| `get_db_connection` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 188 |
| `setup_database` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 211 |
| `has_face_tag` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 260 |
| `is_commercial_safe` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 268 |
| `parse_sql_values` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 273 |
| `parse_value` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 314 |
| `stream_sql_inserts` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 366 |
| `extract_face_metadata` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 426 |
| `download_image` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 542 |
| `download_images` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 596 |
| `create_yolo_dataset` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 698 |
| `main` | Function | `libs/annotation/yfcc100m/yfcc100m_face_pipeline.py` | 779 |
| `setup_directories` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 188 |
| `load_progress` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 195 |
| `save_progress` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 207 |
| `download_image` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 300 |
| `download_batch` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 361 |
| `download_metadata_from_s3` | Function | `libs/annotation/yfcc100m/yfcc100m_downloader.py` | 408 |

## Connected Areas

| Area | Connections |
|------|-------------|
| App | 1 calls |
| Unit | 1 calls |

## How to Explore

1. `gitnexus_context({name: "get_db_connection"})` — see callers and callees
2. `gitnexus_query({query: "yfcc100m"})` — find related execution flows
3. Read key files listed above for implementation details
