import os
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from schemas import OpenAIChatMessage
import time


class Pipeline:
    class Valves(BaseModel):
        # List target pipeline ids (models) that this filter will be connected to.
        # If you want to connect this filter to all pipelines, you can set pipelines to ["*"]
        pipelines: List[str] = ["*"]

        # Assign a priority level to the filter pipeline.
        # The priority level determines the order in which the filter pipelines are executed.
        # The lower the number, the higher the priority.
        priority: int = 0

        # Default rate limits (for users without a group)
        default_requests_per_minute: Optional[int] = 5
        default_requests_per_hour: Optional[int] = 100
        default_sliding_window_limit: Optional[int] = 25
        default_sliding_window_minutes: Optional[int] = 15

        # Rate limits for paid plan users
        paid_requests_per_minute: Optional[int] = 20
        paid_requests_per_hour: Optional[int] = 1000
        paid_sliding_window_limit: Optional[int] = 250
        paid_sliding_window_minutes: Optional[int] = 30
        
        # You can add more user groups here as needed
        # Example: premium_requests_per_minute: Optional[int] = 50

    def __init__(self):
        # Pipeline filters are only compatible with Open WebUI
        self.type = "filter"
        self.name = "Group-based Rate Limit Filter"

        # Initialize rate limits from environment variables or use defaults
        self.valves = self.Valves(
            **{
                "pipelines": os.getenv("RATE_LIMIT_PIPELINES", "*").split(","),
                
                # Default user limits
                "default_requests_per_minute": int(
                    os.getenv("DEFAULT_RATE_LIMIT_RPM", 5)
                ),
                "default_requests_per_hour": int(
                    os.getenv("DEFAULT_RATE_LIMIT_RPH", 100)
                ),
                "default_sliding_window_limit": int(
                    os.getenv("DEFAULT_RATE_LIMIT_SWL", 25)
                ),
                "default_sliding_window_minutes": int(
                    os.getenv("DEFAULT_RATE_LIMIT_SWM", 15)
                ),
                
                # Paid user limits
                "paid_requests_per_minute": int(
                    os.getenv("PAID_RATE_LIMIT_RPM", 20)
                ),
                "paid_requests_per_hour": int(
                    os.getenv("PAID_RATE_LIMIT_RPH", 1000)
                ),
                "paid_sliding_window_limit": int(
                    os.getenv("PAID_RATE_LIMIT_SWL", 250)
                ),
                "paid_sliding_window_minutes": int(
                    os.getenv("PAID_RATE_LIMIT_SWM", 30)
                ),
            }
        )

        # Tracking data - user_id -> (timestamps of requests)
        self.user_requests = {}

    async def on_startup(self):
        print(f"on_startup:{__name__}")
        pass

    async def on_shutdown(self):
        print(f"on_shutdown:{__name__}")
        pass

    def get_user_limits(self, user: Optional[dict]) -> Dict:
        """
        Get the appropriate rate limits for the user based on their group.
        """
        # Default rate limits for users without a group
        limits = {
            "requests_per_minute": self.valves.default_requests_per_minute,
            "requests_per_hour": self.valves.default_requests_per_hour,
            "sliding_window_limit": self.valves.default_sliding_window_limit,
            "sliding_window_minutes": self.valves.default_sliding_window_minutes
        }
        
        # Check if user is authenticated and has groups
        if user and "groups" in user and user["groups"]:
            # Check if user is in the "Paid" group
            if "Paid" in user["groups"]:
                limits = {
                    "requests_per_minute": self.valves.paid_requests_per_minute,
                    "requests_per_hour": self.valves.paid_requests_per_hour,
                    "sliding_window_limit": self.valves.paid_sliding_window_limit,
                    "sliding_window_minutes": self.valves.paid_sliding_window_minutes
                }
            
            # Add additional group checks here if needed
            # Example:
            # elif "Premium Plan" in user["groups"]:
            #     limits = {...premium limits...}
        
        return limits

    def prune_requests(self, user_id: str, limits: Dict):
        """Prune old requests that are outside of the sliding window period."""
        now = time.time()
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req
                for req in self.user_requests[user_id]
                if (
                    (limits["requests_per_minute"] is not None and now - req < 60)
                    or (limits["requests_per_hour"] is not None and now - req < 3600)
                    or (
                        limits["sliding_window_limit"] is not None
                        and now - req < limits["sliding_window_minutes"] * 60
                    )
                )
            ]

    def log_request(self, user_id: str):
        """Log a new request for a user."""
        now = time.time()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = []
        self.user_requests[user_id].append(now)

    def rate_limited(self, user_id: str, limits: Dict) -> bool:
        """Check if a user is rate limited based on their group's limits."""
        self.prune_requests(user_id, limits)

        user_reqs = self.user_requests.get(user_id, [])

        if limits["requests_per_minute"] is not None:
            requests_last_minute = sum(1 for req in user_reqs if time.time() - req < 60)
            if requests_last_minute >= limits["requests_per_minute"]:
                return True

        if limits["requests_per_hour"] is not None:
            requests_last_hour = sum(1 for req in user_reqs if time.time() - req < 3600)
            if requests_last_hour >= limits["requests_per_hour"]:
                return True

        if limits["sliding_window_limit"] is not None:
            requests_in_window = len(user_reqs)
            if requests_in_window >= limits["sliding_window_limit"]:
                return True

        return False

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        print(f"pipe:{__name__}")
        
        # Skip rate limiting for admins
        if user and user.get("role") == "admin":
            return body
            
        # Get user ID or use a default
        user_id = user["id"] if user and "id" in user else "default_user"
        
        # Get the appropriate limits for this user based on their group
        user_limits = self.get_user_limits(user)
        
        # Check if user is rate limited
        if self.rate_limited(user_id, user_limits):
            # Determine which limit was exceeded for better error messaging
            if user and "groups" in user and "Paid" in user["groups"]:
                plan_type = "Paid"
            else:
                plan_type = "Free Plan"
                
            raise Exception(f"Rate limit exceeded for {plan_type}. Please try again later.")

        # Log this request
        self.log_request(user_id)
        
        return body