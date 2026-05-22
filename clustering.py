import logging
import numpy as np
import hdbscan
from sentence_transformers import SentenceTransformer
from database import get_unclustered_tickets, update_cluster_labels

logger = logging.getLogger(__name__)

# 1. Initialize sentence-transformers model at module level.
# Tradeoff: Loading the model globally once prevents massive memory spikes and redundant latency across module calls.
# We wrap this in try/except to gracefully degrade if the model cannot be downloaded (e.g. HuggingFace Hub is down).
try:
    embedder = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("SentenceTransformer loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load sentence-transformers model: {e}")
    embedder = None


def process_unclustered_tickets():
    """Fetch unclustered texts, embed them, cluster, and update database records."""
    if embedder is None:
        logger.error("Cannot process tickets: embedder failed to initialize.")
        return []
    
    try:
        tickets = get_unclustered_tickets()
        if not tickets:
            logger.info("No unclustered tickets found.")
            return []
            
        texts = [t['text'] for t in tickets]
        
        # Embed texts
        logger.info(f"Embedding {len(texts)} tickets...")
        embeddings = embedder.encode(texts)
        
        # Cluster embeddings
        logger.info("Clustering embeddings with HDBSCAN...")
        clusterer = hdbscan.HDBSCAN(min_cluster_size=5)
        cluster_labels = clusterer.fit_predict(embeddings)
        
        cluster_updates = []
        for ticket, label in zip(tickets, cluster_labels):
            # Explicitly handle -1 (HDBSCAN's default for noise).
            # We map it directly to -1 to represent 'uncategorized_noise'. 
            # We do NOT force noise points into the nearest cluster.
            cluster_id = int(label) if label != -1 else -1
            cluster_updates.append((cluster_id, ticket['id']))
            
        # Update the database in batch
        update_cluster_labels(cluster_updates)
        logger.info(f"Successfully processed {len(tickets)} tickets. Clusters detected: {len(set(cluster_labels))}")
        
        return cluster_updates
    except Exception as e:
        logger.error(f"Error during clustering process: {e}")
        # Graceful degradation logic: return an empty list rather than hard-crashing caller
        return []


def calculate_impact_score(cluster_tickets):
    """
    Calculate an impact score for a cluster of tickets based on user tiers.
    
    Tradeoff: Using a coarse heuristic rule (Enterprise = 10, Pro = 3, Free = 1) instead of a 
    rigorous statistical model is completely acceptable at this weekend-project scale. 
    It acts as a fast, computationally cheap proxy for prioritization without requiring 
    historical training data or introducing complex maintenance overhead.
    """
    try:
        score = 0
        for t in cluster_tickets:
            tier = t.get('user_tier', 'Free')
            if tier == 'Enterprise':
                score += 10
            elif tier == 'Pro':
                score += 3
            else:
                score += 1
        return score
    except Exception as e:
        logger.error(f"Failed to calculate impact score: {e}")
        return 0
