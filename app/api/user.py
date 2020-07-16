from cloudinary.uploader import upload
from sqlalchemy.exc import SQLAlchemyError
from flask import request
from celery import chain


from app.service.user_service import save_user, get_user_by_public_url, get_user_by_public_id, get_full_user, get_search_results, normalize_new_user_data, get_all_users
from app.service.user_match_service import add_friend_request, get_friends, get_all_user_recommendations
from app.service.job_offer_service import save_job_offer, get_job_offers, get_user_timeline_job_offers
from app.service.event_service import save_event, get_events, get_user_timeline_events
from app.service.post_service import save_post, get_posts, get_user_timeline_posts
from app.tasks import search_and_store_results, scrape_search_result_profiles
from app.service.email_service import send_password_reset_email
from .errors import success_response, error_response
from app.utils.fs import get_cloudinary_user_folder
from app.utils.token_util import encode_auth_token
from app.utils.scrape_util import normalize_url
from .token import token_auth
from app.extensions import db
from app.api import bp


@bp.route('/api/v1/auth/signup', methods=['POST'])
def user_signup():
    """
    Register a normal user

    There will be no url field,
    so replace it with the email as a workaround(for the primary key)
    """
    request_data = request.get_json()
    if not request_data or not "name" in request_data or not "email" in request_data or not "password" in request_data or not "phone" in request_data or not "headline" in request_data or not "location" in request_data or not "skills" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if user:
            return error_response(409, 'User already exists. Please Log in.')

        new_user = normalize_new_user_data(request_data)
        user_public_id = save_user(new_user, True)
        current_user = get_user_by_public_id(user_public_id)
        current_user.set_password(request_data["password"])
        db.session.commit()

        task = chain(
            search_and_store_results.s(user_public_id),
            scrape_search_result_profiles.s()
        ).apply_async(countdown=5)  # ToDo: save to a particular queue

        auth_token = encode_auth_token(
            current_user.public_id.hex)  # uuid to string
        if not auth_token:
            return error_response(500, 'Something went wrong!')

        return {
            'response': {
                'statusCode': 201,
                'statusText': 'OK'
            },
            'data': {
                'status': True,
                'message': 'Successfully registered.',
                'token': auth_token
            }
        }
    except Exception as e:
        pass

    return error_response(500, 'Failed to signup. Try again later.')


@bp.route('/api/v1/auth/signin', methods=['POST'])
def user_signin():
    """ Regular Signin """
    request_data = request.get_json()
    if not request_data or not "email" in request_data or not "password" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if not user or not user.check_password(request_data["password"]):
            return error_response(401, 'Invalid email or password')

        auth_token = encode_auth_token(user.public_id.hex)  # uuid to string
        if not auth_token:
            return error_response(500, 'Something went wrong!')

        return {
            'response': {
                'statusCode': 200,
                'statusText': 'OK'
            },
            'data': {
                'status': True,
                'message': 'Successfully logged in.',
                'token': auth_token
            }
        }
    except Exception as e:
        pass

    return error_response(500, 'Failed to login. Try again later.')


@bp.route('/api/v1/auth/forgot_password', methods=['POST'])
def forgot_password_request():
    """ Password Reset email """
    request_data = request.get_json()
    if not request_data or not "email" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if not user:
            return error_response(401, 'This email is not associated with any account.')

        token = user.generate_password_reset_otp()
        db.session.commit()
        send_password_reset_email(user, token)

        return success_response(200, 'Check your email for the password reset token.')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Failed to handle password reset. Try again later.')


@bp.route('/api/v1/auth/reset_password', methods=['POST'])
def reset_password_request():
    """ Password Reset """
    request_data = request.get_json()
    if not request_data or not "token" in request_data or not "email" in request_data or not "password" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if not user:
            return error_response(401, 'This email is not associated with any account.')

        if user.check_password_reset_otp(request_data["token"]):
            user.set_password_reset_expires(None)
            user.set_password(request_data["password"])
            db.session.commit()

            return success_response(200, 'Your password has been reset.')

        return error_response(401, 'Expired or invalid token.')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Failed to reset password. Try again later.')


