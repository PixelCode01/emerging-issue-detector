# Conversation Intelligence API

A API designed to ingest support tickets, generate semantic embeddings locally, and cluster them organically to surface high-impact product issues in real-time.

## Quickstart

I've bundled everything into a simple Makefile to ensure a easy local setup.

**Prerequisites:** Python 3.11+

```bash
# 1. Install dependencies
make install

# 2. Seed the database with ~500 synthetic tickets
make seed

# 3. Export your Gemini API key for AI summaries (optional but recommended)
export GEMINI_API_KEY="your_api_key_here"

# 4. Start the FastAPI server locally
make run
```

Once running, the server will be available at `http://localhost:8000`. 
**To test the API instantly, visit the auto-generated UI at [http://localhost:8000/docs](http://localhost:8000/docs).**

## Core Endpoints

- `POST /ingest`: Accepts batches of support tickets, generates vectors via `sentence-transformers`, and stores them as SQLite BLOBs.
- `GET /insights`: Triggers the HDBSCAN clustering algorithm, calculates impact scores, and calls the LLM to generate human-readable summaries of trending issues.

## Assumed Data Schema

The metadata correlation process assumes the incoming support tickets adhere to this structure. This allows us to tie semantic clusters to actionable product metrics (like user tier or SDK version).

```json
{
  "ticket_id": "TCK-1042",
  "text": "Critical: Events dropping in eu-west blocking downstream...",
  "timestamp": "2026-05-22T14:32:00Z",
  "sdk_version": "v0.14",
  "region": "eu-west",
  "user_tier": "enterprise",
  "source": "slack"
}
```

## Architecture Summary

This repository is built for maintainability, speed, and zero external infrastructure dependencies:

- **API Framework**: FastAPI for strict Pydantic payload validation and rapid endpoint iteration.
- **Embeddings**: `sentence-transformers` (`all-MiniLM-L6-v2`) running completely locally in-memory to avoid API latency and costs.
- **Clustering**: `hdbscan` for density-based semantic clustering. We do not force noise points into clusters, ensuring PMs only see actual trends.
- **LLM Summarization**: `google-genai` strictly for summarizing mathematical clusters into human-readable PM insights. Uses a cascading model fallback approach for high availability without crashing.
- **Durability**: A standard `sqlite3` database. We serialize NumPy arrays directly to BLOB columns to avoid ORMs and heavy C-compiler dependencies (like `sqlite-vec`), ensuring this repo runs out of the box on any machine.

## Sample API Output: `/insights`

The `/insights` endpoint clusters tickets, calculates an aggregate impact score based on user tiers (e.g., Enterprise issues weigh heavier than Free tier), and surfaces metadata correlations.

```json
{
  "clusters": [
    {
      "cluster_id": 0,
      "size": 42,
      "impact_score": 140,
      "metadata": {
        "top_sdk_version": "v0.14",
        "top_region": "eu-west"
      },
      "summary": "Users in the EU region are experiencing missing webhook timeouts blocking pipelines.",
      "samples": [
        "Critical: Events dropping in eu-west blocking downstream pipelines due to webhook timeouts!",
        "Getting webhook timeouts constantly."
      ]
    }
  ]
}
```

```