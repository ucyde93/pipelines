import os
from typing import List, Optional
from pydantic import BaseModel
import time


class Pipeline:
    class Valves(BaseModel):
        pipelines: List[str] = []
        priority: int = 0
        requests_per_minute: Optional[int] = None
        requests_per_hour: Optional[int] = None
        sliding_window_limit: Optional[int] = None
        sliding_window_minutes: Optional[int] = None

    def __init__(self):
        self.type = "filter"
        self.name = "Rate Limit Filter"

        # Default valve setup (overwritten dynamically below)
        self.valves = self.Valves(
            pipelines=["*"],
            requests_per_minute=None,
            requests_per_hour=None,
            sliding_window_limit=None,
            sliding_window_minutes=None,
        )

        # Rate limit configs per group
        self.group_limits = {
            "freemium": {
                "requests_per_minute": None,
                "requests_per_hour": 10,
                "sliding_window_limit": None,
                "sliding_window_minutes": None,
            },
            "Paid Plan": {
                "requests_per_minute": None,
                "requests_per_hour": 3,
                "sliding_window_limit": None,
                "sliding_window_minutes": None,
            },
            "admin": None  # Unlimited
        }

        self.user_requests = {}

    async def on_startup(self):
        print(f"on_startup:{__name__}")

    async def on_shutdown(self):
        print(f"on_shutdown:{__name__}")

    def prune_requests(self, user_id: str):
        """Prune old requests outside rate windows."""
        now = time.time()
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req for req in self.user_requests[user_id]
                if (
                    (self.valves.requests_per_minute and now - req < 60) or
                    (self.valves.requests_per_hour and now - req < 3600) or
                    (self.valves.sliding_window_limit and now - req < self.valves.sliding_window_minutes * 60)
                )
            ]

    def log_request(self, user_id: str):
        now = time.time()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = []
        self.user_requests[user_id].append(now)

    def rate_limited(self, user_id: str) -> bool:
        self.prune_requests(user_id)
        user_reqs = self.user_requests.get(user_id, [])

        if self.valves.requests_per_minute is not None:
            if sum(1 for r in user_reqs if time.time() - r < 60) >= self.valves.requests_per_minute:
                return True

        if self.valves.requests_per_hour is not None:
            if sum(1 for r in user_reqs if time.time() - r < 3600) >= self.valves.requests_per_hour:
                return True

        if self.valves.sliding_window_limit is not None:
            if len(user_reqs) >= self.valves.sliding_window_limit:
                return True

        return False

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        print(f"pipe:{__name__}")
        print(body)
        print(user)

        role = user.get("role", "user")
        user_id = user.get("id", "default_user")

        if role == "admin":
            return body  # No rate limit

        group = user.get("group", "freemium")  # fallback if no group
        limits = self.group_limits.get(group)

        if limits is None:
            return body  # Unlimited group

        # Set dynamic limits
        self.valves = self.Valves(
            pipelines=["*"],
            requests_per_minute=limits["requests_per_minute"],
            requests_per_hour=limits["requests_per_hour"],
            sliding_window_limit=limits["sliding_window_limit"],
            sliding_window_minutes=limits["sliding_window_minutes"],
        )

        if self.rate_limited(user_id):
            raise Exception(f"Rate limit exceeded for group '{group}'. Please try again later.")

        self.log_request(user_id)
        return body
