import argparse
import getpass
import sys

import glanceclient
from glanceclient import exc
from glanceclient._i18n import _
from glanceclient.common import utils
from keystoneclient import discover, exceptions as ks_exc, session
from keystoneclient.auth.identity import v3 as v3_auth, v2 as v2_auth
import six.moves.urllib.parse as urlparse

SUPPORTED_VERSIONS = [1, 2]


def authenticate_client(source_or_dest, env_name, args):
    os_args = {k[len(source_or_dest) + 1:]: v for k, v in vars(args).items() if
               k.startswith("%s_os_" % source_or_dest)}
    for general_arg in ['insecure', 'timeout']:
        if general_arg in args:
            os_args[general_arg] = getattr(args, general_arg)
    os_args['ssl_compression'] = True
    os_args['source_or_dest'] = source_or_dest
    os_args = argparse.Namespace(**os_args)

    endpoint = None
    url_version = None
    try:
        if os_args.os_image_url:
            endpoint = os_args.os_image_url
        endpoint, url_version = utils.strip_version(endpoint)
    except ValueError:
        pass

    try:
        api_version = int(os_args.os_image_api_version or url_version or 2)
        if api_version not in SUPPORTED_VERSIONS:
            raise ValueError
    except ValueError:
        msg = ("Invalid API version parameter. "
               "Supported values are %s" % SUPPORTED_VERSIONS)
        utils.exit(msg=msg)

    client, client_desc = _get_versioned_client(api_version, os_args)
    return client, client_desc


def _get_versioned_client(api_version, args):
    endpoint = _get_image_url(args)
    auth_token = args.os_auth_token

    description = "glance-v%s" % (api_version)

    ks_session = None
    if endpoint and auth_token:
        kwargs = {
            'token': auth_token,
            'insecure': args.insecure,
            'timeout': args.timeout,
            'cacert': args.os_cacert,
            'cert': args.os_cert,
            'key': args.os_key,
            'ssl_compression': args.ssl_compression
        }
        description += " using auth_token"
    else:
        kwargs = _get_kwargs_for_create_session(args)
        ks_session, ks_desc = _get_keystone_session(**kwargs)
        kwargs = {'session': ks_session}
        description += ks_desc

    if endpoint is None:
        endpoint_type = args.os_endpoint_type or 'public'
        service_type = args.os_service_type or 'image'
        endpoint = ks_session.get_endpoint(
            service_type=service_type,
            interface=endpoint_type,
            region_name=args.os_region_name)

    return glanceclient.Client(api_version, endpoint, **kwargs), description


def _get_image_url(args):
    """Translate the available url-related options into a single string.

    Return the endpoint that should be used to talk to Glance if a
    clear decision can be made. Otherwise, return None.
    """
    if args.os_image_url:
        return args.os_image_url
    else:
        return None


def _discover_auth_versions(session, auth_url):
    # discover the API versions the server is supporting base on the
    # given URL
    v2_auth_url = None
    v3_auth_url = None
    try:
        ks_discover = discover.Discover(session=session, url=auth_url)
        v2_auth_url = ks_discover.url_for('2.0')
        v3_auth_url = ks_discover.url_for('3.0')
    except ks_exc.ClientException as e:
        # Identity service may not support discover API version.
        # Lets trying to figure out the API version from the original URL.
        url_parts = urlparse.urlparse(auth_url)
        (scheme, netloc, path, params, query, fragment) = url_parts
        path = path.lower()
        if path.startswith('/v3'):
            v3_auth_url = auth_url
        elif path.startswith('/v2'):
            v2_auth_url = auth_url
        else:
            # not enough information to determine the auth version
            msg = ('Unable to determine the Keystone version '
                   'to authenticate with using the given '
                   'auth_url. Identity service may not support API '
                   'version discovery. Please provide a versioned '
                   'auth_url instead. error=%s') % (e)
            raise exc.CommandError(msg)

    return (v2_auth_url, v3_auth_url)


