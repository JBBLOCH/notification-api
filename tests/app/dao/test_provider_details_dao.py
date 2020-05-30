import pytest

from datetime import datetime
from freezegun import freeze_time
from sqlalchemy import asc, desc

from app.models import ProviderDetails, ProviderDetailsHistory, ProviderRates
from app import clients
from app.dao.provider_details_dao import (
    get_alternative_sms_provider,
    get_current_provider,
    get_provider_details_by_identifier,
    get_provider_details_by_notification_type,
    dao_switch_sms_provider_to_provider_with_identifier,
    dao_toggle_sms_provider,
    dao_update_provider_details,
    dao_get_provider_stats,
    dao_get_provider_versions,
    dao_get_sms_provider_with_equal_priority
)
from tests.app.db import (
    create_ft_billing,
    create_service,
    create_template,
)


@pytest.fixture(scope='function')
def setup_provider_details(db_session):
    db_session.query(ProviderRates).delete()
    db_session.query(ProviderDetails).delete()

    prioritised_email_provider = ProviderDetails(**{
        'display_name': 'foo',
        'identifier': 'foo',
        'priority': 10,
        'notification_type': 'email',
        'active': True,
        'supports_international': False,
    })
    db_session.add(prioritised_email_provider)

    deprioritised_email_provider = ProviderDetails(**{
        'display_name': 'foo',
        'identifier': 'foo',
        'priority': 50,
        'notification_type': 'email',
        'active': True,
        'supports_international': False,
    })
    db_session.add(deprioritised_email_provider)

    prioritised_sms_provider = ProviderDetails(**{
        'display_name': 'foo',
        'identifier': 'foo',
        'priority': 10,
        'notification_type': 'sms',
        'active': True,
        'supports_international': False,
    })
    db_session.add(prioritised_sms_provider)

    db_session.commit()

    return [
        prioritised_email_provider,
        deprioritised_email_provider,
        prioritised_sms_provider
    ]


def set_primary_sms_provider(identifier):
    primary_provider = get_provider_details_by_identifier(identifier)
    secondary_provider = get_alternative_sms_provider(identifier)

    primary_provider.priority = 10
    secondary_provider.priority = 20

    dao_update_provider_details(primary_provider)
    dao_update_provider_details(secondary_provider)


def test_can_get_sms_non_international_providers(restore_provider_details):
    sms_providers = get_provider_details_by_notification_type('sms')
    assert len(sms_providers) == 5
    assert all('sms' == prov.notification_type for prov in sms_providers)


def test_can_get_sms_international_providers(restore_provider_details):
    sms_providers = get_provider_details_by_notification_type('sms', True)
    assert len(sms_providers) == 1
    assert all('sms' == prov.notification_type for prov in sms_providers)
    assert all(prov.supports_international for prov in sms_providers)


def test_can_get_sms_providers_in_order_of_priority(restore_provider_details):
    providers = get_provider_details_by_notification_type('sms', False)

    assert providers[0].priority < providers[1].priority


def test_can_get_email_providers_in_order_of_priority(setup_provider_details):
    providers = get_provider_details_by_notification_type('email')
    [prioritised_email_provider, deprioritised_email_provider, _] = setup_provider_details
    assert providers[0].identifier == prioritised_email_provider.identifier
    assert providers[1].identifier == deprioritised_email_provider.identifier


def test_can_get_email_providers(setup_provider_details):
    email_providers = list(filter(lambda provider: provider.notification_type == 'email', setup_provider_details))
    assert len(get_provider_details_by_notification_type('email')) == len(email_providers)
    types = [provider.notification_type for provider in get_provider_details_by_notification_type('email')]
    assert all('email' == notification_type for notification_type in types)


def test_should_not_error_if_any_provider_in_code_not_in_database(restore_provider_details):
    ProviderDetails.query.filter_by(identifier='sns').delete()

    assert clients.get_sms_client('sns')


