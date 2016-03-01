import uuid

from app.models import InvitedUser

from app.dao.invited_user_dao import (
    save_invited_user,
    get_invited_user,
    get_invited_users_for_service,
    get_invited_user_by_id
)


def test_create_invited_user(notify_db, notify_db_session, sample_service):
    assert InvitedUser.query.count() == 0
    email_address = 'invited_user@service.gov.uk'
    invite_from = sample_service.users[0]

    data = {
        'service': sample_service,
        'email_address': email_address,
        'from_user': invite_from,
        'permissions': 'send_messages,manage_service'
    }

    invited_user = InvitedUser(**data)
    save_invited_user(invited_user)

    assert InvitedUser.query.count() == 1
    assert invited_user.email_address == email_address
    assert invited_user.from_user == invite_from
    permissions = invited_user.get_permissions()
    assert len(permissions) == 2
    assert 'send_messages' in permissions
    assert 'manage_service' in permissions


def test_get_invited_user_by_service_and_id(notify_db, notify_db_session, sample_invited_user):
    from_db = get_invited_user(sample_invited_user.service.id, sample_invited_user.id)
    assert from_db == sample_invited_user


def test_get_invited_user_by_id(notify_db, notify_db_session, sample_invited_user):
    from_db = get_invited_user_by_id(sample_invited_user.id)
    assert from_db == sample_invited_user


def test_get_unknown_invited_user_returns_none(notify_db, notify_db_session, sample_service):
    unknown_id = uuid.uuid4()

    unknown = get_invited_user(sample_service.id, unknown_id)
    assert unknown is None


def test_get_invited_users_for_service(notify_db, notify_db_session, sample_service):

    from tests.app.conftest import sample_invited_user
    invites = []
    for i in range(0, 5):
        email = 'invited_user_{}@service.gov.uk'.format(i)

        invited_user = sample_invited_user(notify_db,
                                           notify_db_session,
                                           sample_service,
                                           email)
        invites.append(invited_user)

    all_from_db = get_invited_users_for_service(sample_service.id)
    assert len(all_from_db) == 5
    for invite in invites:
        assert invite in all_from_db


def test_get_invited_users_for_service_that_has_no_invites(notify_db, notify_db_session, sample_service):

    invites = get_invited_users_for_service(sample_service.id)
    assert len(invites) == 0


def test_save_invited_user_sets_status_to_cancelled(notify_db, notify_db_session, sample_invited_user):
    assert InvitedUser.query.count() == 1
    saved = InvitedUser.query.get(sample_invited_user.id)
    assert saved.status == 'pending'
    saved.status = 'cancelled'
    save_invited_user(saved)
    assert InvitedUser.query.count() == 1
    cancelled_invited_user = InvitedUser.query.get(sample_invited_user.id)
    assert cancelled_invited_user.status == 'cancelled'
