import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, Future, wait
from threading import Lock
from typing import Tuple, Dict, List, Sized, Callable, Any

from glanceclient import Client
from glanceclient.exc import HTTPException

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
    outputter = print if not arguments.quiet else null_op

    client, client_description = create_authenticated_client(arguments)  # type: Tuple[Client, str]

    to_delete, to_leave, id_name_map = _get_images(client)

    if to_delete == 0:
        outputter("No images to delete")
        exit(0)

    to_delete_names = [id_name_map[image_id] for image_id in sorted(to_delete)]
    outputter("Going to permanently delete %d %s:\n%s"
              % (len(to_delete), _get_correct_image_noun(to_delete), to_delete_names))

    if not arguments.no_consent_required:
        consent = get_consent()
        if not consent:
            print("Not deleting because of invalid consent", file=sys.stderr)
            exit(1)

    _delete_images(client, to_delete, outputter, max_simultaneous_deletes=arguments.max_simultaneous_deletes)

    after_delete, _, _ = _get_images(client)
    not_deleted = [id_name_map[image_id] for image_id in sorted(list(set(to_delete).intersection(after_delete)))]
    if len(not_deleted) > 0:
        message = "Could not delete %d %s:\n%s" % (len(not_deleted), _get_correct_image_noun(not_deleted), not_deleted)
        if not arguments.ignore_delete_failures:
            print(message, file=sys.stderr)
            exit(1)
        else:
            outputter(message)
    else:
        outputter("They're all gone!")
    exit(0)


def _delete_images(client: Client, image_ids: List[str], outputter: Callable[[Any], None],
                   max_simultaneous_deletes: int=5) -> int:
    """
    Deletes the given images.
    :param client: the glance client that can access OpenStack
    :param image_ids: the identifiers of the images to delete
    :param max_simultaneous_deletes: the maximum number of deletes to request simultaneously
    :return: the number of images deleted
    """
    failed = 0
    futures = []    # type: List[Future]
    complete = 0
    complete_lock = Lock()

    def on_complete(future: Future):
        nonlocal failed, image_ids, complete
        with complete_lock:
            complete += 1
            if not future.result():
                failed += 1
            outputter("Deleted %d/%d %s (%d failed)"
                      % (complete - failed, len(image_ids), _get_correct_image_noun(image_ids), failed))

    with ThreadPoolExecutor(max_workers=max_simultaneous_deletes) as executor:
        for i in range(len(image_ids)):
            image_id = image_ids[i]
            future = executor.submit(_delete_image, client, image_id)
            future.add_done_callback(on_complete)
            futures.append(future)
    wait(futures)
    return len(image_ids) - failed


def _delete_image(client: Client, image_id: str) -> bool:
    """
    Deletes an OpenStack image with the given identifier.
    :param client: the glance client that can access OpenStack
    :param image_id: the identifier of the image to delete
    :return: whether the image was successfully deleted
    """
    try:
        client.images.delete(image_id)
        return True
    except HTTPException as e:
        print("Unable to delete image %s: %s" % (image_id, e.details), file=sys.stderr)
        return False


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
        prog="glancenuke",
        description="Tool for deleting all (non-protected) OpenStack images in a tenant",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    add_openstack_args(parser)

    parser.add_argument("-q", dest="quiet", action="store_true", default=False, help="Quiet mode (also requires -y)")
    parser.add_argument("-y", dest="no_consent_required", action="store_true", default=False,
                        help="Do not require consent before deleting images")
    parser.add_argument("-p", "--parallel-deletes", choices=range(0, 1000), type=int, default=5,
                        dest="max_simultaneous_deletes",
                        help="Maximum number of deletes to request in parallel")
    parser.add_argument("--ignore-delete-failures", dest="ignore_delete_failures", action="store_true", default=True,
                        help="Whether the failure to delete one or more images should be ignored")

    arguments = parser.parse_args(args)
    if arguments.quiet and not arguments.no_consent_required:
        print("Must require no consent to operate in quiet mode (i.e. add the -y flag)", file=sys.stderr)
        exit(1)
    return arguments


if __name__ == "__main__":
    main()
