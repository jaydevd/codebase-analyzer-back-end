import time
import uuid
import tiktoken
import redis
from django.conf import settings

class VoyageRateLimiter:
    """
    A distributed rate limiter for Voyage AI embedding requests using Redis.
    Enforces a strict 3 RPM (Requests Per Minute) and 10,000 TPM (Tokens Per Minute) limit.
    """
    RPM_LIMIT = 3
    TPM_LIMIT = 10000
    WINDOW_SIZE = 60  # seconds
    
    # Prefix for redis keys
    RPM_KEY = "voyage_rpm_window"
    TPM_KEY = "voyage_tpm_window"
    
    def __init__(self):
        # We use tiktoken with the cl100k_base encoding as a standard proxy for Voyage's tokens
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def _get_redis_client(self):
        location = settings.CACHES["default"]["LOCATION"]
        if isinstance(location, list):
            location = location[0]
        return redis.from_url(location)

    def estimate_tokens(self, texts: list[str]) -> int:
        """Estimate the total token count for a list of strings."""
        if not texts:
            return 0
        # encode_batch is faster for multiple texts
        tokens = self.tokenizer.encode_batch(texts)
        return sum(len(t) for t in tokens)

    def _cleanup_old_entries(self, redis_client, key, current_time):
        """Remove entries older than the window size."""
        window_start = current_time - self.WINDOW_SIZE
        redis_client.zremrangebyscore(key, "-inf", window_start)

    def get_current_usage(self) -> tuple[int, int]:
        """Returns the current (requests_in_window, tokens_in_window)."""
        redis_client = self._get_redis_client()
        current_time = time.time()
        
        self._cleanup_old_entries(redis_client, self.RPM_KEY, current_time)
        self._cleanup_old_entries(redis_client, self.TPM_KEY, current_time)
        
        req_count = redis_client.zcard(self.RPM_KEY)
        
        # Get all token entries in the current window
        token_entries = redis_client.zrange(self.TPM_KEY, 0, -1)
        # Parse the token amounts from the values "token_amount:uuid"
        token_count = sum(int(entry.decode('utf-8').split(':')[0]) for entry in token_entries)
        
        return req_count, token_count

    def calculate_wait_time(self, requested_tokens: int) -> float:
        """
        Calculates how long to wait (in seconds) until there is enough capacity
        for the requested tokens. Returns 0 if there is immediate capacity.
        """
        redis_client = self._get_redis_client()
        current_time = time.time()
        
        self._cleanup_old_entries(redis_client, self.RPM_KEY, current_time)
        self._cleanup_old_entries(redis_client, self.TPM_KEY, current_time)
        
        req_count = redis_client.zcard(self.RPM_KEY)
        
        token_entries = redis_client.zrange(self.TPM_KEY, 0, -1, withscores=True)
        current_tokens = sum(int(entry[0].decode('utf-8').split(':')[0]) for entry in token_entries)
        
        # Check if immediate capacity exists
        if req_count < self.RPM_LIMIT and (current_tokens + requested_tokens) <= self.TPM_LIMIT:
            # Enforce an adaptive pacing: at least 20 seconds between requests
            # to spread the 3 RPM out.
            last_req = redis_client.zrange(self.RPM_KEY, -1, -1, withscores=True)
            if last_req:
                last_time = last_req[0][1]
                time_since_last = current_time - last_time
                if time_since_last < 20.0:
                    return 20.0 - time_since_last
            return 0.0
            
        # We need to wait. Find when enough capacity will free up.
        # Check when the oldest request drops off if we are at RPM limit
        req_wait = 0.0
        if req_count >= self.RPM_LIMIT:
            oldest_req = redis_client.zrange(self.RPM_KEY, 0, 0, withscores=True)
            if oldest_req:
                req_wait = (oldest_req[0][1] + self.WINDOW_SIZE) - current_time

        # Check when enough tokens drop off
        tok_wait = 0.0
        if (current_tokens + requested_tokens) > self.TPM_LIMIT:
            freed_tokens = 0
            for entry, score in token_entries:
                freed_tokens += int(entry.decode('utf-8').split(':')[0])
                if (current_tokens - freed_tokens + requested_tokens) <= self.TPM_LIMIT:
                    tok_wait = (score + self.WINDOW_SIZE) - current_time
                    break
        
        # Add a small buffer to the wait time
        wait_time = max(req_wait, tok_wait, 0)
        return wait_time + 1.0 if wait_time > 0 else 0.0

    def consume(self, tokens: int):
        """Record the consumption of a request and the given tokens."""
        redis_client = self._get_redis_client()
        current_time = time.time()
        
        # Use a transaction pipeline for atomicity
        pipeline = redis_client.pipeline()
        
        # Add request timestamp
        req_id = str(uuid.uuid4())
        pipeline.zadd(self.RPM_KEY, {req_id: current_time})
        pipeline.expire(self.RPM_KEY, self.WINDOW_SIZE + 5)
        
        # Add token count timestamp
        tok_id = f"{tokens}:{str(uuid.uuid4())}"
        pipeline.zadd(self.TPM_KEY, {tok_id: current_time})
        pipeline.expire(self.TPM_KEY, self.WINDOW_SIZE + 5)
        
        pipeline.execute()
