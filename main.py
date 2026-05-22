import time
import logging
import uuid
import sqlite3
from typing import List, Optional, Dict, Any
from collections import Counter
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from database import get_connection, insert_ticket, get_unclustered_tickets
from clustering import embedder, process_unclustered_tickets, calculate_impact_score
from llm import generate_pm_insight

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Conversation Intelligence API")

# 1. Middleware for processing time logging
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    process_time_ms = round(process_time * 1000, 2)
    logger.info(f"Method: {request.method} Path: {request.url.path} - process_time_ms: {process_time_ms}")
    response.headers["X-Process-Time"] = str(process_time_ms)
    return response

# 2. Strict Pydantic Models
class TicketIngestRequest(BaseModel):
    text: str = Field(..., description="The content of the support ticket")
    sdk_version: str = Field(..., description="The SDK version string")
    region: str = Field(..., description="Region where the ticket originated")
    user_tier: str = Field(..., description="Billing tier of the user")
    source: str = Field(..., description="Source of the ticket, e.g., email, slack")

class TicketIngestResponse(BaseModel):
    ticket_id: str
    status: str

class HealthResponse(BaseModel):
    db_status: str
    total_tickets: int
    cluster_count: int
    noise_ratio: float

class AnalyzeResponse(BaseModel):
    processed_count: int
    clusters_found: int

class ClusterMetadata(BaseModel):
    top_sdk_version: str
    top_region: str

class ClusterInsight(BaseModel):
    cluster_id: int
    size: int
    impact_score: int
    metadata: ClusterMetadata
    summary: str
    samples: List[str]

class InsightsResponse(BaseModel):
    clusters: List[ClusterInsight]

# 3. Thin Endpoints

@app.get("/health", response_model=HealthResponse)
def health_check():
    """
    Returns API and Database health metrics.
    
    Sample Response:
    {
      "db_status": "ok",
      "total_tickets": 500,
      "cluster_count": 4,
      "noise_ratio": 0.45
    }
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM tickets")
            total_tickets = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT cluster_id) FROM tickets WHERE cluster_id IS NOT NULL AND cluster_id != -1")
            cluster_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE cluster_id = -1")
            noise_tickets = cursor.fetchone()[0]
            
            # Compute ratio of noise tickets to total tickets that have been clustered (including noise)
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE cluster_id IS NOT NULL")
            total_clustered = cursor.fetchone()[0]
            
            noise_ratio = round(noise_tickets / total_clustered, 2) if total_clustered > 0 else 0.0

            return HealthResponse(
                db_status="ok",
                total_tickets=total_tickets,
                cluster_count=cluster_count,
                noise_ratio=noise_ratio
            )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=500, content={"error": "Database error", "detail": str(e)})

@app.post("/ingest", response_model=TicketIngestResponse)
def ingest_ticket(ticket: TicketIngestRequest):
    """
    Ingests a single ticket, generates an embedding, and stores it directly.
    
    Sample Response:
    {
      "ticket_id": "8b51d6ed-99cc-4e89-9a74-d4b8e211fd67",
      "status": "success"
    }
    """
    try:
        ticket_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Tradeoff: Blocking the request to fetch embedding. Acceptable for simple traffic,
        # but in production we'd decouple this via a queue (Celery/Kafka).
        embedding = None
        if embedder is not None:
            embedding = embedder.encode(ticket.text)
            
        insert_ticket(
            ticket_id=ticket_id,
            text=ticket.text,
            timestamp=timestamp,
            sdk_version=ticket.sdk_version,
            region=ticket.region,
            user_tier=ticket.user_tier,
            source=ticket.source,
            embedding=embedding
        )
        return TicketIngestResponse(ticket_id=ticket_id, status="success")
    except Exception as e:
        logger.error(f"Failed to ingest ticket: {e}")
        return JSONResponse(status_code=500, content={"error": "Ingestion failed"})

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze():
    """
    Triggers the HDBSCAN clustering pipeline for any unclustered tickets.
    
    Sample Response:
    {
      "processed_count": 215,
      "clusters_found": 3
    }
    """
    try:
        cluster_updates = process_unclustered_tickets()
        if not cluster_updates:
            return AnalyzeResponse(processed_count=0, clusters_found=0)
            
        # Extract unique valid clusters (excluding noise -1)
        unique_clusters = set(c_id for c_id, t_id in cluster_updates if c_id != -1)
        
        return AnalyzeResponse(
            processed_count=len(cluster_updates),
            clusters_found=len(unique_clusters)
        )
    except Exception as e:
        logger.error(f"Failed to run analysis: {e}")
        return JSONResponse(status_code=500, content={"error": "Analysis failed"})

@app.get("/insights", response_model=InsightsResponse)
def get_insights():
    """
    Returns ranked clusters grouped with metadata, ordered by impact score.
    
    Sample Response:
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
          "samples": [
            "Critical: Events dropping in eu-west blocking downstream pipelines due to webhook timeouts!",
            "Getting webhook timeouts constantly."
          ]
        }
      ]
    }
    """
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Fetch all tickets belonging to valid clusters (exclude noise)
            cursor.execute("SELECT * FROM tickets WHERE cluster_id IS NOT NULL AND cluster_id != -1")
            rows = cursor.fetchall()
            
            # Group by cluster ID
            clusters_map = {}
            for row in rows:
                c_id = row['cluster_id']
                if c_id not in clusters_map:
                    clusters_map[c_id] = []
                clusters_map[c_id].append(dict(row))
                
        insights = []
        for c_id, tickets in clusters_map.items():
            impact = calculate_impact_score(tickets)
            
            # Simple summarization/grouping logic
            sdks = Counter([t['sdk_version'] for t in tickets])
            regions = Counter([t['region'] for t in tickets])
            
            # 2 samples
            samples = [t['text'] for t in tickets[:2]]
            
            insight_summary = generate_pm_insight(samples)
            
            insights.append(ClusterInsight(
                cluster_id=c_id,
                size=len(tickets),
                impact_score=impact,
                metadata=ClusterMetadata(
                    top_sdk_version=sdks.most_common(1)[0][0] if sdks else "unknown",
                    top_region=regions.most_common(1)[0][0] if regions else "unknown",
                ),
                summary=insight_summary,
                samples=samples
            ))
            
        # Rank by impact score descending
        insights.sort(key=lambda x: x.impact_score, reverse=True)
        return InsightsResponse(clusters=insights)
        
    except Exception as e:
        logger.error(f"Failed to fetch insights: {e}")
        return JSONResponse(status_code=500, content={"error": "Insights failed"})
