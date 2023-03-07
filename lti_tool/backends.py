from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import LtiLaunch
from django.http import HttpRequest
from logging import getLogger


logger = getLogger(__name__)

UserModel = get_user_model()


class LtiLaunchAuthenticationBackend(BaseBackend):
    def authenticate(self, request: HttpRequest, lti_launch: LtiLaunch = None):
        logger.debug(f"inside authenticate()")
        if lti_launch.user.auth_user and lti_launch.user.auth_user.is_authenticated:
            logger.debug(
                "user is already authenticated: {{ lti_launch.user.auth_user.username }}"
            )
            return lti_launch.user.auth_user
        else:
            username = lti_launch.user.sub
            auth_user, _created = UserModel._default_manager.get_or_create(
                **{
                    UserModel.USERNAME_FIELD: username,
                }
            )
            logger.debug(f"created {{ _created }}/updated auth user {{ auth_user }}")

            # auth_user.lti_user = lti_launch.user
            lti_launch.user.auth_user = auth_user
            lti_launch.user.save()
            return auth_user
