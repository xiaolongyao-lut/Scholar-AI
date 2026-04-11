"""
Dependency Injection Container

Provides IoC (Inversion of Control) for easy dependency management and testing.
"""

from typing import Dict, Callable, Any, Optional, TypeVar, Generic
from modules.logger_config import get_logger

logger = get_logger("scoring_system.container")

T = TypeVar("T")


class ServiceContainer(Generic[T]):
    """Simple service container for dependency injection"""

    def __init__(self):
        """Initialize container"""
        self._services: Dict[str, tuple[Callable, bool]] = {}
        self._singletons: Dict[str, Any] = {}
        self._aliases: Dict[str, str] = {}

    def register(
        self,
        name: str,
        factory: Callable,
        singleton: bool = True,
        aliases: Optional[list] = None,
    ) -> "ServiceContainer":
        """
        Register a service in the container

        Args:
            name: Service name
            factory: Factory function to create service
            singleton: If True, only one instance will be created
            aliases: List of alternative names for this service

        Returns:
            Self for method chaining
        """
        self._services[name] = (factory, singleton)
        logger.debug("Registered service: %s (singleton=%s)", name, singleton)

        # Register aliases
        if aliases:
            for alias in aliases:
                self._aliases[alias] = name
                logger.debug("Registered alias: %s -> %s", alias, name)

        return self

    def get(self, name: str, **kwargs) -> Any:
        """
        Get service instance from container

        Args:
            name: Service name
            **kwargs: Arguments to pass to factory

        Returns:
            Service instance

        Raises:
            KeyError: If service not found
        """
        # Check if it's an alias
        actual_name = self._aliases.get(name, name)

        if actual_name not in self._services:
            raise KeyError(f"Service not registered: {actual_name}")

        factory, is_singleton = self._services[actual_name]

        # Return singleton if already created
        if is_singleton:
            if actual_name not in self._singletons:
                instance = factory(**kwargs)
                self._singletons[actual_name] = instance
                logger.debug("Created singleton instance: %s", actual_name)
            return self._singletons[actual_name]

        # Create new instance for transient service
        return factory(**kwargs)

    def has(self, name: str) -> bool:
        """Check if service is registered"""
        return name in self._services or name in self._aliases

    def service_count(self) -> int:
        """Get the number of registered services"""
        return len(self._services)

    def clear_singletons(self) -> None:
        """Clear all singleton instances"""
        self._singletons.clear()
        logger.info("Cleared all singleton instances")

    def register_instance(self, name: str, instance: Any, aliases: Optional[list] = None) -> "ServiceContainer":
        """
        Register a specific instance as a singleton

        Args:
            name: Service name
            instance: Instance to register
            aliases: List of alternative names

        Returns:
            Self for method chaining
        """
        self._services[name] = (lambda: instance, True)
        self._singletons[name] = instance

        if aliases:
            for alias in aliases:
                self._aliases[alias] = name

        logger.debug("Registered instance: %s", name)
        return self

    def __repr__(self) -> str:
        return f"ServiceContainer(services={len(self._services)}, singletons={len(self._singletons)})"


class ContainerBuilder:
    """Builder pattern for constructing containers"""

    def __init__(self):
        """Initialize builder"""
        self.container = ServiceContainer()

    def add_configuration(
        self, config_path: Optional[str] = None
    ) -> "ContainerBuilder":
        """Add configuration service"""
        from modules.configuration_manager import ConfigurationManager

        def config_factory():
            return ConfigurationManager(config_path)

        self.container.register(
            "config",
            config_factory,
            singleton=True,
            aliases=["configuration"],
        )
        return self

    def add_classifier(self) -> "ContainerBuilder":
        """Add evidence classifier service using registry"""
        from modules.classifier_registry import ClassifierRegistry
        import modules.evidence_classifier # Ensure default is registered

        def classifier_factory():
            config = self.container.get("config")
            # Resolve name from config or default
            name = config.config.get("classifier", "default")
            return ClassifierRegistry.create(name, config_manager=config)

        self.container.register(
            "classifier",
            classifier_factory,
            singleton=True,
            aliases=["evidence_classifier"],
        )
        return self

    def add_scorer(self) -> "ContainerBuilder":
        """Add scoring engine service using registry"""
        from modules.scoring_registry import ScoringRegistry
        import modules.default_scorer # Ensure default is registered

        def scorer_factory():
            config = self.container.get("config")
            # Resolve name from config or default
            name = config.config.get("scorer", "default")
            return ScoringRegistry.create(name)

        self.container.register(
            "scorer",
            scorer_factory,
            singleton=True,
            aliases=["scoring_engine"],
        )
        return self

    def add_processor(self) -> "ContainerBuilder":
        """Add paper processor service"""
        from modules.paper_processor import PaperProcessor

        def processor_factory():
            config = self.container.get("config")
            classifier = self.container.get("classifier")
            scorer = self.container.get("scorer")
            return PaperProcessor(config, classifier=classifier, scorer=scorer)

        self.container.register(
            "processor",
            processor_factory,
            singleton=True,
            aliases=["paper_processor"],
        )
        return self

    def add_batch_manager(self) -> "ContainerBuilder":
        """Add batch manager service"""
        from modules.batch_manager import BatchManager

        def batch_factory():
            config = self.container.get("config")
            return BatchManager(config)

        self.container.register(
            "batch_manager",
            batch_factory,
            singleton=True,
        )
        return self

    def add_exporter(self) -> "ContainerBuilder":
        """Add result exporter service"""
        from modules.result_exporter import ResultExporter

        def exporter_factory():
            config = self.container.get("config")
            return ResultExporter(config)

        self.container.register(
            "exporter",
            exporter_factory,
            singleton=True,
            aliases=["result_exporter"],
        )
        return self

    def add_observer(self) -> "ContainerBuilder":
        """Add pipeline observability service"""
        from modules.pipeline_observer import PipelineObserver
        from modules.composite_observer import CompositeObserver, LoggingObserver, MetricsObserver

        def observer_factory():
            return CompositeObserver([
                LoggingObserver(),
                MetricsObserver()
            ])

        self.container.register(
            "observer",
            observer_factory,
            singleton=True,
            aliases=["pipeline_observer"],
        )
        return self

    def add_cache(self) -> "ContainerBuilder":
        """Add cache service"""
        from modules.cache_manager import CacheManager

        def cache_factory():
            return CacheManager(max_size=10000, ttl_seconds=3600)

        self.container.register(
            "cache",
            cache_factory,
            singleton=True,
        )
        return self

    def build(self) -> ServiceContainer:
        """Build and return the container"""
        service_count = self.container.service_count()
        logger.info("Built container with %d services", service_count)
        return self.container


def create_default_container(config_path: Optional[str] = None) -> ServiceContainer:
    """
    Create a fully configured default container

    Args:
        config_path: Path to configuration file

    Returns:
        Configured ServiceContainer
    """
    builder = ContainerBuilder()
    return (
        builder.add_configuration(config_path)
        .add_classifier()
        .add_scorer()
        .add_observer()
        .add_processor()
        .add_batch_manager()
        .add_exporter()
        .add_cache()
        .build()
    )
