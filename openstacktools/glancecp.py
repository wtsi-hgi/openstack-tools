#!/usr/bin/env python3
################################################################################
# Copyright (c) 2016 Genome Research Ltd.
#
# Author: Joshua C. Randall <jcrandall@alum.mit.edu>
#
# This file is part of glancecp.
#
# glancecp is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <http://www.gnu.org/licenses/>.
################################################################################
#
# Portions of this code are based on openstack/python-glanceclient
# (http://git.openstack.org/cgit/openstack/python-glanceclient/)
# which was distributed with the following copyright and license:
#
# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
################################################################################

"""
Copies images from one OpenStack glance environment to another.
"""

import argparse
import copy
import getpass
import io
import os.path
import re
import sys
import traceback

from configparser import ConfigParser

from oslo_utils import encodeutils
import six.moves.urllib.parse as urlparse

import glanceclient
from glanceclient._i18n import _
from glanceclient.common import utils
from glanceclient import exc

from keystoneclient.auth.identity import v2 as v2_auth
from keystoneclient.auth.identity import v3 as v3_auth
from keystoneclient import discover
from keystoneclient import exceptions as ks_exc
from keystoneclient import session

from keystoneauth1 import loading

SUPPORTED_VERSIONS = [1, 2]

class GlanceCPShell(object):
    def load_config(self, config_file):
        if os.path.isfile(config_file):
            config = ConfigParser(default_section="common")
            config.read(config_file)
            return config
        else:
            if os.path.exists(config_file):
                raise IsADirectoryError("Config path %s exists but is not a file" % config_file)
            else:
                return ConfigParser()

    def parse_specification(self, spec):
        env_name = ""
        id_or_name = ""
        # match <os_environment>:<image_id|image_name>
        m = re.fullmatch('^(?P<env>[a-zA-Z0-9_]*):(?P<id_or_name>.*)$', spec)
        if m:
            env_name = m.group('env')
            id_or_name = m.group('id_or_name')
            return env_name, id_or_name

        # match <os_environment>:"<image_id|image_name>" or <os_environment>:'<image_id|image_name>'
        m = re.fullmatch('^(?P<env>[a-zA-Z0-9_]*):(["\'])(?P<id_or_name>.*)\2$', spec)
        if m:
            env_name = m.group('env')
            id_or_name = m.group('id_or_name')
            return env_name, id_or_name

        # match "<image_id|image_name>" or '<image_id|image_name>' or <image_id|image_name>
        m = re.fullmatch(r"(?P<quote>['\"]|)(?P<id_or_name>.*?)(?P=quote)", spec)
        if m:
            id_or_name = m.group('id_or_name')
            return env_name, id_or_name

        raise ValueError("Failed to parse specification [%s]" % spec)

    def env_section(self, env_name):
        section = env_name
        if section == "":
            section = "common"
        return section

    def get_default(self, env_name, config, *params, default=""):
        # try to get each param in the *params list in order from env_name section of config (or the common section if env_name is empty)
        # failing that, if env_name is not empty try to get it from an environment variable named <ENV>_<PARAM> (e.g. myenv_OS_AUTH_URL)
        # failing that, for OS_PROJECT_NAME if env_name is not empty set it to env_name
        # failing that, try to get it from an environment variable named <PARAM> (e.g. OS_AUTH_URL)
        # failing that, return the value given in the default keyword argument
        section = self.env_section(env_name)
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
        return utils.env(*params, default=default)

    def get_help(self, env_name, *params):
        if len(params) == 0:
            raise ValueError("get_help called with no params")
        defaults = []
        section = self.env_section(env_name)
        for param in params:
            defaults.append("config option %s in section [%s]" % (param, section))
        if env_name != "":
            for param in params:
                defaults.append("env[%s_%s]" % (env_name, param))
        for param in params:
            if param == "OS_PROJECT_NAME":
                defaults.append("the env_name in the specification (%s)" % (env_name))
        for param in params:
            defaults.append("env[%s]" % (param))
        if len(defaults) > 1:
            defaults[-1] = "or "+defaults[-1]
        return 'Defaults to: %s' % (', '.join(defaults))

    def add_openstack_args(self, parser, source_or_dest, env_name, config):
        parser.add_argument('--%s-os-auth-url' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_AUTH_URL'),
                            help=self.get_help(env_name, 'OS_AUTH_URL'))

        parser.add_argument('--%s_os_auth_url' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-username' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_USERNAME'),
                            help=self.get_help(env_name, 'OS_USERNAME'))

        parser.add_argument('--%s_os_username' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-user-id' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_USER_ID'),
                            help=self.get_help(env_name, 'OS_USER_ID'))

        parser.add_argument('--%s_os_user_id' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-user-domain-name' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_USER_DOMAIN_NAME'),
                            help=self.get_help(env_name, 'OS_USER_DOMAIN_NAME'))

        parser.add_argument('--%s_os_user_domain_name' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-user-domain-id' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_USER_DOMAIN_ID'),
                            help=self.get_help(env_name, 'OS_USER_DOMAIN_ID'))

        parser.add_argument('--%s_os_user_domain_id' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-password' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_PASSWORD'),
                            help=self.get_help(env_name, 'OS_PASSWORD')+'''
                               WARNING: specifying your password on the command-line
                               may expose it to other users on the same machine.
                            ''')

        parser.add_argument('--%s_os_password' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-project-name' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_PROJECT_NAME'),
                            help=self.get_help(env_name, 'OS_PROJECT_NAME'))

        parser.add_argument('--%s_os_project_name' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-project-id' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_PROJECT_ID'),
                            help=self.get_help(env_name, 'OS_PROJECT_ID'))

        parser.add_argument('--%s_os_project_id' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-tenant-name' % source_or_dest,
                            '--%s_os_tenant_name' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_TENANT_NAME'),
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-tenant-id' % source_or_dest,
                            '--%s_os_tenant_id' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_TENANT_ID'),
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-project-domain-name' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_PROJECT_DOMAIN_NAME'),
                            help=self.get_help(env_name, 'OS_PROJECT_DOMAIN_NAME'))

        parser.add_argument('--%s_os_project_domain_name' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-project-domain-id' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_PROJECT_DOMAIN_ID'),
                            help=self.get_help(env_name, 'OS_PROJECT_DOMAIN_ID'))

        parser.add_argument('--%s_os_project_domain_id' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-region-name' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_REGION_NAME'),
                            help=self.get_help(env_name, 'OS_REGION_NAME'))

        parser.add_argument('--%s_os_region_name' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-auth-token' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_AUTH_TOKEN'),
                            help=self.get_help(env_name, 'OS_AUTH_TOKEN'))

        parser.add_argument('--%s_os_auth_token' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-auth-type' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_AUTH_TYPE'),
                            help=self.get_help(env_name, 'OS_AUTH_TYPE'))

        parser.add_argument('--%s_os_auth_type' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-service-type' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_SERVICE_TYPE'),
                            help=self.get_help(env_name, 'OS_SERVICE_TYPE'))

        parser.add_argument('--%s_os_service_type' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-endpoint-type' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_ENDPOINT_TYPE'),
                            help=self.get_help(env_name, 'OS_ENDPOINT_TYPE'))

        parser.add_argument('--%s_os_endpoint_type' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-cacert' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_CACERT'),
                            help=self.get_help(env_name, 'OS_CACERT'))

        parser.add_argument('--%s_os_cacert' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-cert' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_CERT'),
                            help=self.get_help(env_name, 'OS_CERT'))

        parser.add_argument('--%s_os_cert' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-key' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_KEY'),
                            help=self.get_help(env_name, 'OS_KEY'))

        parser.add_argument('--%s_os_key' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-image-url' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_IMAGE_URL'),
                            help=self.get_help(env_name, 'OS_IMAGE_URL'))

        parser.add_argument('--%s_os_image_url' % source_or_dest,
                            help=argparse.SUPPRESS)

        parser.add_argument('--%s-os-image-api-version' % source_or_dest,
                            default=self.get_default(env_name, config, 'OS_IMAGE_API_VERSION', default="2"),
                            help=self.get_help(env_name, 'OS_IMAGE_API_VERSION'))

        parser.add_argument('--%s_os_image_api_version' % source_or_dest,
                            help=argparse.SUPPRESS)



    def parse_args(self, argv, initial=True, source_env="", dest_env="", config=ConfigParser()):
        parser = argparse.ArgumentParser(
            prog="glancecp",
            description=__doc__.strip(),
            add_help=(not initial),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        parser.add_argument("source", help='''
               A specification of the source image, in the format
               [<os_environment>:]<image_id|image_name>, where <os_environment>
               names an OpenStack environment from which to copy the source image
               which must match the regex [a-zA-Z0-9_]+ and <image_id|image_name>
               can optionally be single or double-quoted.
        ''')

        parser.add_argument("dest", help='''
               A specification of the destination image, in the format
               [<os_environment>:]<image_id|image_name>, where <os_environment>
               names an OpenStack environment from which to copy the source image
               which must match the regex [a-zA-Z0-9_]+ and <image_id|image_name>
               can optionally be single or double-quoted.
        ''')

        parser.add_argument("--config",
            default=utils.env('GLANCECP_CONFIG_FILE', default="glancecp.config"),
            help='''
               Path to an INI-style config file (or '-' to read configuration from
               standard input).

               Values of <os_environment> in the source and destination
               specifications will be matched against a section of the same name
               in the INI file.

               Properties within each section match the names of the usual
               OpenStack environment variables. For example:
                 OS_AUTH_URL
                 OS_USERNAME
                 OS_PASSWORD
                 OS_TENANT_ID

               A special [common] section can also be used to define
               defaults that apply to all sections, and properties
               defined there would also apply when an <os_environment>
               is omitted from the source and/or destination specification.

               If this option is not specified, the default will be to
               attempt to load configuration from the path set in the
               environment variable GLANCECP_CONFIG_FILE. If unset, it
               will attempt to read configuration from a file called
               'glancecp.config' in the current directory.
        ''')

        parser.add_argument("--properties",
            default="min_disk,min_ram",
            help='''
               Comma-delimited list of properties to copy from the source
               image to the destination image. Note that some properties
               are read-only and attempting to set them will cause the copy
               to fail.
        ''')

        parser.add_argument("--duplicate-name-strategy",
            default="none",
            choices=["none", "allow", "replace"],
            help='''
               Strategy for handling duplicate names at destination:
                 - "none":    Do not allow duplicate names, copying will fail
                              if the destination already exists.
                 - "allow":   Allow creation of destination even if images with
                              the destination name already exist.
                 - "replace": Remove any images already present with the
                              destination name and replace them with the
                              source image.
        ''')
        parser.add_argument("--duplicate_name_strategy",
                            help=argparse.SUPPRESS)

        self.add_openstack_args(parser, "source", source_env, config)
        self.add_openstack_args(parser, "dest", dest_env, config)

        parser.add_argument('--insecure', default=False,
            help='''
               Explicitly allow client to perform "insecure" TLS
               (https) requests. The server's certificate will not be
               verified against any certificate authorities. This
               option should be used with caution.
        ''')

        parser.add_argument('--timeout', default=False,
            help="Set request timeout (in seconds).")

        if initial:
          argv_copy = copy.deepcopy(argv)
          args, extra = parser.parse_known_args(argv_copy)
          return args
        else:
          return parser.parse_args(argv)

    def _get_image_url(self, args):
        """Translate the available url-related options into a single string.

        Return the endpoint that should be used to talk to Glance if a
        clear decision can be made. Otherwise, return None.
        """
        if args.os_image_url:
            return args.os_image_url
        else:
            return None

    def _discover_auth_versions(self, session, auth_url):
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

    def _get_keystone_session(self, **kwargs):
        ks_session = session.Session.construct(kwargs)
        ks_desc = ""

        # discover the supported keystone versions using the given auth url
        auth_url = kwargs.pop('auth_url', None)
        (v2_auth_url, v3_auth_url) = self._discover_auth_versions(
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

    def _get_kwargs_for_create_session(self, args):
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

        # Validate password flow auth
        project_info = (
            args.os_tenant_name or args.os_tenant_id or (
                args.os_project_name and (
                    args.os_project_domain_name or
                    args.os_project_domain_id
                )
            ) or args.os_project_id
        )

        if not project_info:
            print("no project_info: args=[%s]" % args)
            raise exc.CommandError(
                _("You must provide a project_id or a project_name"
                  "with either project_domain_name or project_domain_id for %s" % args.source_or_dest))

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
            'tenant_name': args.os_tenant_name,
            'tenant_id': args.os_tenant_id,
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

    def _get_versioned_client(self, api_version, args):
        endpoint = self._get_image_url(args)
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
            kwargs = self._get_kwargs_for_create_session(args)
            ks_session, ks_desc = self._get_keystone_session(**kwargs)
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

    def authenticate_client(self, source_or_dest, args):
        os_args = {k[len(source_or_dest)+1:] : v for k, v in vars(args).items() if k.startswith("%s_os_" % source_or_dest)}
        for general_arg in ['insecure','timeout']:
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

        client, client_desc = self._get_versioned_client(api_version, os_args)
        return client, client_desc

    def main(self, argv):
        # parse args initially with no help option and ignoring unknown
        init_args = self.parse_args(argv, initial=True)

        # attempt to load configuration
        config = self.load_config(init_args.config)

        # parse source and destination
        source_env, source_id_or_name = self.parse_specification(init_args.source)
        dest_env, dest_name = self.parse_specification(init_args.dest)

        # parse args again, this time with help enabled
        args = self.parse_args(argv, initial=False, source_env=source_env, dest_env=dest_env, config=config)

        # authenticate glance client for source and dest environments
        source_client, source_client_desc = self.authenticate_client("source", args)
        dest_client, dest_client_desc = self.authenticate_client("dest", args)

        # find source image
        source_image = None
        try:
            source_image = source_client.images.get(source_id_or_name)
        except exc.HTTPNotFound:
            found = False
            for image in source_client.images.list():
                if image.name == source_id_or_name:
                    if found:
                        utils.exit("Multiple source images were found named %s, cannot continue." % source_id_or_name)
                    else:
                        source_image = source_client.images.get(image.id)
                        found = True
        if not source_image:
            utils.exit("Source image not found: %s" % source_id_or_name)

        # prepare destination image properties
        dest_image_properties = dict()

        # copy essential properties (cannot upload without these)
        for key in ['disk_format', 'container_format']:
            dest_image_properties[key] = source_image[key]

        # copy extra properties according to user list
        for key in args.properties.split(','):
            k = key.strip()
            dest_image_properties[k] = source_image[k]

        # set or copy name
        if dest_name != "":
            dest_image_properties['name'] = dest_name
        else:
            dest_image_properties['name'] = source_image['name']

        if args.duplicate_name_strategy != "allow":
            # check for existing images by that name at destination
            for image in dest_client.images.list():
                if image.name == dest_image_properties['name']:
                    if args.duplicate_name_strategy == "replace":
                        print("deleting existing image %s ('%s')" % (image.id, image.name), file=sys.stderr)
                        try:
                            dest_client.images.delete(image.id)
                        except Exception as e:
                            utils.exit("Failed to delete image with conflicting "
                                       "name '%s': %s" % (image.name, e))
                    elif args.duplicate_name_strategy == "none":
                        utils.exit("An image named '%s' is already present at "
                                   "destination. Please change to a unique name, "
                                   "use the '--duplicate-name-strategy=allow' "
                                   "option to allow creation of images with "
                                   "duplicate names, or use the "
                                   "'--duplicate-name-strategy=replace' option "
                                   "to remove any other images with the "
                                   "destination name."
                                   % dest_image_properties['name'])

        # inform user we are copying
        # TODO: only if verbose?
        print("copying source image %s ('%s') from %s to destination image '%s' on %s" % (source_image.id, source_image.name, source_client_desc, dest_image_properties['name'], dest_client_desc), file=sys.stderr)

        # create destination image
        try:
            dest_image = dest_client.images.create(**dest_image_properties)
        except Exception as e:
            utils.exit("Failed to create destination image (exception type %s): %s" % (type(e), e))

        # copy data from source to destination
        try:
            dest_client.images.upload(dest_image.id, data_to_upload_stream(source_client.images.data(source_image.id)))
        except Exception as ue:
            try:
                dest_client.images.delete(dest_image.id)
            except Exception as de:
                utils.exit("Failed to delete image after upload failed (exception type %s): %s" % (type(de), de))
            utils.exit("Failed to upload image (exception type %s): %s" % (type(ue), ue))

        # tell the user the id of their new image
        print(dest_image.id)

def debug_enabled(argv):
    if bool(utils.env('GLANCECP_DEBUG')) is True:
        return True
    if '--debug' in argv or '-d' in argv:
        return True
    return False


def data_to_upload_stream(data, buffer_size=io.DEFAULT_BUFFER_SIZE):
    class UploadStream(io.RawIOBase):
        def __init__(self, data_iter):
            self.remaining_data = None
            self.data_iter = data_iter
        def readable(self):
            return True
        def readinto(self, b):
            try:
                max_chunk_size = len(b)
                chunk = self.remaining_data or next(self.data_iter)
                output, self.remaining_data = chunk[:max_chunk_size], chunk[max_chunk_size:]
                b[:len(output)] = output
                return len(output)
            except StopIteration:
                return 0
    return io.BufferedReader(UploadStream(iter(data)), buffer_size=buffer_size)

def main():
    try:
        argv = [encodeutils.safe_decode(a) for a in sys.argv[1:]]
        GlanceCPShell().main(argv)
    except KeyboardInterrupt:
        utils.exit('... terminating glancecp', exit_code=130)
    except Exception as e:
        if debug_enabled(argv) is True:
            traceback.print_exc()
        utils.exit(encodeutils.exception_to_unicode(e))

if __name__ == "__main__":
    main()
