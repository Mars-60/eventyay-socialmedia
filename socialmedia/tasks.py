import logging

from eventyay.celery_app import app

from .models import SocialMediaPostStatus
from .providers.registry import get_provider
from .signals import claim_and_resolve_generic_post, claim_post_for_publishing

logger = logging.getLogger(__name__)


@app.task
def publish_single_post(post_pk: int, provider_name: str):
    """Celery task to publish a single scheduled social media post asynchronously.

    Claims the post using database row locking (select_for_update) and executes
    the provider's publish_post call off the main periodic beat thread.
    """
    logger.info(
        "Executing publish_single_post task for post %s (provider: %s).",
        post_pk,
        provider_name,
    )
    claimed_post, account = claim_post_for_publishing(post_pk, provider_name)
    if not claimed_post or not account:
        logger.warning(
            "Post %s could not be claimed or active %s account missing for organizer.",
            post_pk,
            provider_name,
        )
        return

    try:
        provider = get_provider(account)
        media = [claimed_post.media_url] if claimed_post.media_url else None
        logger.info(
            "Calling %s API to publish post %s (with_media=%s)...",
            provider_name,
            post_pk,
            bool(media),
        )
        provider.publish_post(text=claimed_post.post_text, media=media)
        claimed_post.status = SocialMediaPostStatus.PUBLISHED
        claimed_post.error_message = ""
        claimed_post.save(update_fields=["status", "error_message", "updated_at"])
        logger.info(
            "Successfully published post %s to %s (status -> PUBLISHED).",
            post_pk,
            provider_name,
        )
    except Exception as e:
        logger.error(
            "Failed to publish post %s to %s: %s (status -> FAILED).",
            post_pk,
            provider_name,
            e,
            exc_info=True,
        )
        claimed_post.status = SocialMediaPostStatus.FAILED
        claimed_post.error_message = str(e)
        claimed_post.save(update_fields=["status", "error_message", "updated_at"])


@app.task
def publish_generic_post(post_pk: int):
    """Celery task to publish a generic scheduled social media post asynchronously.

    Claims the generic post and publishes sequentially to all active accounts,
    aggregating failures to ensure the logical post is marked FAILED if any provider fails.
    """
    logger.info(
        "Executing publish_generic_post task for generic post %s.",
        post_pk,
    )
    claimed_post, active_accounts = claim_and_resolve_generic_post(post_pk)
    if not claimed_post or not active_accounts:
        logger.warning(
            "Generic post %s could not be claimed or no active accounts found.",
            post_pk,
        )
        return

    errors = []
    published_providers = []

    for account in active_accounts:
        try:
            provider = get_provider(account)
            media = [claimed_post.media_url] if claimed_post.media_url else None
            logger.info(
                "Calling %s API to publish generic post %s (with_media=%s)...",
                account.provider,
                post_pk,
                bool(media),
            )
            provider.publish_post(text=claimed_post.post_text, media=media)
            published_providers.append(account.provider)
            logger.info(
                "Successfully published generic post %s to %s.",
                post_pk,
                account.provider,
            )
        except Exception as e:
            errors.append(f"{account.provider}: {str(e)}")
            logger.error(
                "Failed to publish generic post %s to %s: %s.",
                post_pk,
                account.provider,
                e,
                exc_info=True,
            )

    if errors:
        claimed_post.status = SocialMediaPostStatus.FAILED
        err_details = "; ".join(errors)
        if published_providers:
            succ = ", ".join(published_providers)
            claimed_post.error_message = f"Published to ({succ}). Errors: {err_details}"
        else:
            claimed_post.error_message = err_details
        claimed_post.save(update_fields=["status", "error_message", "updated_at"])
        logger.warning(
            "Generic post %s finished with partial or total failures (status -> FAILED).",
            post_pk,
        )
    else:
        claimed_post.status = SocialMediaPostStatus.PUBLISHED
        claimed_post.error_message = ""
        claimed_post.save(update_fields=["status", "error_message", "updated_at"])
        logger.info(
            "Successfully published generic post %s to all accounts (status -> PUBLISHED).",
            post_pk,
        )