@freeze_time('2000-01-01T00:00:00')
def test_update_adds_history(restore_provider_details):
    ses = ProviderDetails.query.filter(ProviderDetails.identifier == 'ses').one()
    ses_history = ProviderDetailsHistory.query.filter(ProviderDetailsHistory.id == ses.id).one()

    assert ses.version == 1
    assert ses_history.version == 1
    assert ses.updated_at is None

    ses.active = False

    dao_update_provider_details(ses)

    assert not ses.active
    assert ses.updated_at == datetime(2000, 1, 1, 0, 0, 0)

    ses_history = ProviderDetailsHistory.query.filter(
        ProviderDetailsHistory.id == ses.id
    ).order_by(
        ProviderDetailsHistory.version
    ).all()

    assert ses_history[0].active
    assert ses_history[0].version == 1
    assert ses_history[0].updated_at is None

    assert not ses_history[1].active
    assert ses_history[1].version == 2
    assert ses_history[1].updated_at == datetime(2000, 1, 1, 0, 0, 0)


def test_update_sms_provider_to_inactive_sets_inactive(restore_provider_details):
    set_primary_sms_provider('sns')
    primary_provider = get_current_provider('sms')
    primary_provider.active = False

    dao_update_provider_details(primary_provider)

    assert not primary_provider.active


def test_get_current_sms_provider_returns_correct_provider(restore_provider_details):
    set_primary_sms_provider('sns')

    provider = get_current_provider('sms')

    assert provider.identifier == 'sns'


@pytest.mark.parametrize('provider_identifier', ['mmg', 'sns'])
def test_get_alternative_sms_provider_returns_expected_provider(notify_db, provider_identifier):
    provider = get_alternative_sms_provider(provider_identifier)
    assert provider.identifier != provider


def test_switch_sms_provider_to_current_provider_does_not_switch(
    restore_provider_details,
    current_sms_provider
):
    dao_switch_sms_provider_to_provider_with_identifier(current_sms_provider.identifier)
    new_provider = get_current_provider('sms')

    assert current_sms_provider.id == new_provider.id
    assert current_sms_provider.identifier == new_provider.identifier


def test_switch_sms_provider_to_inactive_provider_does_not_switch(
    restore_provider_details,
    current_sms_provider
):
    alternative_sms_provider = get_alternative_sms_provider(current_sms_provider.identifier)
    alternative_sms_provider.active = False
    dao_update_provider_details(alternative_sms_provider)

    dao_switch_sms_provider_to_provider_with_identifier(alternative_sms_provider.identifier)
    new_provider = get_current_provider('sms')

    assert new_provider.id == current_sms_provider.id
    assert new_provider.identifier == current_sms_provider.identifier


def test_toggle_sms_provider_switches_provider(
    mocker,
    restore_provider_details,
    current_sms_provider,
    sample_user

):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    dao_toggle_sms_provider(current_sms_provider.identifier)
    new_provider = get_current_provider('sms')

    old_starting_provider = get_provider_details_by_identifier(current_sms_provider.identifier)

    assert new_provider.identifier != old_starting_provider.identifier
    assert new_provider.priority < old_starting_provider.priority


