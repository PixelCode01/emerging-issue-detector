import random
import uuid
import logging
from datetime import datetime, timedelta, timezone
from database import init_db, insert_ticket

# Use standard logging instead of prints
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rule 1: Determinism. Ensures datasets are reproducible across runs.
random.seed(42)

REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]
TIERS = ["Free", "Pro", "Enterprise"]
SOURCES = ["email", "in-app", "slack"]
SDK_VERSIONS = ["v0.13", "v0.14", "v0.15"]

# True Noise Pool
NOISE_PHRASES = ["ok thanks", "ping", "nvm", "??", "fixed it", "hello", "thx", "test ticket", "ignore this", "any update?"]

def generate_ticket():
    """
    Generates a single ticket dictionary based on the predefined correlation rules.
    """
    now = datetime.now(timezone.utc)
    ticket_id = str(uuid.uuid4())
    
    # Rule 3: 50% true noise
    if random.random() < 0.5:
        return {
            "id": ticket_id,
            "text": random.choice(NOISE_PHRASES),
            "timestamp": (now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 24))).isoformat(),
            "sdk_version": random.choice(SDK_VERSIONS),
            "region": random.choice(REGIONS),
            "user_tier": random.choice(TIERS),
            "source": random.choice(SOURCES),
            "embedding": None
        }

    # Signal Generation (Topics A, B, C)
    topic = random.choices(["A", "B", "C"], weights=[0.4, 0.3, 0.3])[0]
    
    # Base defaults
    region = random.choice(REGIONS)
    user_tier = random.choice(TIERS)
    source = random.choice(SOURCES)
    sdk_version = random.choice(SDK_VERSIONS)
    timestamp = now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 24))
    
    # Apply Topic Correlations
    if topic == "A":  
        # Topic A: "Webhook timeouts" spiked heavily in the last 24h, strongly correlated with sdk_version=v0.14 and region=eu-west.
        timestamp = now - timedelta(hours=random.randint(0, 23))
        sdk_version = "v0.14"
        region = "eu-west"
        
        if user_tier == "Enterprise":
            text = "Critical: Events dropping in eu-west blocking downstream pipelines due to webhook timeouts!"
        elif user_tier == "Free":
            text = "webhok broken?"  # Rule 4: Typos
        else:
            text = "Getting webhook timeouts constantly."

    elif topic == "B":  
        # Topic B: "SAML SSO" requests strictly from Enterprise/Pro tiers via source=email.
        user_tier = random.choice(["Pro", "Enterprise"])
        source = "email"
        
        if user_tier == "Enterprise":
            text = "Urgent: SAML SSO integration failing for our primary tenant. Employees cannot log in."
        else:
            text = "Need help setting up SAML SSO for our team."
            
    else:  
        # Topic C: "Dashboard Latency" weakly correlated with region=ap-south.
        if random.random() < 0.6:  # Weak correlation
            region = "ap-south"
        
        if user_tier == "Enterprise":
            text = "High priority: The metrics dashbord is experiencing severe latency, affecting reporting." # Rule 4: Typos
        else:
            text = "dashbord slow"
            
    return {
        "id": ticket_id,
        "text": text,
        "timestamp": timestamp.isoformat(),
        "sdk_version": sdk_version,
        "region": region,
        "user_tier": user_tier,
        "source": source,
        "embedding": None
    }

def main():
    logger.info("Generating 500 synthetic tickets...")
    
    # Tradeoff: Reusing the existing single-insert `insert_ticket` function inside a loop 
    # instead of writing a new bulk insert function. For 500 records, the overhead is negligible 
    # and it keeps the database abstraction thin and focused.
    successful_inserts = 0
    for _ in range(500):
        t = generate_ticket()
        try:
            insert_ticket(
                ticket_id=t["id"],
                text=t["text"],
                timestamp=t["timestamp"],
                sdk_version=t["sdk_version"],
                region=t["region"],
                user_tier=t["user_tier"],
                source=t["source"],
                embedding=t["embedding"]
            )
            successful_inserts += 1
        except Exception as e:
            # Graceful degradation logic: Do not crash the entire generation process if one insert fails
            logger.error(f"Failed to insert ticket {t['id']}: {e}")

    logger.info(f"Data generation complete. Inserted {successful_inserts} tickets.")

if __name__ == "__main__":
    init_db()
    main()
