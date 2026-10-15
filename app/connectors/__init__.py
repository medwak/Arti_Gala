from .artic import ArticConnector
from .base import Connector
from .cleveland import ClevelandConnector
from .europeana import EuropeanaConnector
from .met import MetConnector
from .scraper import HtmlScraper, ScrapeConfig
from .smithsonian import SmithsonianConnector
from .vam import VamConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.name: c
    for c in (
        # Europe
        EuropeanaConnector,
        VamConnector,
        # North America
        MetConnector,
        ArticConnector,
        ClevelandConnector,
        SmithsonianConnector,
    )
}

__all__ = ["CONNECTORS", "Connector", "HtmlScraper", "ScrapeConfig"]
