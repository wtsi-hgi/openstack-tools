import argparse
from configparser import ConfigParser

from glanceclient.common import utils


def add_openstack_args(parser, env_name="", config=ConfigParser(), prefix=None):
    hyphen_prefix = "%s-" % prefix if prefix else ""
    underscore_prefix = "%s_" % prefix if prefix else ""

    parser.add_argument('--%sos-auth-url' % hyphen_prefix,
                        default=get_default(config, 'OS_AUTH_URL', env_name=env_name),
                        help=get_help(env_name, 'OS_AUTH_URL'))

    parser.add_argument('--%sos_auth_url' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-username' % hyphen_prefix,
                        default=get_default(config, 'OS_USERNAME', env_name=env_name),
                        help=get_help(env_name, 'OS_USERNAME'))

    parser.add_argument('--%sos_username' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-user-id' % hyphen_prefix,
                        default=get_default(config, 'OS_USER_ID', env_name=env_name),
                        help=get_help(env_name, 'OS_USER_ID'))

    parser.add_argument('--%sos_user_id' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-user-domain-name' % hyphen_prefix,
                        default=get_default(config, 'OS_USER_DOMAIN_NAME', env_name=env_name),
                        help=get_help(env_name, 'OS_USER_DOMAIN_NAME'))

    parser.add_argument('--%sos_user_domain_name' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-user-domain-id' % hyphen_prefix,
                        default=get_default(config, 'OS_USER_DOMAIN_ID', env_name=env_name),
                        help=get_help(env_name, 'OS_USER_DOMAIN_ID'))

    parser.add_argument('--%sos_user_domain_id' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-password' % hyphen_prefix,
                        default=get_default(config, 'OS_PASSWORD', env_name=env_name),
                        help=get_help(env_name, 'OS_PASSWORD') + '''
                           WARNING: specifying your password on the command-line
                           may expose it to other users on the same machine.
                        ''')

    parser.add_argument('--%sos_password' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-project-name' % hyphen_prefix,
                        default=get_default(config, 'OS_PROJECT_NAME', 'OS_TENANT_NAME', env_name=env_name),
                        help=get_help(env_name, 'OS_PROJECT_NAME', 'OS_TENANT_NAME'))

    parser.add_argument('--%sos_project_name' % underscore_prefix,
                        '--%sos-tenant-name' % hyphen_prefix,
                        '--%sos_tenant_name' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-project-id' % hyphen_prefix,
                        default=get_default(config, 'OS_PROJECT_ID', 'OS_TENANT_ID', env_name=env_name),
                        help=get_help(env_name, 'OS_PROJECT_ID', 'OS_TENANT_ID'))

    parser.add_argument('--%sos_project_id' % underscore_prefix,
                        '--%sos-tenant-id' % hyphen_prefix,
                        '--%sos_tenant_id' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-project-domain-name' % hyphen_prefix,
                        default=get_default(config, 'OS_PROJECT_DOMAIN_NAME', env_name=env_name),
                        help=get_help(env_name, 'OS_PROJECT_DOMAIN_NAME'))

    parser.add_argument('--%sos_project_domain_name' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-project-domain-id' % hyphen_prefix,
                        default=get_default(config, 'OS_PROJECT_DOMAIN_ID', env_name=env_name),
                        help=get_help(env_name, 'OS_PROJECT_DOMAIN_ID'))

    parser.add_argument('--%sos_project_domain_id' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-region-name' % hyphen_prefix,
                        default=get_default(config, 'OS_REGION_NAME', env_name=env_name),
                        help=get_help(env_name, 'OS_REGION_NAME'))

    parser.add_argument('--%sos_region_name' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-auth-token' % hyphen_prefix,
                        default=get_default(config, 'OS_AUTH_TOKEN', env_name=env_name),
                        help=get_help(env_name, 'OS_AUTH_TOKEN'))

    parser.add_argument('--%sos_auth_token' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-auth-type' % hyphen_prefix,
                        default=get_default(config, 'OS_AUTH_TYPE', env_name=env_name),
                        help=get_help(env_name, 'OS_AUTH_TYPE'))

    parser.add_argument('--%sos_auth_type' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-service-type' % hyphen_prefix,
                        default=get_default(config, 'OS_SERVICE_TYPE', env_name=env_name),
                        help=get_help(env_name, 'OS_SERVICE_TYPE'))

    parser.add_argument('--%sos_service_type' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-endpoint-type' % hyphen_prefix,
                        default=get_default(config, 'OS_ENDPOINT_TYPE', env_name=env_name),
                        help=get_help(env_name, 'OS_ENDPOINT_TYPE'))

    parser.add_argument('--%sos_endpoint_type' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-cacert' % hyphen_prefix,
                        default=get_default(config, 'OS_CACERT', env_name=env_name),
                        help=get_help(env_name, 'OS_CACERT'))

    parser.add_argument('--%sos_cacert' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-cert' % hyphen_prefix,
                        default=get_default(config, 'OS_CERT', env_name=env_name),
                        help=get_help(env_name, 'OS_CERT'))

    parser.add_argument('--%sos_cert' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-key' % hyphen_prefix,
                        default=get_default(config, 'OS_KEY', env_name=env_name),
                        help=get_help(env_name, 'OS_KEY'))

    parser.add_argument('--%sos_key' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-image-url' % hyphen_prefix,
                        default=get_default(config, 'OS_IMAGE_URL', env_name=env_name),
                        help=get_help(env_name, 'OS_IMAGE_URL'))

    parser.add_argument('--%sos_image_url' % underscore_prefix,
                        help=argparse.SUPPRESS)

    parser.add_argument('--%sos-image-api-version' % hyphen_prefix,
                        default=get_default(config, 'OS_IMAGE_API_VERSION', default="2", env_name=env_name),
                        help=get_help(env_name, 'OS_IMAGE_API_VERSION'))

    parser.add_argument('--%sos_image_api_version' % underscore_prefix,
                        help=argparse.SUPPRESS)


