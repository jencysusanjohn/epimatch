from app.extensions import db
from ..models import Post, UserMatch


def save_post(post_data, user):
    post = Post()
    post.from_dict(post_data)
    db.session.add(post)
    user.add_post(post)
    db.session.commit()

    return post.public_id


def get_posts(posts):
    return list(map(lambda x: x.to_dict(), posts))


def get_user_timeline_posts(current_user):
    friends_ids = current_user.get_friends_ids(current_user.friends)
    friends_posts = Post.query\
        .join(UserMatch, (UserMatch.user_id == Post.user_id))\
        .filter(UserMatch.user_id.in_(friends_ids))
    own_posts = Post.query.filter_by(user_id=current_user.id)

    return friends_posts.union(own_posts).order_by(Post.created_at.desc())
