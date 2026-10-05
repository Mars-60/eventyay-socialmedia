from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils.timezone import now
from django_scopes import scope

from socialmedia.models import (
    SocialMediaAccount,
    SocialMediaPost,
    SocialMediaPostStatus,
)
from socialmedia.providers.base import PublishingError
from socialmedia.providers.mastodon import MastodonProvider
from socialmedia.providers.telegram import TelegramProvider
from socialmedia.signals import publish_scheduled_posts


@pytest.mark.django_db
def test_publish_scheduled_posts_success(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Create active account for Telegram
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    # Create due post
    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Hello Telegram!",
            media_url="https://testserver/img.jpg",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch.object(
        TelegramProvider,
        "publish_post",
        return_value={"post_id": "123", "url": "https://t.me/123"},
    ) as mock_publish:
        publish_scheduled_posts(sender=None)

        mock_publish.assert_called_once_with(
            text="Hello Telegram!", media=["https://testserver/img.jpg"]
        )

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.PUBLISHED
        assert post.error_message == ""


@pytest.mark.django_db
def test_publish_scheduled_posts_failure(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Create active account for Mastodon
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="mastodon",
        platform_username="test_user",
        is_active=True,
    )
    account.credentials = {
        "api_base_url": "https://mastodon.social",
        "access_token": "fake_token",
    }
    account.save()

    # Create due post
    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="session",
            entity_id="session_1_mastodon",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Hello Mastodon!",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch.object(
        MastodonProvider,
        "publish_post",
        side_effect=PublishingError("API rate limit exceeded"),
    ) as mock_publish:
        publish_scheduled_posts(sender=None)

        mock_publish.assert_called_once_with(text="Hello Mastodon!", media=None)

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.FAILED
        assert post.error_message == "API rate limit exceeded"


@pytest.mark.django_db
def test_publish_scheduled_posts_missing_account(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # No social media accounts created

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="session",
            entity_id="session_1_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Hello Telegram!",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    publish_scheduled_posts(sender=None)

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.FAILED
        assert "No active telegram account found" in post.error_message


@pytest.mark.django_db
def test_publish_scheduled_posts_future_or_other_status(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Create active account
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    with scope(organizer=organizer, event=event):
        # Future post
        post_future = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_telegram",
            scheduled_at=now() + timedelta(minutes=15),
            post_text="Future Telegram!",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )
        # Excluded/Draft/Published posts
        post_published = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_2_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Already published!",
            status=SocialMediaPostStatus.PUBLISHED,
            is_pinned=True,
        )
        post_draft = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_3_draft",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Draft post!",
            status=SocialMediaPostStatus.DRAFT,
            is_pinned=True,
        )

    with patch.object(TelegramProvider, "publish_post") as mock_publish:
        publish_scheduled_posts(sender=None)
        mock_publish.assert_not_called()

    with scope(organizer=organizer, event=event):
        post_future.refresh_from_db()
        assert post_future.status == SocialMediaPostStatus.SCHEDULED

        post_published.refresh_from_db()
        assert post_published.status == SocialMediaPostStatus.PUBLISHED

        post_draft.refresh_from_db()
        assert post_draft.status == SocialMediaPostStatus.DRAFT


@pytest.mark.django_db
def test_publish_scheduled_posts_auto_publishes_unpinned_posts_when_enabled(
    organizer, event, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    with scope(organizer=organizer, event=event):
        event.settings.set("socialmedia_auto_publish", True)
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Unpinned auto published post",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=False,
        )

    with patch.object(
        TelegramProvider,
        "publish_post",
        return_value={"post_id": "123", "url": "https://t.me/123"},
    ) as mock_publish:
        publish_scheduled_posts(sender=None)
        mock_publish.assert_called_once_with(
            text="Unpinned auto published post", media=None
        )

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.PUBLISHED


