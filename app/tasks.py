from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError

from .service.user_service import save_user, get_user_by_public_id, get_top_skills_keyword_text, save_search_result, get_user_by_public_url
from .service.linkedin_service import scrape_user, scrape_search_results
from app.utils.scrape_util import normalize_url
from .models import UserRecommendation
from app.utils.fs import log_to_file
from app.main import ProfileScraper
from app.extensions import db
from app import celery

celery_logger = get_task_logger(__name__)


@celery.task(bind=True, max_retries=3)
def scrape_search_result_profiles(self, current_user_public_id):
    """
    Task #3
    Scrapes search result profiles(tied with a user)
    """
    if not current_user_public_id:
        return

    celery_logger.warning('Executing retrieving task for user {0.args!r}'.format(
        self.request))
    SCRAPE_USERS_IN_SINGLE_RUN_LIMIT = 50

    user = get_user_by_public_id(current_user_public_id)
    if not user:
        return

    user_recommendation_search_results = user.get_all_search_results()

    try:
        with ProfileScraper() as scraper:
            # Iterate and scrape each user
            scrape_count = 0
            for result in user_recommendation_search_results:
                if (scrape_count >= SCRAPE_USERS_IN_SINGLE_RUN_LIMIT):
                    break

                search_result = result.search_result
                search_result_url = normalize_url(search_result.url)
                user_exist = False
                if search_result.scraped:
                    user_exist = True

                celery_logger.info('scraping {0}'.format(
                    search_result_url))

                try:
                    if not user_exist:
                        # Visit user with vanity url & scrape user
                        profile = scraper.scrape(
                            user=search_result_url)
                        if not profile:
                            continue
                        scraped = profile.to_dict()

                        if scraped and "personal_info" in scraped:
                            personal_info = scraped["personal_info"]
                            if not "url" in personal_info:
                                continue

                            log_to_file(scraped)
                            # save new user to DB
                            save_user(scraped)

                            # Update `scraped` flag in `search_result_person`
                            search_result.set_scraped()

                    """
                    get user from db and recommend the user
                    """
                    recommended_user = get_user_by_public_url(
                        search_result_url)

                    if not recommended_user:
                        continue

                    # ToDo: skip if already recommended
                    recommendation = UserRecommendation()
                    data = {
                        'recommended_for_id': user.id,
                        'recommended_for': user,
                        'recommended_id': recommended_user.id,
                        'recommended': recommended_user,
                    }
                    recommendation.from_dict(data)
                    db.session.add(recommendation)
                    db.session.commit()
                    scrape_count += 1
                except SQLAlchemyError as e:
                    db.session.rollback()
                    celery_logger.error(e)
                    continue
                except Exception as e:
                    celery_logger.error(e)
                    # 'Something went wrong while scraping user'
                    continue
                    # self.retry(countdown=20)

    except:
        celery_logger.error('Something went wrong')
        return


@celery.task(bind=True, max_retries=3)
def search_and_store_results(self, user_public_id):
    """
    Task #2
    Scrape, save & associate search results to original user
    Returns `user_public_id` if successful
    """
    if not user_public_id:
        celery_logger.error('Invalid user id')
        return

    user = get_user_by_public_id(user_public_id)
    if not user:
        celery_logger.error('No such user')
        return

    celery_logger.warning('Executing matching task for user {0.args!r}'.format(
        self.request))

    top_skills = get_top_skills_keyword_text(user_public_id)
    if len(top_skills) > 0:
        try:
            scraped = scrape_search_results(top_skills)

            if scraped and "urls" in scraped and "vanity_urls" in scraped["urls"]:
                scraped_urls = scraped["urls"]["vanity_urls"]

                try:
                    for _url in scraped_urls:
                        try:
                            save_search_result(normalize_url(_url), user)
                        except SQLAlchemyError as e:
                            db.session.rollback()
                            celery_logger.error(e)
                            continue
                        except Exception as e:
                            celery_logger.error(e)
                            continue

                    return user_public_id
                except Exception as e:
                    celery_logger.error(e)
                    self.retry(countdown=20)

            return None
        except:
            celery_logger.error('Something went wrong')
            return
    else:
        celery_logger.error('Could\'t find user skills to search for.')

    return


@celery.task(bind=True, max_retries=3)
def scrape_and_store_user(self, url):
    """
    Task #1
    Scrape and save user from url
    Returns `user_public_id` if successful
    """
    # log to console
    celery_logger.warning('Executing registration task for {0.args!r}'.format(
        self.request))

    scraped = scrape_user(url)
    if scraped:
        try:
            user_public_id = save_user(scraped, True)
            return user_public_id
        except SQLAlchemyError as e:
            db.session.rollback()
            celery_logger.error(e)
        except Exception as e:
            celery_logger.error(e)
            self.retry(countdown=20)
