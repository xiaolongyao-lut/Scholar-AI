# -*- coding: utf-8 -*-
"""
Classifier Registry Module
Provides a runtime registry for evidence classifier implementations.
"""

import logging
from typing import TYPE_CHECKING, Callable, Dict, Optional, Type, TypeVar

if TYPE_CHECKING:
    from literature_assistant.core.modules.classifier_interface import ClassifierInterface
else:
    from modules.classifier_interface import ClassifierInterface

ClassifierT = TypeVar("ClassifierT", bound=ClassifierInterface)

logger = logging.getLogger(__name__)


class ClassifierRegistry:
    """Registry for evidence classifier factories"""
    
    _registry: Dict[str, Callable[..., ClassifierInterface]] = {}
    
    @classmethod
    def register(cls, name: str, factory: Callable[..., ClassifierInterface]) -> None:
        """
        Register a classifier factory.
        
        Args:
            name: Unique name for the classifier
            factory: Callable (class or function) that returns a ClassifierInterface
        """
        cls._registry[name] = factory
        logger.info("Registered classifier: %s", name)
    
    @classmethod
    def get_factory(cls, name: str) -> Optional[Callable[..., ClassifierInterface]]:
        """Get a classifier factory by name"""
        return cls._registry.get(name)
    
    @classmethod
    def create(cls, name: str, **kwargs: object) -> ClassifierInterface:
        """
        Create a classifier instance by name.
        
        Args:
            name: Registered name
            **kwargs: Arguments for the factory
            
        Returns:
            An instance conforming to ClassifierInterface
            
        Raises:
            ValueError: If classifier name is not registered
        """
        factory = cls.get_factory(name)
        if not factory:
            raise ValueError(f"Classifier '{name}' is not registered.")
        return factory(**kwargs)

    @classmethod
    def list_registered(cls) -> list[str]:
        """List all registered classifier names"""
        return list(cls._registry.keys())


def register_classifier(
    name: str,
) -> Callable[[Type[ClassifierT]], Type[ClassifierT]]:
    """Decorator for registering classifier classes"""
    def decorator(classifier_cls: Type[ClassifierT]) -> Type[ClassifierT]:
        ClassifierRegistry.register(name, classifier_cls)
        return classifier_cls
    return decorator
