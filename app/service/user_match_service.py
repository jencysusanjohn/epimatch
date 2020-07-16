from ..models import UserFriendshipRequest, UserMatch, UserFriendship, UserRecommendation
from app.extensions import db


def add_friendship(user1, user2):
    """ Create a User -> UserMatch relation and then append it to UserRelationship """
    pl = UserFriendship()
    pl.parties.append(UserMatch(user=user1))
    pl.parties.append(UserMatch(user=user2))

    return pl


def add_friend_request(current_user, other_user, status_text):
    """ Create a friendship request """
    if current_user.public_id == other_user.public_id:
        # Users cannot be friends with themselves
        return None

    if current_user.are_friends(other_user):
        # Users are already friends
        return None

    if not current_user.can_send_request(other_user):
        # Request already sent
        return None

    """
    Request status can be `pending`, `rejected` or `ignored`
    -> `pending` if user clicks status `1`
    -> `rejected` if user sends status `0`
    if existing request is `pending` and user sends `1` => Friendship formed
    if existing request is `pending` and user sends `0` => Add to ignored lists(set `ignored`)
    if existing request is `rejected` and user sends `1` or `0` => Nothing changes(No friendship)
    If no request exist, and user sends `1` => Create new request with `pending` status
    If no request exist, and user sends `0` => Create new request with `rejected` status
    """

    if current_user.has_received_in_request_already(other_user):
        all_received_requests = current_user.received_requests
        existing_request = [
            request for request in all_received_requests if request.from_user_id == other_user.id][0]
        # If existing is pending and new user wan't to meet,
        # add friends with new user and delete request
        if existing_request.status == 'pending':
            # if current user sent status 0
            if status_text == "rejected":
                # Update request status to `ignored`
                existing_request.ignore_request()
                db.session.commit()
                return False

            # add new friendship between users
            add_friendship(current_user, other_user)
            # delete request
            db.session.delete(existing_request)
            db.session.commit()
            return True

        if existing_request.status == 'rejected':
            existing_request.ignore_request()
            db.session.commit()
            return False

        # if request is not `pending` or `rejected`, it is probably `ignored`
        return False

    # send a new request
    new_friendship_request = UserFriendshipRequest()
    data = {
        'to_user_id': other_user.public_id,
        'to_user': other_user,
        'from_user_id': current_user.public_id,
        'from_user': current_user,
        'status': status_text
    }
    new_friendship_request.from_dict(data)
    db.session.add(new_friendship_request)
    db.session.commit()

    return False


def get_friends(friends):
    def get_friend(self_friend_obj):
        other_user_friend = self_friend_obj.other_party()
        other_user = other_user_friend.user

        return other_user.to_dict()

    return list(map(get_friend, friends))


def get_all_user_recommendations(current_user):
    """
    Returns list of recommended users
    Includes users with status `pending` or `rejected`

    Should not include if request already sent
    Should not include if already friends
    Should not include if incoming request is rejected(status: `ignored`) or received rejected request
    """
    all_recommendations_ids = list(
        map(lambda x: x.recommended_id, current_user.recommended_list))
    friends_ids = current_user.get_friends_ids(current_user.friends)
    sent_request_users_ids = current_user.get_sent_requests_users_ids(
        current_user.sent_requests)
    ignored_received_requests = current_user.get_ignored_received_requests_users_ids(
        current_user.received_requests)

    # in (all_recommendations_ids - (all_recommendations_ids intersection (friends_ids union sent_request_users_ids)))
    remaining_recommendations_ids = list(
        set(all_recommendations_ids) - (set(friends_ids + sent_request_users_ids + ignored_received_requests)))

    recommendations = UserRecommendation.query\
        .filter(UserRecommendation.recommended_id.in_(remaining_recommendations_ids))\
        .order_by(UserRecommendation.created_at)

    return recommendations