def get_default(config, *params, default="", env_name=""):
    # try to get each param in the *params list in order from env_name section of config (or the common section if env_name is empty)
    # failing that, if env_name is not empty try to get it from an environment variable named <ENV>_<PARAM> (e.g. myenv_OS_AUTH_URL)
    # failing that, for OS_PROJECT_NAME if env_name is not empty set it to env_name
    # failing that, try to get it from an environment variable named <PARAM> (e.g. OS_AUTH_URL)
    # failing that, return the value given in the default keyword argument
    section = env_section(env_name)
    for param in params:
        value = config.get(section, param, fallback=None)
        if value:
            return value
    if env_name != "":
        env_params = [('%s_%s' % (env_name, param)) for param in params]
        value = utils.env(*env_params, default=None)
        if value:
            return value
        for param in params:
            if param == "OS_PROJECT_NAME":
                return env_name
            if param == "OS_TENANT_NAME":
                return env_name
    return utils.env(*params, default=default)


def get_help(env_name, *params):
    if len(params) == 0:
        raise ValueError("get_help called with no params")
    defaults = []
    section = env_section(env_name)
    for param in params:
        defaults.append("config option %s in section [%s]" % (param, section))
    if env_name != "":
        for param in params:
            defaults.append("env[%s_%s]" % (env_name, param))
        if "OS_PROJECT_NAME" in params or "OS_TENANT_NAME" in params:
            defaults.append("the env_name in the specification ('%s')" % (env_name))
    for param in params:
        defaults.append("env[%s]" % (param))
    if len(defaults) > 1:
        defaults[-1] = "or " + defaults[-1]
    return 'Defaults to: %s' % (', '.join(defaults))


def env_section(env_name):
    section = env_name
    if section == "":
        section = "common"
    return section