def test_toggle_sms_provider_switches_when_provider_priorities_are_equal(
    mocker,
    restore_provider_details,
    sample_user
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    current_provider = get_current_provider('sms')
    new_provider = get_alternative_sms_provider(current_provider.identifier)

    current_provider.priority = new_provider.priority
    dao_update_provider_details(current_provider)

    dao_toggle_sms_provider(current_provider.identifier)

    old_starting_provider = get_provider_details_by_identifier(current_provider.identifier)

    assert new_provider.identifier != old_starting_provider.identifier
    assert new_provider.priority < old_starting_provider.priority


def test_toggle_sms_provider_updates_provider_history(
    mocker,
    restore_provider_details,
    current_sms_provider,
    sample_user
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)
    provider_history_rows = ProviderDetailsHistory.query.filter(
        ProviderDetailsHistory.id == current_sms_provider.id
    ).order_by(
        desc(ProviderDetailsHistory.version)
    ).all()

    dao_toggle_sms_provider(current_sms_provider.identifier)

    updated_provider_history_rows = ProviderDetailsHistory.query.filter(
        ProviderDetailsHistory.id == current_sms_provider.id
    ).order_by(
        desc(ProviderDetailsHistory.version)
    ).all()

    assert len(updated_provider_history_rows) - len(provider_history_rows) == 1
    assert updated_provider_history_rows[0].version - provider_history_rows[0].version == 1


def test_toggle_sms_provider_switches_provider_stores_notify_user_id(
    restore_provider_details,
    sample_user,
    mocker
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)

    current_provider = get_current_provider('sms')
    dao_toggle_sms_provider(current_provider.identifier)
    new_provider = get_current_provider('sms')

    assert current_provider.identifier != new_provider.identifier
    assert new_provider.created_by.id == sample_user.id
    assert new_provider.created_by_id == sample_user.id


def test_toggle_sms_provider_switches_provider_stores_notify_user_id_in_history(
    restore_provider_details,
    sample_user,
    mocker
):
    mocker.patch('app.provider_details.switch_providers.get_user_by_id', return_value=sample_user)

    old_provider = get_current_provider('sms')
    dao_toggle_sms_provider(old_provider.identifier)
    new_provider = get_current_provider('sms')

    old_provider_from_history = ProviderDetailsHistory.query.filter_by(
        identifier=old_provider.identifier,
        version=old_provider.version
    ).order_by(
        asc(ProviderDetailsHistory.priority)
    ).first()
    new_provider_from_history = ProviderDetailsHistory.query.filter_by(
        identifier=new_provider.identifier,
        version=new_provider.version
    ).order_by(
        asc(ProviderDetailsHistory.priority)
    ).first()

    assert old_provider.version == old_provider_from_history.version
    assert new_provider.version == new_provider_from_history.version
    assert new_provider_from_history.created_by_id == sample_user.id
    assert old_provider_from_history.created_by_id == sample_user.id


def test_can_get_all_provider_history(restore_provider_details, current_sms_provider):
    assert len(dao_get_provider_versions(current_sms_provider.id)) == 1


def test_get_sms_provider_with_equal_priority_returns_provider(
    restore_provider_details
):
    current_provider = get_current_provider('sms')
    new_provider = get_alternative_sms_provider(current_provider.identifier)

    current_provider.priority = new_provider.priority
    dao_update_provider_details(current_provider)

    conflicting_provider = \
        dao_get_sms_provider_with_equal_priority(current_provider.identifier, current_provider.priority)

    assert conflicting_provider


def test_get_current_sms_provider_returns_active_only(restore_provider_details):
    current_provider = get_current_provider('sms')
    current_provider.active = False
    dao_update_provider_details(current_provider)
    new_current_provider = get_current_provider('sms')

    assert current_provider.identifier != new_current_provider.identifier


def test_dao_get_provider_stats_returns_data_in_type_and_identifier_order(setup_provider_details):
    all_provider_details = setup_provider_details
    result = dao_get_provider_stats()
    assert len(result) == len(all_provider_details)

    [prioritised_email_provider, deprioritised_email_provider, prioritised_sms_provider] = setup_provider_details

    assert result[0].identifier == prioritised_email_provider.identifier
    assert result[0].display_name == prioritised_email_provider.display_name

    assert result[1].identifier == prioritised_sms_provider.identifier
    assert result[1].display_name == prioritised_sms_provider.display_name

    assert result[2].identifier == deprioritised_email_provider.identifier
    assert result[2].display_name == deprioritised_email_provider.display_name


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_ignores_billable_sms_older_than_1_month(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing('2017-06-05', 'sms', sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 0


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing('2018-06-05', 'sms', sms_template, service, provider=sms_provider.identifier, billable_unit=4)

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 4


@freeze_time('2018-06-28 12:00')
def test_dao_get_provider_stats_counts_billable_sms_within_last_month_with_rate_multiplier(setup_provider_details):
    sms_provider = next((provider for provider in setup_provider_details if provider.notification_type == 'sms'), None)

    service = create_service(service_name='1')
    sms_template = create_template(service, 'sms')

    create_ft_billing(
        '2018-06-05',
        'sms',
        sms_template,
        service,
        provider=sms_provider.identifier,
        billable_unit=4,
        rate_multiplier=2
    )

    results = dao_get_provider_stats()

    sms_provider_result = next((result for result in results if result.identifier == sms_provider.identifier), None)

    assert sms_provider_result.current_month_billable_sms == 8
