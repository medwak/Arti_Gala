from .artic import ArticConnector
from .base import Connector
from .cleveland import ClevelandConnector
from .met import MetConnector
from .scraper import HtmlScraper, ScrapeConfig
from .smithsonian import SmithsonianConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.name: c for c in (MetConnector, ArticConnector, ClevelandConnector, SmithsonianConnector)
}

__all__ = ["CONNECTORS", "Connector", "HtmlScraper", "ScrapeConfig"]
