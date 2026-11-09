from rest_framework.throttling import UserRateThrottle


class AIRateThrottle(UserRateThrottle):
    """Per-user cap on calls that spend paid AI-provider tokens."""
    scope = 'ai'
