import argparse
from typing import Tuple, Dict, List, Sized

import sys
from glanceclient import Client

from openstacktools._arguments import add_openstack_args
from openstacktools._client import create_authenticated_client
from openstacktools._helpers import get_consent, null_op

PROTECTED_PROPERTY = "protected"
ID_PROPERTY = "id"
NAME_PROPERTY = "name"


def main():
    """
    Main method.
    """
    arguments = _parse_args(sys.argv[1:])
    client, client_description = create_authenticated_client(arguments)  # type: Tuple[Client, str]

    outputter = print if not arguments.quiet else null_op

    to_delete, to_leave, id_name_map = _get_images(client)

    if to_delete == 0:
        outputter("No images to delete")
        exit(0)

    to_delete_names = [id_name_map[image_id] for image_id in sorted(to_delete)]
    outputter("Going to permanently delete %d %s:\n%s"
              % (len(to_delete), _get_correct_image_noun(to_delete), to_delete_names))

    if not arguments.no_consent:
        consent = get_consent()
        if not consent:
            print("Not deleting because of invalid consent", file=sys.stderr)
            exit(1)

    for i in range(len(to_delete)):
        image_id = to_delete[i]
        client.images.delete(image_id)
        outputter("Deleted %d of %d %s" % (i + 1, len(to_delete), _get_correct_image_noun(to_delete)))

    after_delete, _, _ = _get_images(client)
    not_deleted = [id_name_map[image_id] for image_id in sorted(list(set(to_delete).intersection(after_delete)))]
    if len(not_deleted) > 0:
        print("Could not delete %d %s:\n%s" % (len(not_deleted), _get_correct_image_noun(not_deleted), not_deleted),
              file=sys.stderr)
        exit(1)

    outputter("They're gone!")
    exit(0)


def _get_images(client: Client) -> Tuple[List[str], List[str], Dict[str, str]]:
    """
    Gets the images from OpenStack.
    :param client: glance client to access OpenStack.
    :return: tuple where the first element is the ids of images that can be deleted, the second is the ids of images
    that cannot be deleted and the third is a mapping between image ids and their friendly names
    """
    to_delete = []  # type: List[str]
    to_leave = []  # type: List[str]
    id_name_map = {}  # type: Dict[str, str]

    for image in client.images.list():
        image_id = image[ID_PROPERTY]
        id_name_map[image_id] = image[NAME_PROPERTY]
        if image[PROTECTED_PROPERTY]:
            to_leave.append(image_id)
        else:
            to_delete.append(image_id)

    return to_delete, to_leave, id_name_map


def _get_correct_image_noun(images: Sized):
    """
    Gets the correct image noun (image or images) depending on the number of images.
    :param images: the container of images
    :return: the image noun
    """
    return "image" if len(images) in [0, 1] else "images"


def _parse_args(args: List[str]):
    """
    Parses the given CLI arguments.
    :param args: CLI arguments
    :return: namespace containing the arguments
    """
    parser = argparse.ArgumentParser(
        prog="nuke",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_openstack_args(parser)

    parser.add_argument("-q", dest="quiet", action="store_true", default=False, help="Quiet mode (also requires -y)")
    parser.add_argument("-y", dest="no_consent", action="store_true", default=False,
                        help="Do not require consent before deleting images")

    arguments = parser.parse_args(args)
    if arguments.quiet and not arguments.no_consent:
        print("Must require no consent to operate in quiet mode (i.e. add the -y flag)", file=sys.stderr)
        exit(1)
    return arguments


if __name__ == "__main__":
    main()