@bp.route('/api/v1/user/upload_profile_picture', methods=['POST'])
@token_auth.login_required
def upload_profile_picture():
    """ Update profile picture of current user """
    file_to_upload = request.files['image']
    if not file_to_upload:
        return error_response(400, 'Missing image file')

    try:
        current_user = token_auth.current_user()
        # upload image to cloudinary service
        upload_result = upload(file_to_upload,
                               folder="{0}/profiles".format(
                                   get_cloudinary_user_folder(current_user.url)),
                               overwrite=False)
        current_user.change_profile_image(upload_result["secure_url"])
        db.session.commit()

        return success_response(201, 'Profile picture updated successfully')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Failed to change profile picture. Try again later.')


@bp.route('/api/v1/get_user', methods=['GET'])
@token_auth.login_required
def get_user():
    """ Get current user """
    try:
        current_user = token_auth.current_user()

        return success_response(200, data=get_full_user(current_user))
    except Exception as e:
        pass

    return error_response(500, 'Something went wrong. Try again later.')


@bp.route('/api/v1/get_users', methods=['GET'])
@token_auth.login_required
def get_users():
    """ Get all users """
    # ToDo: check if admin email with jwt auth
    try:
        result = get_all_users()
        users = list(map(lambda x: x.to_dict(), result))

        return success_response(200,
                                data={
                                    'data': users,
                                    'total': len(users)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Something went wrong. Try again later.')


@bp.route('/api/v1/get_user_search_results', methods=['GET'])
@token_auth.login_required
def get_user_search_results():
    """ List of urls of users from search results """
    try:
        current_user = token_auth.current_user()
        result = get_search_results(current_user.search_results)

        return success_response(200,
                                data={
                                    'data': result,
                                    'total': len(result)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Something went wrong. Try again later.')


@bp.route('/api/v1/get_user_recommendations', methods=['GET'])
@token_auth.login_required
def get_user_recommendations():
    """ Get user recommendations persons """
    # ToDo: filter if person is a friend or already requested to
    try:
        current_user = token_auth.current_user()
        users = list(map(lambda x: get_full_user(x.recommended),
                         get_all_user_recommendations(current_user)))

        return success_response(200,
                                data={
                                    'data': users,
                                    'total': len(users)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Something went wrong. Try again later.')


@bp.route('/api/v1/post/new', methods=['POST'])
@token_auth.login_required
def add_new_post():
    """ Create new post """
    # type is `form-data`
    file_to_upload = request.files['image']
    request_data = request.form

    if not request_data or not "body" in request_data or not file_to_upload:
        return error_response(400, 'Invalid data supplied')

    try:
        current_user = token_auth.current_user()
        # upload image to cloudinary service
        upload_result = upload(file_to_upload,
                               folder="{0}/posts".format(get_cloudinary_user_folder(
                                   current_user.url)),
                               overwrite=False)
        new_post = {'body': request_data["body"],
                    'image': upload_result["secure_url"],
                    'user_id': current_user.id}
        post_id = save_post(new_post, current_user)

        return success_response(201,
                                message='Posted successfully')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Error creating new post!')


@bp.route('/api/v1/user/posts', methods=['GET'])
@token_auth.login_required
def get_user_posts():
    """ Get posts created by the current user """
    try:
        current_user = token_auth.current_user()
        posts = get_posts(current_user.posts)

        return success_response(200,
                                data={
                                    'data': posts,
                                    'total': len(posts)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user posts!')


@bp.route('/api/v1/timeline/posts', methods=['GET'])
@token_auth.login_required
def get_user_timeline_latest_posts():
    """ Get Posts to show on timeline """
    try:
        current_user = token_auth.current_user()
        posts = list(map(lambda x: x.to_dict(),
                         get_user_timeline_posts(current_user)))

        return success_response(200, 'success', data={
            'data': posts,
            'total': len(posts)
        })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user timeline posts!')


@bp.route('/api/v1/event/new', methods=['POST'])
@token_auth.login_required
def add_new_event():
    """ Create a new event """
    request_data = request.get_json()

    if not request_data or not "title" in request_data or not "venue" in request_data or not "location" in request_data or not "description" in request_data or not "start_date" in request_data or not "start_time" in request_data or not "end_date" in request_data or not "end_time" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        current_user = token_auth.current_user()
        new_event = {
            'user_id': current_user.id,
            'title': request_data["title"],
            'venue': request_data["venue"],
            'location': request_data["location"],
            'description': request_data["description"],
            # convert to datetime format
            'starts_at': "{0} {1}".format(request_data["start_date"], request_data["start_time"]),
            # convert to datetime format
            'ends_at': "{0} {1}".format(request_data["end_date"], request_data["end_time"]),
        }
        event_id = save_event(new_event, current_user)

        return success_response(201, message='Event scheduled successfully')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Error creating new event!')


@bp.route('/api/v1/user/events', methods=['GET'])
@token_auth.login_required
def get_user_events():
    """ Get events created by the current user """
    try:
        current_user = token_auth.current_user()
        events = get_events(current_user.events)

        return success_response(200,
                                data={
                                    'data': events,
                                    'total': len(events)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user events!')


@bp.route('/api/v1/timeline/events', methods=['GET'])
@token_auth.login_required
def get_user_timeline_latest_events():
    """ Get events to show on timeline """
    try:
        current_user = token_auth.current_user()
        events = list(map(lambda x: x.to_dict(),
                          get_user_timeline_events(current_user)))

        return success_response(200, 'success', data={
            'data': events,
            'total': len(events)
        })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user timeline events!')


@bp.route('/api/v1/job_offer/new', methods=['POST'])
@token_auth.login_required
def add_new_job_offer():
    """ Create a new job offer """
    request_data = request.get_json()

    if not request_data or not "title" in request_data or not "venue" in request_data or not "location" in request_data or not "description" in request_data or not "contact" in request_data or not "start_date" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        current_user = token_auth.current_user()
        new_job_offer = {
            'user_id': current_user.id,
            'title': request_data["title"],
            'venue': request_data["venue"],
            'location': request_data["location"],
            'description': request_data["description"],
            'contact': request_data["contact"],
            'starts_at': request_data["start_date"],
        }
        job_offer_id = save_job_offer(new_job_offer, current_user)

        return success_response(201, message='Job offer created successfully')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Error creating new job offer!')


@bp.route('/api/v1/user/job_offers', methods=['GET'])
@token_auth.login_required
def get_user_job_offers():
    """ Get User Jobs created by the current user """
    try:
        current_user = token_auth.current_user()
        job_offers = get_job_offers(current_user.job_offers)

        return success_response(200,
                                data={
                                    'data': job_offers,
                                    'total': len(job_offers)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user job offers!')


@bp.route('/api/v1/timeline/job_offers', methods=['GET'])
@token_auth.login_required
def get_user_timeline_latest_job_offers():
    """ Get job_offers to show on timeline """
    try:
        current_user = token_auth.current_user()
        job_offers = list(map(lambda x: x.to_dict(),
                              get_user_timeline_job_offers(current_user)))

        return success_response(200, 'success', data={
            'data': job_offers,
            'total': len(job_offers)
        })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user timeline job offers!')


@bp.route('/api/v1/user/match_request', methods=['POST'])
@token_auth.login_required
def handle_match_request():
    """ Handling Meet / Pass action """
    request_data = request.get_json()

    if not request_data or not "match_user_public_id" in request_data or not "status" in request_data or not (request_data["status"] == 0 or request_data["status"] == 1):
        return error_response(400, 'Invalid data supplied')

    try:
        current_user = token_auth.current_user()
        user_to_match = get_user_by_public_id(
            request_data["match_user_public_id"])

        if not user_to_match:
            return error_response(404, 'No such user to send request to!')

        # if user wants to meet -> `pending` else `rejected`
        status_text = "pending" if request_data["status"] == 1 else "rejected"

        # True if matched, False if pending, None if request is not possible to process
        res = add_friend_request(
            current_user, other_user=user_to_match, status_text=status_text)

        if res is not None:
            if res:
                return success_response(200,
                                        message='Matching successful',
                                        data={
                                            'match': True
                                        })

            return success_response(201,
                                    message='Matching in progress',
                                    data={
                                        'match': False
                                    })

        return error_response(500,
                              message='Request is either pending or already accepted')

    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Error creating new match request!')


@bp.route('/api/v1/user/friends', methods=['GET'])
@token_auth.login_required
def get_user_friends():
    """ Get user's friends """
    try:
        current_user = token_auth.current_user()
        friends = get_friends(current_user.friends)

        return success_response(200,
                                data={
                                    'data': friends,
                                    'total': len(friends)
                                })
    except Exception as e:
        pass

    return error_response(500, 'Error retrieving user friends!')


@bp.route('/api/v1/user/delete', methods=['POST'])
@token_auth.login_required
def delete_user_account():
    """ Create new post """
    try:
        current_user = token_auth.current_user()
        db.session.delete(current_user)
        db.session.commit()

        return success_response(200, message='Account deleted successfully')
    except SQLAlchemyError as e:
        db.session.rollback()
    except Exception as e:
        pass

    return error_response(500, 'Error deleting user account!')
