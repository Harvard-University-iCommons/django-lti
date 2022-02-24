from typing import Optional

from django.http.request import HttpRequest

from pylti1p3.contrib.django.launch_data_storage.cache import DjangoCacheDataStorage
from pylti1p3.contrib.django.message_launch import DjangoMessageLaunch
from pylti1p3.deployment import Deployment
from pylti1p3.registration import Registration
from pylti1p3.tool_config.abstract import ToolConfAbstract

from .models import (
    Key,
    LtiContext,
    LtiDeployment,
    LtiLaunch,
    LtiMembership,
    LtiPlatformInstance,
    LtiRegistration,
    LtiResourceLink,
    LtiUser,
)


def _prepare_registraion(lti_registration):
    reg = Registration()
    reg.set_auth_login_url(lti_registration.auth_url)
    reg.set_auth_token_url(lti_registration.token_url)
    # reg.set_auth_audience(auth_audience)
    reg.set_client_id(lti_registration.client_id)
    # reg.set_key_set(key_set)
    reg.set_key_set_url(lti_registration.keyset_url)
    reg.set_issuer(lti_registration.issuer)
    if lti_registration.has_key:
        reg.set_tool_public_key(lti_registration.public_key)
        reg.set_tool_private_key(lti_registration.private_key)
    else:
        key = Key.objects.active().latest()
        reg.set_tool_private_key(key.private_key)
        reg.set_tool_public_key(key.public_key)
    return reg


def _prepare_deployment(lti_deployment):
    return Deployment().set_deployment_id(lti_deployment.deployment_id)


class DjangoToolConfig(ToolConfAbstract):
    """LTI tool configuration class.

    A registration UUID may be specified on init to address situations
    where client_id isn't included in OIDC initiation params.
    """

    registration_uuid = None
    registration = None
    deployment = None

    def __init__(self, registration_uuid=None):
        super().__init__()
        self.registration_uuid = registration_uuid

    def check_iss_has_one_client(self, iss):
        return False

    def check_iss_has_many_clients(self, iss):
        return True

    def find_registration_by_issuer(self, iss, *args, **kwargs):
        try:
            self.registration = LtiRegistration.objects.active().get(
                uuid=self.registration_uuid, issuer=iss
            )
            return _prepare_registraion(self.registration)
        except LtiRegistration.DoesNotExist:
            return None

    def find_registration_by_params(self, iss, client_id, *args, **kwargs):
        lookups = {"issuer": iss, "client_id": client_id}
        if self.registration_uuid is not None:
            lookups.update(uuid=self.registration_uuid)
        try:
            self.registration = LtiRegistration.objects.active().get(**lookups)
            return _prepare_registraion(self.registration)
        except LtiRegistration.DoesNotExist:
            return None

    def find_deployment(self, iss, deployment_id):
        try:
            self.deployment = LtiDeployment.objects.active().get(
                registration__uuid=self.registration_uuid,
                registration__issuer=iss,
                registration__is_active=True,
                deployment_id=deployment_id,
            )
            return _prepare_deployment(self.deployment)
        except LtiDeployment.DoesNotExist:
            return None

    def find_deployment_by_params(self, iss, deployment_id, client_id, *args, **kwargs):
        lookups = {
            "registration__issuer": iss,
            "registration__client_id": client_id,
            "registration__is_active": True,
            "deployment_id": deployment_id,
        }
        if self.registration_uuid is not None:
            lookups.update(registration__uuid=self.registration_uuid)
        try:
            self.deployment = LtiDeployment.objects.active().get(**lookups)
            return _prepare_deployment(self.deployment)
        except LtiDeployment.DoesNotExist:
            return None


def get_launch_from_request(
    request: HttpRequest, launch_id: Optional[str] = None
) -> LtiLaunch:
    """
    Returns the DjangoMessageLaunch associated with a request.

    Optionally, a launch_id may be specified to retrieve the launch from the cache.
    """

    tool_conf = DjangoToolConfig()
    launch_data_storage = DjangoCacheDataStorage()
    if launch_id is not None:
        message_launch = DjangoMessageLaunch.from_cache(
            launch_id, request, tool_conf, launch_data_storage=launch_data_storage
        )
    else:
        message_launch = DjangoMessageLaunch(
            request, tool_conf, launch_data_storage=launch_data_storage
        )
        message_launch.validate()
    return LtiLaunch(message_launch)


