from flask import request
from celery import chain

from app.service.user_service import get_user_by_public_url, get_user_by_public_id, normalize_new_user_data, save_user
from app.tasks import search_and_store_results, scrape_search_result_profiles
from .errors import error_response, success_response
from app.utils.token_util import encode_auth_token
from app.utils.scrape_util import normalize_url
from .token import token_auth
from app.extensions import db
from app.api import bp


@bp.route('/api/v1/linkedin/signup', methods=['POST'])
def signup_with_linkedin():
    request_data = request.get_json()
    if not request_data or not "name" in request_data or not "email" in request_data or not "headline" in request_data or not "skills" in request_data or not "image" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if user:
            return error_response(409, 'User already exists. Please Log in.')

        new_user = normalize_new_user_data(request_data)
        user_public_id = save_user(new_user, True)
        db.session.commit()

        task = chain(
            search_and_store_results.s(user_public_id),
            scrape_search_result_profiles.s()
        ).apply_async(countdown=5)  # ToDo: save to a particular queue

        current_user = get_user_by_public_id(user_public_id)
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


@bp.route('/api/v1/linkedin/signin', methods=['POST'])
def signin_with_linkedin():
    """ LinkedIn Signin """
    request_data = request.get_json()
    if not request_data or not "email" in request_data:
        return error_response(400, 'Invalid data supplied')

    try:
        user = get_user_by_public_url(request_data["email"])
        if not user:
            return error_response(401, 'Failed to sign in with LinkedIn')

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


@bp.route('/api/v1/search', methods=['GET'])
@token_auth.login_required
def search():
    try:
        current_user = token_auth.current_user()

        task = search_and_store_results.apply_async(
            args=[current_user.public_id], countdown=20)  # ToDo: save to a particular queue

        return success_response(201,
                                message='Matching Task {0} {1} for {2}'.format(task.id, task.state, current_user.url))
    except Exception as e:
        return error_response(500, 'Something went wrong!')


@bp.route('/api/v1/scrape_user_search_results', methods=['GET'])
@token_auth.login_required
def scrape_user_search_results():
    try:
        current_user = token_auth.current_user()

        task = scrape_search_result_profiles.apply_async(
            args=[current_user.public_id], countdown=20)

        return success_response(201,
                                message='Retrieving Task {0} {1} for {2}'.format(task.id, task.state, current_user.url))
    except Exception as e:
        return error_response(500, 'Something went wrong!')
