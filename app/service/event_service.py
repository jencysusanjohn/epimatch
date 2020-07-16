from ..models import Event, UserMatch
from app.extensions import db


def save_event(event_data, user):
    event = Event()
    event.from_dict(event_data)
    db.session.add(event)
    user.add_event(event)
    db.session.commit()

    return event.public_id


def get_events(events):
    return list(map(lambda x: x.to_dict(), events))


def get_user_timeline_events(current_user):
    friends_ids = current_user.get_friends_ids(current_user.friends)
    friends_events = Event.query\
        .join(UserMatch, (UserMatch.user_id == Event.user_id))\
        .filter(UserMatch.user_id.in_(friends_ids))
    own_events = Event.query.filter_by(user_id=current_user.id)

    return friends_events.union(own_events).order_by(Event.created_at.desc())
