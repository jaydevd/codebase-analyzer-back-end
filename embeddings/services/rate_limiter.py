import time
import uuid
import tiktoken
import redis
from django.conf import settings
from common.constants import VOYAGE_RPM_LIMIT, VOYAGE_TPM_LIMIT

class VoyageRateLimiter:
    RPM_LIMIT = VOYAGE_RPM_LIMIT
    TPM_LIMIT = VOYAGE_TPM_LIMIT
    WINDOW_SIZE = 60
    MIN_GAP = WINDOW_SIZE / max(RPM_LIMIT, 1)

    RPM_KEY = "voyage_rpm_window"
    TPM_KEY = "voyage_tpm_window"

    def __init__(self):
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def _get_redis_client(self):
        location = settings.CACHES["default"]["LOCATION"]
        if isinstance(location, list):
            location = location[0]
        return redis.from_url(location)

    def estimate_tokens(self, texts: list[str]) -> int:
        if not texts:
            return 0
        tokens = self.tokenizer.encode_batch(texts)
        return sum(len(t) for t in tokens)

    def _cleanup_old_entries(self, redis_client, key, current_time):
        window_start = current_time - self.WINDOW_SIZE
        redis_client.zremrangebyscore(key, "-inf", window_start)

    def get_current_usage(self) -> tuple[int, int]:
        redis_client = self._get_redis_client()
        current_time = time.time()

        self._cleanup_old_entries(redis_client, self.RPM_KEY, current_time)
        self._cleanup_old_entries(redis_client, self.TPM_KEY, current_time)

        req_count = redis_client.zcard(self.RPM_KEY)

        token_entries = redis_client.zrange(self.TPM_KEY, 0, -1)
        token_count = sum(int(entry.decode('utf-8').split(':')[0]) for entry in token_entries)

        return req_count, token_count

    def calculate_wait_time(self, requested_tokens: int) -> float:
        redis_client = self._get_redis_client()
        current_time = time.time()

        self._cleanup_old_entries(redis_client, self.RPM_KEY, current_time)
        self._cleanup_old_entries(redis_client, self.TPM_KEY, current_time)

        req_count = redis_client.zcard(self.RPM_KEY)

        token_entries = redis_client.zrange(self.TPM_KEY, 0, -1, withscores=True)
        current_tokens = sum(int(entry[0].decode('utf-8').split(':')[0]) for entry in token_entries)

        has_rpm_capacity = req_count < self.RPM_LIMIT
        has_tpm_capacity = (current_tokens + requested_tokens) <= self.TPM_LIMIT

        if has_rpm_capacity and has_tpm_capacity:
            near_capacity = (
                req_count >= self.RPM_LIMIT - 1
                or (current_tokens + requested_tokens) >= self.TPM_LIMIT * 0.8
            )
            if near_capacity:
                last_req = redis_client.zrange(self.RPM_KEY, -1, -1, withscores=True)
                if last_req:
                    time_since_last = current_time - last_req[0][1]
                    if time_since_last < self.MIN_GAP:
                        return self.MIN_GAP - time_since_last
            return 0.0

        req_wait = 0.0
        if req_count >= self.RPM_LIMIT:
            oldest_req = redis_client.zrange(self.RPM_KEY, 0, 0, withscores=True)
            if oldest_req:
                req_wait = (oldest_req[0][1] + self.WINDOW_SIZE) - current_time

        tok_wait = 0.0
        if (current_tokens + requested_tokens) > self.TPM_LIMIT:
            freed_tokens = 0
            for entry, score in token_entries:
                freed_tokens += int(entry.decode('utf-8').split(':')[0])
                if (current_tokens - freed_tokens + requested_tokens) <= self.TPM_LIMIT:
                    tok_wait = (score + self.WINDOW_SIZE) - current_time
                    break

        wait_time = max(req_wait, tok_wait, 0)
        return wait_time + 1.0 if wait_time > 0 else 0.0

    def consume(self, tokens: int):
        redis_client = self._get_redis_client()
        current_time = time.time()

        pipeline = redis_client.pipeline()

        req_id = str(uuid.uuid4())
        pipeline.zadd(self.RPM_KEY, {req_id: current_time})
        pipeline.expire(self.RPM_KEY, self.WINDOW_SIZE + 5)

        tok_id = f"{tokens}:{str(uuid.uuid4())}"
        pipeline.zadd(self.TPM_KEY, {tok_id: current_time})
        pipeline.expire(self.TPM_KEY, self.WINDOW_SIZE + 5)

        pipeline.execute()