@pytest.mark.django_db
def test_publish_scheduled_posts_skips_unpinned_when_auto_publish_disabled(
    organizer, event, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    with scope(organizer=organizer, event=event):
        event.settings.set("socialmedia_auto_publish", False)
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Unpinned post should be skipped",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=False,
        )

    with patch.object(TelegramProvider, "publish_post") as mock_publish:
        publish_scheduled_posts(sender=None)
        mock_publish.assert_not_called()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.SCHEDULED


@pytest.mark.django_db
def test_publish_single_post_task_directly(organizer, event):
    from socialmedia.tasks import publish_single_post

    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_telegram",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Hello Direct Task!",
            status=SocialMediaPostStatus.SCHEDULED,
        )

    with patch.object(
        TelegramProvider,
        "publish_post",
        return_value={"post_id": "123", "url": "https://t.me/123"},
    ) as mock_publish:
        publish_single_post(post.pk, "telegram")
        mock_publish.assert_called_once_with(text="Hello Direct Task!", media=None)

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.PUBLISHED


@pytest.mark.django_db
def test_safe_fetch_url_ssrf_and_dns_pinning():
    from socialmedia.utils import safe_fetch_url

    with pytest.raises(PublishingError, match="forbidden local address"):
        safe_fetch_url("http://127.0.0.1/test.png")

    with pytest.raises(PublishingError, match="forbidden local address"):
        safe_fetch_url("http://localhost/test.png")

    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
        with pytest.raises(PublishingError, match="resolved to forbidden IP"):
            safe_fetch_url("http://private-domain.local/image.png")


@pytest.mark.django_db
def test_publish_scheduled_posts_skips_legacy_scheduler_providers(
    organizer, event, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    account = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="test_channel",
        is_active=True,
    )
    account.credentials = {"bot_token": "fake_token"}
    account.save()

    with scope(organizer=organizer, event=event):
        post_postiz = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_1_postiz",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Postiz scheduled post",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )
        post_buffer = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_2_buffer",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Buffer scheduled post",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch.object(TelegramProvider, "publish_post") as mock_publish:
        publish_scheduled_posts(sender=None)
        mock_publish.assert_not_called()

    with scope(organizer=organizer, event=event):
        post_postiz.refresh_from_db()
        post_buffer.refresh_from_db()
        assert post_postiz.status == SocialMediaPostStatus.SCHEDULED
        assert post_buffer.status == SocialMediaPostStatus.SCHEDULED


@pytest.mark.django_db
def test_publish_generic_post_multiple_providers(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Two different providers
    acc_tg = SocialMediaAccount.objects.create(
        organizer=organizer, provider="telegram", platform_username="t1", is_active=True
    )
    acc_tg.credentials = {"bot_token": "token"}
    acc_tg.save()

    acc_mast = SocialMediaAccount.objects.create(
        organizer=organizer, provider="mastodon", platform_username="m1", is_active=True
    )
    acc_mast.credentials = {
        "client_id": "c",
        "client_secret": "s",
        "access_token": "a",
        "api_base_url": "url",
    }
    acc_mast.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp",  # Realistic generic ID
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Generic post text",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with (
        patch.object(TelegramProvider, "publish_post") as mock_tg,
        patch.object(MastodonProvider, "publish_post") as mock_mast,
    ):
        publish_scheduled_posts(sender=None)
        mock_tg.assert_called_once()
        mock_mast.assert_called_once()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.PUBLISHED


@pytest.mark.django_db
def test_publish_generic_post_duplicate_accounts(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    acc_tg1 = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="tg1",
        is_active=True,
    )
    acc_tg1.credentials = {"bot_token": "t1"}
    acc_tg1.save()

    acc_tg2 = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="tg2",
        is_active=True,
    )
    acc_tg2.credentials = {"bot_token": "t2"}
    acc_tg2.save()

    acc_tg3_inactive = SocialMediaAccount.objects.create(
        organizer=organizer,
        provider="telegram",
        platform_username="tg3",
        is_active=False,
    )
    acc_tg3_inactive.credentials = {"bot_token": "t3"}
    acc_tg3_inactive.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="schedule",
            entity_id="schedule",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Multiple accounts test",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch.object(TelegramProvider, "publish_post") as mock_tg:
        publish_scheduled_posts(sender=None)
        assert mock_tg.call_count == 2

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.PUBLISHED


