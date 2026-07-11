"""Canonical input connectors."""

from guardian_voc.connectors.base import FeedbackConnector, ImportIssue, ImportPreview
from guardian_voc.connectors.file_import import (
    FileImportConnector,
    QuarantinedRow,
    preview_import,
)
from guardian_voc.connectors.mapping_profiles import (
    MappingProfile,
    get_profile,
    list_profiles,
)
from guardian_voc.connectors.marketplace_api import (
    LazadaCredentials,
    LazadaReviewConnector,
    MarketplaceAPIError,
    MarketplaceAuthorizationError,
    MarketplaceCredentialsError,
    MarketplaceReconciliationManifest,
    ShopeeCredentials,
    ShopeeReviewConnector,
)
from guardian_voc.connectors.page_reader import (
    CachedPageReader,
    FallbackPageReader,
    MetadataPageReader,
    PageContent,
    PageReader,
    TinyFishPageReader,
)
from guardian_voc.connectors.public_social import (
    LiveSocialCrawlerConnector,
    PublicSocialConnector,
    SocialCrawlerConnector,
)

__all__ = [
    "CachedPageReader",
    "FallbackPageReader",
    "FeedbackConnector",
    "FileImportConnector",
    "ImportIssue",
    "ImportPreview",
    "LiveSocialCrawlerConnector",
    "LazadaCredentials",
    "LazadaReviewConnector",
    "MappingProfile",
    "MarketplaceAPIError",
    "MarketplaceAuthorizationError",
    "MarketplaceCredentialsError",
    "MarketplaceReconciliationManifest",
    "MetadataPageReader",
    "PageContent",
    "PageReader",
    "PublicSocialConnector",
    "QuarantinedRow",
    "SocialCrawlerConnector",
    "ShopeeCredentials",
    "ShopeeReviewConnector",
    "TinyFishPageReader",
    "get_profile",
    "list_profiles",
    "preview_import",
]
