import os
import time
from typing import List, Optional
from pydantic import BaseModel


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
        self.name = "Group-Based Rate Limit"

        # Prevent Open WebUI UI overrides by setting all to None initially
        self.valves = self.Valves(
            pipelines=["*"],
            requests_per_minute=None,
            requests_per_hour=None,
            sliding_window_limit=None,
            sliding_window_minutes=None,
        )

        # Define limits per group
        self.group_limits = {
            "freemium": {
                "requests_per_minute": None,
                "requests_per_hour": 10,
                "sliding_window_limit": None,
                "sliding_window_minutes": None,
            },
            "Paid Plan": {
                "requests_per_minute": 1,
                "requests_per_hour": 3,
                "sliding_window_limit": None,
                "sliding_window_minutes": None,
            },
            "admin": None  # No limit
        }

        self.user_requests = {}

    async def on_startup(self):
        print(f"on_startup:{__name__}")

    async def on_shutdown(self):
        print(f"on_shutdown:{__name__}")

    def prune_requests(self, user_id: str):
        """Remove requests outside of their valid window."""
        now = time.time()
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req for req in self.user_requests[user_id]
                if (
                    (self.valves.requests_per_minute and now - req < 60)
                    or (self.valves.requests_per_hour and now - req < 3600)
                    or (
                        self.valves.sliding_window_limit
                        and now - req < self.valves.sliding_window_minutes * 60
                    )
                )
            ]

    def log_request(self, user_id: str):
        """Store the timestamp of the user's request."""
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
        print(f"Request body: {body}")
        print(f"User object: {user}")

        role = user.get("role", "user")
        user_id = user.get("id", "default_user")

        if role == "admin":
            print("Admin detected, bypassing limits.")
            return body

        group = user.get("group", "freemium")  # default to freemium
        print(f"Detected group: {group}")

        limits = self.group_limits.get(group)
        if limits is None:
            print("No limits for group (unlimited).")
            return body

        # Dynamically assign limits based on group
        self.valves = self.Valves(
            pipelines=["*"],
            requests_per_minute=limits["requests_per_minute"],
            requests_per_hour=limits["requests_per_hour"],
            sliding_window_limit=limits["sliding_window_limit"],
            sliding_window_minutes=limits["sliding_window_minutes"],
        )

        print(f"Applied limits: {self.valves.dict()}")

        if self.rate_limited(user_id):
            print(f"User {user_id} in group '{group}' is rate limited.")
            raise Exception(f"Rate limit exceeded for group '{group}'. Please try again later.")

        self.log_request(user_id)
        print(f"Logged request for user {user_id}")
        return body
