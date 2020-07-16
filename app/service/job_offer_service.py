from ..models import JobOffer, UserMatch
from app.extensions import db


def save_job_offer(job_offer_data, user):
    job_offer = JobOffer()
    job_offer.from_dict(job_offer_data)
    db.session.add(job_offer)
    user.add_job_offer(job_offer)
    db.session.commit()

    return job_offer.public_id


def get_job_offers(job_offers):
    return list(map(lambda x: x.to_dict(), job_offers))


def get_user_timeline_job_offers(current_user):
    friends_ids = current_user.get_friends_ids(current_user.friends)
    friends_job_offers = JobOffer.query\
        .join(UserMatch, (UserMatch.user_id == JobOffer.user_id))\
        .filter(UserMatch.user_id.in_(friends_ids))
    own_job_offers = JobOffer.query.filter_by(user_id=current_user.id)

    return friends_job_offers.union(own_job_offers).order_by(JobOffer.created_at.desc())
