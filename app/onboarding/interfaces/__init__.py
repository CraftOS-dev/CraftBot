# -*- coding: utf-8 -*-
"""
Abstract interfaces for onboarding implementations.

These interfaces define the contract that any UI implementation
(browser, CLI, future interfaces) must follow to provide onboarding.
"""

from app.onboarding.interfaces.base import OnboardingInterface
from app.onboarding.interfaces.steps import (
    HardOnboardingStep,
    IntroStep,
    ProviderStep,
    ApiKeyStep,
    UserProfileStep,
    AgentNameStep,
)

__all__ = [
    "OnboardingInterface",
    "HardOnboardingStep",
    "IntroStep",
    "ProviderStep",
    "ApiKeyStep",
    "UserProfileStep",
    "AgentNameStep",
]
