# -*- coding: utf-8 -*-
"""Scoring Registry - Manages discovery and instantiation of scoring plugins."""

import logging
from typing import Dict, Type, Any, Callable
from modules.scoring_interface import ScoringInterface

logger = logging.getLogger(__name__)


class ScoringRegistry:
    """Registry for ScoringInterface implementations."""

    _registry: Dict[str, Type[ScoringInterface]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[ScoringInterface]], Type[ScoringInterface]]:
        """Decorator to register a scoring class."""
        def decorator(subclass: Type[ScoringInterface]) -> Type[ScoringInterface]:
            cls._registry[name] = subclass
            logger.debug(f"Registered scoring plugin: {name}")
            return subclass
        return decorator

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> ScoringInterface:
        """Create a scoring instance by name."""
        if name not in cls._registry:
            logger.warning(f"Scoring plugin '{name}' not found. Falling back to 'default'.")
            name = "default"
            
        if name not in cls._registry:
            raise ValueError(f"No scoring plugins registered, including 'default'.")
            
        scoring_cls = cls._registry[name]
        return scoring_cls(**kwargs)

    @classmethod
    def list_plugins(cls) -> list[str]:
        """List all registered plugins."""
        return list(cls._registry.keys())
