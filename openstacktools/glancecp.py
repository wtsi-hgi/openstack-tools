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
import random
import time

from configparser import ConfigParser

import glanceclient
from glanceclient import exc
from glanceclient.common import utils

from keystoneauth1 import discover
from keystoneauth1 import exceptions as ks_exc
from keystoneauth1.identity import v2 as v2_auth
from keystoneauth1.identity import v3 as v3_auth
from keystoneauth1 import loading
from oslo_utils import encodeutils

from openstacktools._arguments import add_openstack_args
from openstacktools._client import create_authenticated_client


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
        m = re.fullmatch('^(?P<env>[a-zA-Z0-9_.-]*):(?P<id_or_name>.*)$', spec)
        if m:
            env_name = m.group('env')
            id_or_name = m.group('id_or_name')
            return env_name, id_or_name

        # match <os_environment>:"<image_id|image_name>" or <os_environment>:'<image_id|image_name>'
        m = re.fullmatch('^(?P<env>[a-zA-Z0-9_.-]*):(["\'])(?P<id_or_name>.*)\2$', spec)
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
               which must match the regex [a-zA-Z0-9_.-]+ and <image_id|image_name>
               can optionally be single or double-quoted.
        ''')

        parser.add_argument("dest", help='''
               A specification of the destination image, in the format
               [<os_environment>:]<image_id|image_name>, where <os_environment>
               names an OpenStack environment from which to copy the source image
               which must match the regex [a-zA-Z0-9_.-]+ and <image_id|image_name>
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
                            choices=["none", "allow", "replace", "rename"],
                            help='''
               Strategy for handling duplicate names at destination:
                 - "none":    Do not allow duplicate names, copying will fail
                              if the destination already exists.
                 - "allow":   Allow creation of destination even if images with
                              the destination name already exist.
                 - "replace": Remove any images already present with the
                              destination name and replace them with the
                              source image.
                 - "rename":  Rename any images already present with the
                              destination name to make them unique.
                              Currently this is implemented with a
                              monotonically increasing integer suffix.
        ''')
        parser.add_argument("--duplicate_name_strategy",
                            help=argparse.SUPPRESS)

        add_openstack_args(parser, source_env, config, prefix="source")
        add_openstack_args(parser, dest_env, config, prefix="dest")

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

    def authenticate_client(self, source_or_dest, env_name, args):
        os_args = {k[len(source_or_dest) + 1:]: v for k, v in vars(args).items() if
                   k.startswith("%s_os_" % source_or_dest)}
        for general_arg in ['insecure', 'timeout']:
            if general_arg in args:
                os_args[general_arg] = getattr(args, general_arg)
        return create_authenticated_client(os_args, source_or_dest)

    def random_suffix(self):
        return '%08x' % random.randrange(16**8)

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
        source_client, source_client_desc = self.authenticate_client("source", source_env, args)
        dest_client, dest_client_desc = self.authenticate_client("dest", dest_env, args)

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
        except exc.CommunicationError as ce:
            utils.exit("Communication error while attempting to get source image: %s" % (ce))
        except exc.HTTPInternalServerError as hise:
            utils.exit("Internal server error while attempting to get source image: %s" % (hise))

        if not source_image:
            utils.exit("Source image not found: %s" % source_id_or_name)

        # prepare destination image properties
        dest_image_properties = {}

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

        # inform user we are copying
        # TODO: only if verbose?
        print("copying source image %s ('%s') from %s to destination image '%s' on %s" % (
        source_image.id, source_image.name, source_client_desc, dest_image_properties['name'], dest_client_desc),
              file=sys.stderr)

        # check for duplicates and plan strategy to deal with them
        delete_images = []
        rename_images = []
        image_names = {}
        if args.duplicate_name_strategy != "allow":
            # check for existing images by that name at destination
            for image in dest_client.images.list():
                if args.duplicate_name_strategy in ["rename", "replace"]:
                    image_names[image.name] = 1
                if image.name == dest_image_properties['name']:
                    if args.duplicate_name_strategy == "replace":
                        rename_images.append(image.id)
                        delete_images.append(image.id)
                    elif args.duplicate_name_strategy == "rename":
                        rename_images.append(image.id)
                    elif args.duplicate_name_strategy == "none":
                        utils.exit("An image named '%s' is already present at "
                                   "destination. Please change to a unique name, "
                                   "use the '--duplicate-name-strategy=allow' "
                                   "option to allow creation of images with "
                                   "duplicate names, use the "
                                   "'--duplicate-name-strategy=replace' option "
                                   "to remove any other images with the "
                                   "destination name, or use the "
                                   "'--duplicate-name-strategy=rename' option "
                                   "to rename any existing images to make them "
                                   "unique." % dest_image_properties['name'])
                    else:
                        raise ValueError("Unexpected value for '--duplicate-name-strategy': %s", args.duplicate_name_strategy)

        suffix = self.random_suffix()
        for image_id in rename_images:
            while "%s.%s" % (dest_image_properties['name'], suffix) in image_names:
                suffix = random_suffix()
            new_name = "%s.%s" % (dest_image_properties['name'], suffix)
            print("renaming existing image %s to '%s'" % (image_id, new_name), file=sys.stderr)
            try:
                dest_client.images.update(image_id, name=new_name)
            except exc.CommunicationError as ce:
                utils.exit("Communication error while attempting to rename existing image: %s" % (ce))
            except exc.HTTPInternalServerError as hise:
                utils.exit("Internal server error while attempting to rename existing image: %s" % (hise))
            except exc.HTTPException as he:
                utils.exit("HTTP error while attempting to rename: %s" % (he))
            except Exception as e:
                utils.exit("Failed to rename existing image (exception type %s): %s" % (type(e), e))

        # create destination image
        print("creating image at destination: %s" % (dest_image_properties['name']), file=sys.stderr)
        try:
            dest_image = dest_client.images.create(**dest_image_properties)
        except exc.CommunicationError as ce:
            utils.exit("Communication error while attempting to create image: %s" % (ce))
        except exc.HTTPInternalServerError as hise:
            utils.exit("Internal server error while attempting to create image: %s" % (hise))
        except Exception as e:
            utils.exit("Failed to create destination image (exception type %s): %s" % (type(e), e))

        # copy data from source to destination
        failure_reason = ""
        print("copying data from source image %s to destination image %s" % (source_image.id, dest_image.id), file=sys.stderr)
        try:
            data = source_client.images.data(source_image.id)
            if data is not None:
                dest_client.images.upload(dest_image.id, data_to_upload_stream(data))
            else:
                print("WARNING: source image %s contained no data" % (source_image.id), file=sys.stderr)
        except exc.CommunicationError as ce:
            failure_reason = "Communication error while attempting to transfer image: %s" % (ce)
        except exc.HTTPInternalServerError as hise:
            failure_reason = "Internal server error while attempting to transfer image: %s" % (hise)
        except Exception as ue:
            failure_reason = "Failed to transfer image (exception type %s): %s" % (type(ue), ue)

        if failure_reason != "":
            try:
                dest_client.images.delete(dest_image.id)
            except exc.CommunicationError as ce:
                utils.exit("%s. In addition, there was a communication error while attempting to delete image after upload failed: %s" % (failure_reason, ce))
            except exc.HTTPInternalServerError as hise:
                utils.exit("%s. In addition, there was an internal server error while attempting to delete image after upload failed: %s" % (failure_reason, hise))
            except Exception as de:
                utils.exit("%s. In addition, failed to delete image after upload failed (exception type %s): %s" % (failure_reason, type(de), de))
            utils.exit(failure_reason)

        # successfully created image, now delete any images scheduled for deletion (because of duplicate_name_strategy=replace)
        for image_id in delete_images:
            print("deleting existing image %s because it had a duplicate name" % (image_id), file=sys.stderr)
            try:
                dest_client.images.delete(image_id)
            except exc.CommunicationError as ce:
                utils.exit("Communication error while attempting to delete image %s with duplicate name: %s" % (image_id, ce))
            except exc.HTTPInternalServerError as hise:
                utils.exit("Internal server error while attempting to delete image %s with duplicate name: %s" % (image_id, hise))
            except exc.HTTPConflict as hc:
                utils.exit("Conflict while attempting to delete image %s with duplicate name: %s" % (image_id, hc))
            except Exception as e:
                utils.exit("Failed to delete image %s with duplicate "
                           "name (exception type %s): %s" % (image_id, type(e), e))

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
        def __init__(self, data_iter, *args, **kwargs):
            super().__init__(*args, **kwargs)
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
    argv = [encodeutils.safe_decode(a) for a in sys.argv[1:]]
    try:
        GlanceCPShell().main(argv)
    except KeyboardInterrupt:
        utils.exit('... terminating glancecp', exit_code=130)
    except Exception as e:
        if debug_enabled(argv) is True:
            traceback.print_exc()
        utils.exit(encodeutils.exception_to_unicode(e))


if __name__ == "__main__":
    main()