def _get_keystone_session(**kwargs):
    ks_session = session.Session.construct(kwargs)
    ks_desc = ""

    # discover the supported keystone versions using the given auth url
    auth_url = kwargs.pop('auth_url', None)
    (v2_auth_url, v3_auth_url) = _discover_auth_versions(
        session=ks_session,
        auth_url=auth_url)

    # Determine which authentication plugin to use. First inspect the
    # auth_url to see the supported version. If both v3 and v2 are
    # supported, then use the highest version if possible.
    user_id = kwargs.pop('user_id', None)
    username = kwargs.pop('username', None)
    password = kwargs.pop('password', None)
    user_domain_name = kwargs.pop('user_domain_name', None)
    user_domain_id = kwargs.pop('user_domain_id', None)
    # project and tenant can be used interchangeably
    project_id = (kwargs.pop('project_id', None) or
                  kwargs.pop('tenant_id', None))
    project_name = (kwargs.pop('project_name', None) or
                    kwargs.pop('tenant_name', None))
    project_domain_id = kwargs.pop('project_domain_id', None)
    project_domain_name = kwargs.pop('project_domain_name', None)
    auth = None

    use_domain = (user_domain_id or
                  user_domain_name or
                  project_domain_id or
                  project_domain_name)
    use_v3 = v3_auth_url and (use_domain or (not v2_auth_url))
    use_v2 = v2_auth_url and not use_domain

    if use_v3:
        auth = v3_auth.Password(
            v3_auth_url,
            user_id=user_id,
            username=username,
            password=password,
            user_domain_id=user_domain_id,
            user_domain_name=user_domain_name,
            project_id=project_id,
            project_name=project_name,
            project_domain_id=project_domain_id,
            project_domain_name=project_domain_name)
        ks_desc += " keystone-v3 %s" % (project_id or project_name)
        if project_domain_id or project_domain_name:
            ks_desc += "%s" % (project_domain_id or project_domain_name)
    elif use_v2:
        auth = v2_auth.Password(
            v2_auth_url,
            username,
            password,
            tenant_id=project_id,
            tenant_name=project_name)
        ks_desc += " keystone-v2 %s" % (project_id or project_name)
    else:
        # if we get here it means domain information is provided
        # (caller meant to use Keystone V3) but the auth url is
        # actually Keystone V2. Obviously we can't authenticate a V3
        # user using V2.
        exc.CommandError("Credential and auth_url mismatch. The given "
                         "auth_url is using Keystone V2 endpoint, which "
                         "may not able to handle Keystone V3 credentials. "
                         "Please provide a correct Keystone V3 auth_url.")

    ks_session.auth = auth
    return ks_session, ks_desc


def _get_kwargs_for_create_session(args):
    if not args.os_username:
        raise exc.CommandError(
            _("You must provide a username for %s" % args.source_or_dest))

    if not args.os_password:
        # No password, If we've got a tty, try prompting for it
        if hasattr(sys.stdin, 'isatty') and sys.stdin.isatty():
            # Check for Ctl-D
            try:
                args.os_password = getpass.getpass('OS Password for %s: ' % args.source_or_dest)
            except EOFError:
                pass
        # No password because we didn't have a tty or the
        # user Ctl-D when prompted.
        if not args.os_password:
            raise exc.CommandError(
                _("You must provide a password for %s" % args.source_or_dest))

    if not args.os_auth_url:
        raise exc.CommandError(
            _("You must provide an auth url for %s" % args.source_or_dest))

    kwargs = {
        'auth_url': args.os_auth_url,
        'username': args.os_username,
        'user_id': args.os_user_id,
        'user_domain_id': args.os_user_domain_id,
        'user_domain_name': args.os_user_domain_name,
        'password': args.os_password,
        'project_name': args.os_project_name,
        'project_id': args.os_project_id,
        'project_domain_name': args.os_project_domain_name,
        'project_domain_id': args.os_project_domain_id,
        'insecure': args.insecure,
        'cacert': args.os_cacert,
        'cert': args.os_cert,
        'key': args.os_key
    }
    return kwargs
