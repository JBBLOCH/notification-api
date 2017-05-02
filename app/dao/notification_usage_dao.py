from datetime import datetime

from sqlalchemy import Float, Integer
from sqlalchemy import func, case, cast
from sqlalchemy import literal_column

from app import db
from app.dao.date_util import get_financial_year
from app.models import (NotificationHistory,
                        Rate,
                        NOTIFICATION_STATUS_TYPES_BILLABLE,
                        KEY_TYPE_TEST,
                        SMS_TYPE,
                        EMAIL_TYPE)
from app.statsd_decorators import statsd
from app.utils import get_london_month_from_utc_column


@statsd(namespace="dao")
def get_yearly_billing_data(service_id, year):
    start_date, end_date = get_financial_year(year)
    rates = get_rates_for_year(start_date, end_date, SMS_TYPE)

    result = []
    for r, n in zip(rates, rates[1:]):
        result.append(
            sms_yearly_billing_data_query(r.rate, service_id, r.valid_from, n.valid_from))

    result.append(sms_yearly_billing_data_query(rates[-1].rate, service_id, rates[-1].valid_from, end_date))

    result.append(email_yearly_billing_data_query(service_id, start_date, end_date))

    return sum(result, [])


@statsd(namespace="dao")
def get_monthly_billing_data(service_id, year):
    start_date, end_date = get_financial_year(year)
    rates = get_rates_for_year(start_date, end_date, SMS_TYPE)

    result = []
    for r, n in zip(rates, rates[1:]):
        result.extend(sms_billing_data_per_month_query(r.rate, service_id, r.valid_from, n.valid_from))
    result.extend(sms_billing_data_per_month_query(rates[-1].rate, service_id, rates[-1].valid_from, end_date))

    return [(datetime.strftime(x[0], "%B"), x[1], x[2], x[3], x[4], x[5]) for x in result]


def billing_data_filter(notification_type, start_date, end_date, service_id):
    return [
        NotificationHistory.notification_type == notification_type,
        NotificationHistory.created_at.between(start_date, end_date),
        NotificationHistory.service_id == service_id,
        NotificationHistory.status.in_(NOTIFICATION_STATUS_TYPES_BILLABLE),
        NotificationHistory.key_type != KEY_TYPE_TEST
    ]


def email_yearly_billing_data_query(service_id, start_date, end_date, rate=0):
    result = db.session.query(
        func.count(NotificationHistory.id),
        func.count(NotificationHistory.id),
        rate_multiplier(),
        NotificationHistory.notification_type,
        NotificationHistory.international,
        cast(rate, Integer())
    ).filter(
        *billing_data_filter(EMAIL_TYPE, start_date, end_date, service_id)
    ).group_by(
        NotificationHistory.notification_type,
        rate_multiplier(),
        NotificationHistory.international
    ).first()
    if not result:
        return [(0, 0, 1, EMAIL_TYPE, False, 0)]
    else:
        return [result]


def sms_yearly_billing_data_query(rate, service_id, start_date, end_date):
    result = db.session.query(
        cast(func.sum(NotificationHistory.billable_units * rate_multiplier()), Integer()),
        func.sum(NotificationHistory.billable_units),
        rate_multiplier(),
        NotificationHistory.notification_type,
        NotificationHistory.international,
        cast(rate, Float())
    ).filter(
        *billing_data_filter(SMS_TYPE, start_date, end_date, service_id)
    ).group_by(
        NotificationHistory.notification_type,
        NotificationHistory.international,
        rate_multiplier()
    ).order_by(
        rate_multiplier()
    ).all()

    if not result:
        return [(0, 0, 1, SMS_TYPE, False, rate)]
    else:
        return result


def get_rates_for_year(start_date, end_date, notification_type):
    rates = Rate.query.filter(Rate.notification_type == notification_type).order_by(Rate.valid_from).all()
    results = []
    for current_rate, current_rate_expiry_date in zip(rates, rates[1:]):
        if is_between(current_rate.valid_from, start_date, end_date) or \
                is_between(current_rate_expiry_date.valid_from, start_date, end_date):
            results.append(current_rate)

    if is_between(rates[-1].valid_from, start_date, end_date):
        results.append(rates[-1])

    if not results:
        if start_date >= rates[-1].valid_from:
            results.append(rates[-1])

    return results


def is_between(date, start_date, end_date):
    return start_date <= date <= end_date


def sms_billing_data_per_month_query(rate, service_id, start_date, end_date):
    month = get_london_month_from_utc_column(NotificationHistory.created_at)
    result = db.session.query(
        month,
        func.sum(NotificationHistory.billable_units),
        rate_multiplier(),
        NotificationHistory.international,
        NotificationHistory.notification_type,
        cast(rate, Float())
    ).filter(
        *billing_data_filter(SMS_TYPE, start_date, end_date, service_id)
    ).group_by(
        NotificationHistory.notification_type,
        month,
        NotificationHistory.rate_multiplier,
        NotificationHistory.international
    ).order_by(
        month,
        rate_multiplier()
    ).all()

    return result


def rate_multiplier():
    return cast(case([
        (NotificationHistory.rate_multiplier == None, literal_column("'1'")),  # noqa
        (NotificationHistory.rate_multiplier != None, NotificationHistory.rate_multiplier),  # noqa
    ]), Integer())