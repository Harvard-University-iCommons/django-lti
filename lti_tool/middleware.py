from logging import getLogger

from django.contrib.auth import authenticate, get_user_model, login

from pylti1p3.exception import LtiException

from .constants import SESSION_KEY
from .models import AbsentLtiLaunch
from .utils import get_launch_from_request

logger = getLogger(__name__)

UserModel = get_user_model()


class LtiLaunchMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        launch_id = request.session.get(SESSION_KEY)
        try:
            request.lti_launch = get_launch_from_request(request, launch_id)
            logger.info(f"launch user: {request.lti_launch.user}")

            # request.lti_launch = lti_launch
            # lti_user = request.lti_launch.user
            # # authenticate the user here?
            user: UserModel = authenticate(
                request=request, lti_launch=request.lti_launch
            )
            logger.info(f"authenticated user {user} {user.username}")
            login(request, user)
            logger.info(f"login user {user} {user.username}")
            request.lti_launch.user.auth_user = user
            request.lti_launch.user.save()

        except LtiException:
            request.lti_launch = AbsentLtiLaunch()

        return self.get_response(request)