def sync_user_from_launch(lti_launch: LtiLaunch) -> LtiUser:
    sub = lti_launch.get_claim("sub")
    user_claims = {
        "given_name": lti_launch.get_claim("given_name"),
        "family_name": lti_launch.get_claim("family_name"),
        "name": lti_launch.get_claim("name"),
        "email": lti_launch.get_claim("email"),
        "picture_url": lti_launch.get_claim("picture"),
    }
    lti_user, _created = LtiUser.objects.update_or_create(
        registration=lti_launch.registration,
        sub=sub,
        defaults={k: v for k, v in user_claims.items() if v is not None},
    )
    return lti_user


def sync_context_from_launch(lti_launch: LtiLaunch) -> LtiContext:
    context_claim = lti_launch.context_claim
    context_types = [] if context_claim is None else context_claim.get("type", [])
    if context_claim is None:
        context, _created = LtiContext.objects.get_or_create(
            deployment=lti_launch.deployment, id_on_platform=""
        )
    else:
        defaults = {
            "title": context_claim.get("title", ""),
            "label": context_claim.get("label", ""),
            "is_course_template": (
                "http://purl.imsglobal.org/vocab/lis/v2/course#CourseTemplate"
                in context_types
            ),
            "is_course_offering": (
                "http://purl.imsglobal.org/vocab/lis/v2/course#CourseOffering"
                in context_types
            ),
            "is_course_section": (
                "http://purl.imsglobal.org/vocab/lis/v2/course#CourseSection"
                in context_types
            ),
            "is_group": (
                "http://purl.imsglobal.org/vocab/lis/v2/course#Group" in context_types
            ),
        }
        context, _created = LtiContext.objects.update_or_create(
            deployment=lti_launch.deployment,
            id_on_platform=context_claim["id"],
            defaults=defaults,
        )
    return context


def sync_membership_from_launch(
    lti_launch: LtiLaunch, user: LtiUser, context: LtiContext
) -> LtiMembership:
    roles = lti_launch.roles_claim
    defaults = {}
    if "http://purl.imsglobal.org/vocab/lis/v2/membership#Administrator" in roles:
        defaults["is_administrator"] = True
    if "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper" in roles:
        defaults["is_content_developer"] = True
    if "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor" in roles:
        defaults["is_instructor"] = True
    if "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner" in roles:
        defaults["is_learner"] = True
    if "http://purl.imsglobal.org/vocab/lis/v2/membership#Mentor" in roles:
        defaults["is_mentor"] = True
    membership, _created = LtiMembership.objects.update_or_create(
        user=user, context=context, defaults=defaults
    )
    return membership


def sync_resource_link_from_launch(
    lti_launch: LtiLaunch, context: LtiContext
) -> LtiResourceLink:
    resource_link_claim = lti_launch.resource_link_claim
    resource_link, _created = LtiResourceLink.objects.update_or_create(
        context=context,
        id_on_platform=resource_link_claim["id"],
        defaults={
            "title": resource_link_claim.get("title", ""),
            "description": resource_link_claim.get("description", ""),
        },
    )
    return resource_link


def sync_platform_instance_from_launch(
    lti_launch: LtiLaunch,
) -> Optional[LtiPlatformInstance]:
    platform_instance_claim = lti_launch.platform_instance_claim
    if platform_instance_claim is None:
        return None
    platform_instance, _created = LtiPlatformInstance.objects.update_or_create(
        issuer=lti_launch.get_claim("iss"),
        guid=platform_instance_claim["guid"],
        defaults={
            "contact_email": platform_instance_claim.get("contact_email", ""),
            "description": platform_instance_claim.get("description", ""),
            "name": platform_instance_claim.get("name", ""),
            "url": platform_instance_claim.get("url", ""),
            "product_family_code": platform_instance_claim.get(
                "product_family_code", ""
            ),
            "version": platform_instance_claim.get("version", ""),
        },
    )
    deployment = lti_launch.deployment
    deployment.platform_instance = platform_instance
    deployment.save(update_fields=["platform_instance"])
    return platform_instance


def sync_data_from_launch(lti_launch: LtiLaunch) -> None:
    user = sync_user_from_launch(lti_launch)
    if not lti_launch.is_data_privacy_launch:
        context = sync_context_from_launch(lti_launch)
        sync_membership_from_launch(lti_launch, user, context)
        if not lti_launch.is_deep_link_launch:
            sync_resource_link_from_launch(lti_launch, context)
    sync_platform_instance_from_launch(lti_launch)