@pytest.mark.django_db
def test_publish_generic_post_partial_failure(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    acc_tg = SocialMediaAccount.objects.create(
        organizer=organizer, provider="telegram", platform_username="t1", is_active=True
    )
    acc_tg.credentials = {"bot_token": "token"}
    acc_tg.save()

    acc_mast = SocialMediaAccount.objects.create(
        organizer=organizer, provider="mastodon", platform_username="m1", is_active=True
    )
    acc_mast.credentials = {
        "client_id": "c",
        "client_secret": "s",
        "access_token": "a",
        "api_base_url": "url",
    }
    acc_mast.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="ticket",
            entity_id="ticket_123",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Partial failure text",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with (
        patch.object(TelegramProvider, "publish_post") as mock_tg,
        patch.object(
            MastodonProvider, "publish_post", side_effect=Exception("Network timeout")
        ) as mock_mast,
    ):
        publish_scheduled_posts(sender=None)
        mock_tg.assert_called_once()
        mock_mast.assert_called_once()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.FAILED
        assert "Published to (telegram)" in post.error_message
        assert "mastodon: Network timeout" in post.error_message


@pytest.mark.django_db
def test_publish_generic_post_all_failure(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    acc_tg = SocialMediaAccount.objects.create(
        organizer=organizer, provider="telegram", platform_username="t1", is_active=True
    )
    acc_tg.credentials = {"bot_token": "token"}
    acc_tg.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="speaker",
            entity_id="speaker_1_2",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="All fail text",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch.object(
        TelegramProvider, "publish_post", side_effect=Exception("Auth error")
    ) as mock_tg:
        publish_scheduled_posts(sender=None)
        mock_tg.assert_called_once()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.FAILED
        assert "telegram: Auth error" in post.error_message


@pytest.mark.django_db
def test_publish_generic_post_zero_accounts(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    # Zero accounts setup
    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="session",
            entity_id="session_1",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="No accounts",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch("socialmedia.signals.publish_generic_post") as mock_task:
        publish_scheduled_posts(sender=None)
        mock_task.assert_not_called()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.SCHEDULED


@pytest.mark.django_db
def test_publish_generic_post_duplicate_execution(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    acc_tg = SocialMediaAccount.objects.create(
        organizer=organizer, provider="telegram", platform_username="t1", is_active=True
    )
    acc_tg.credentials = {"bot_token": "token"}
    acc_tg.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp",
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Dup test",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    from socialmedia.tasks import publish_generic_post

    with patch.object(TelegramProvider, "publish_post") as mock_tg:
        publish_generic_post(post.pk)
        assert mock_tg.call_count == 1

        # Second execution should do nothing
        publish_generic_post(post.pk)
        assert mock_tg.call_count == 1


@pytest.mark.django_db
def test_publish_unsupported_suffix_skipped(organizer, event, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    acc_tg = SocialMediaAccount.objects.create(
        organizer=organizer, provider="telegram", platform_username="t1", is_active=True
    )
    acc_tg.credentials = {"bot_token": "token"}
    acc_tg.save()

    with scope(organizer=organizer, event=event):
        post = SocialMediaPost.objects.create(
            event=event,
            post_type="cfp",
            entity_id="cfp_bluesky",  # Unsupported suffix
            scheduled_at=now() - timedelta(minutes=5),
            post_text="Unsupported suffix test",
            status=SocialMediaPostStatus.SCHEDULED,
            is_pinned=True,
        )

    with patch("socialmedia.signals.publish_generic_post") as mock_task, \
         patch("socialmedia.signals.publish_single_post") as mock_single:
        publish_scheduled_posts(sender=None)
        mock_task.assert_not_called()
        mock_single.assert_not_called()

    with scope(organizer=organizer, event=event):
        post.refresh_from_db()
        assert post.status == SocialMediaPostStatus.SCHEDULED
