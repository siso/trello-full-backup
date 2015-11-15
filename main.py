#!/usr/bin/env python

import sys
import itertools
import os
import argparse
import re
import datetime
import requests
import json

# Do not download files over 100 MB by default
ATTACHMENT_BYTE_LIMIT = 100000000
ATTACHMENT_REQUEST_TIMEOUT = 30  # seconds
ATTACHMENT_DOWNLOAD_RETRIES = 3  # Retry 3 times at most
FILE_NAME_MAX_LENGTH = 255
FILTERS = ['open', 'all']

TRELLO_API = 'https://api.trello.com/1/'

# Read the API keys from the environment variables
TRELLO_API_KEY = os.getenv('TRELLO_API_KEY', '')
TRELLO_TOKEN = os.getenv('TRELLO_TOKEN', '')

auth = '?key=' + TRELLO_API_KEY + '&token=' + TRELLO_TOKEN

# Parse arguments
parser = argparse.ArgumentParser(
    description='Trello Full Backup'
)

# The destination folder to save the backup to
parser.add_argument('-d',
                    metavar='DEST',
                    nargs='?',
                    help='Destination folder')

# Backup the boards that are closed
parser.add_argument('-B', '--closed-boards',
                    dest='closed_boards',
                    action='store_const',
                    default=0,
                    const=1,
                    help='Backup closed board')

# Backup the lists that are archived
parser.add_argument('-L', '--archived-lists',
                    dest='archived_lists',
                    action='store_const',
                    default=0,
                    const=1,
                    help='Backup archived lists')

# Backup the cards that are archived
parser.add_argument('-C', '--archived-cards',
                    dest='archived_cards',
                    action='store_const',
                    default=0,
                    const=1,
                    help='Backup archived cards')

# Backup the cards that are archived
parser.add_argument('-o', '--organizations',
                    dest='orgs',
                    action='store_const',
                    default=False,
                    const=True,
                    help='Backup organizations')

# Set the size limit for the attachments
parser.add_argument('-a', '--attachment-size',
                    dest='attachment_size',
                    nargs=1,
                    type=int,
                    help='Attachment size limit in bytes')

args = parser.parse_args()

dest_dir = datetime.datetime.now().isoformat('_')
dest_dir = dest_dir.replace(':', '-').split('.')[0] + '_backup'

if args.d:
    dest_dir = args.d

if os.access(dest_dir, os.R_OK):
    print('Folder', dest_dir, 'already exists')
    sys.exit(1)

# Override new attachment size limit
if args.attachment_size:
    ATTACHMENT_BYTE_LIMIT = args.attachment_size[-1]

os.mkdir(dest_dir)
os.chdir(dest_dir)

print('==== Backup initiated')
print('Backing up to:', dest_dir)
print('Backup closed board:', bool(args.closed_boards))
print('Backup archived lists:', bool(args.archived_lists))
print('Backup archived cards:', bool(args.archived_cards))
print('Attachment size limit (bytes):', ATTACHMENT_BYTE_LIMIT)
print('==== ')
print()


def sanitize_file_name(name):
    """ Stip problematic characters for a file name """
    return re.sub(r'[<>:\/\|\?\*]', '_', name)[-FILE_NAME_MAX_LENGTH:]


def write_file(file_name, obj, dumps=True):
    """ Write <obj> to the file <file_name> """
    with open(file_name, 'w') as f:
        to_write = json.dumps(obj, indent=4) if dumps else obj
        f.write(to_write)


def filter_boards(boards):
    """ Return a list of the boards to retrieve (closed or not) """
    return [b for b in boards if not (args.closed_boards and b['closed'])]


def download_attachments(c):
    """ Download the attachments for the card <c> """
    # Only download attachments below the size limit
    attachments = [a for a in c['attachments']
                   if a['bytes'] != None and
                   a['bytes'] < ATTACHMENT_BYTE_LIMIT]

    if len(attachments) > 0:
        # Enter attachments directory
        os.mkdir('attachments')
        os.chdir('attachments')

        # Download attachments
        for id_attachment, attachment in enumerate(attachments):
            attachment_name = sanitize_file_name(str(id_attachment) +
                                                 '_' + attachment['name'])

            print('Saving attachment', attachment_name)
            try:
                content = requests.get(attachment['url'],
                                       stream=True,
                                       timeout=ATTACHMENT_REQUEST_TIMEOUT)
            except Exception:
                sys.stderr.write('Could not download ' + attachment_name)

            with open(attachment_name, 'wb') as f:
                for chunk in content.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)

        # Exit attachments directory
        os.chdir('..')


def backup_card(id_card, c):
    """ Backup the card <c> with id <id_card> """
    card_name = sanitize_file_name(str(id_card) + '_' + c['name'])
    os.mkdir(card_name)

    # Enter card directory
    os.chdir(card_name)

    meta_file_name = 'card.json'
    description_file_name = 'description.md'

    print('Saving', card_name)
    print('Saving', meta_file_name, 'and', description_file_name)
    write_file(meta_file_name, c)
    write_file(description_file_name, c['desc'], dumps=False)

    download_attachments(c)

    # Exit card directory
    os.chdir('..')


def backup_board(board):
    """ Backup the board """
    board_details = requests.get(TRELLO_API + 'boards/' + board['id'] +
                                 auth + '&' +
                                 'actions=all&' +
                                 'actions_limit=1000&' +
                                 'cards=' + FILTERS[args.archived_cards] + '&' +
                                 'card_attachments=true&' +
                                 'lists=' + FILTERS[args.archived_lists] + '&' +
                                 'members=all&' +
                                 'member_fields=all&' +
                                 'checklists=all&' +
                                 'fields=all'
                                 ).json()

    board_dir = sanitize_file_name(board_details['name'])

    os.mkdir(board_dir)

    # Enter board directory
    os.chdir(board_dir)

    file_name = board_dir + '_full.json'
    print('Saving full json for board',
          board_details['name'], 'with id', board['id'], 'to', file_name)
    write_file(file_name, board_details)

    lists = {}
    cs = itertools.groupby(board_details['cards'], key=lambda x: x['idList'])
    for list_id, cards in cs:
        lists[list_id] = sorted(list(cards), key=lambda card: card['pos'])

    for id_list, ls in enumerate(board_details['lists']):
        list_name = sanitize_file_name(str(id_list) + '_' + ls['name'])
        os.mkdir(list_name)

        # Enter list directory
        os.chdir(list_name)
        cards = lists[ls['id']] if ls['id'] in lists else []

        for id_card, c in enumerate(cards):
            backup_card(id_card, c)

        # Exit list directory
        os.chdir('..')

    # Exit sub directory
    os.chdir('..')

org_boards_data = {}

org_boards_data['me'] = requests.get(TRELLO_API + 'members/me/boards' + auth).json()

if args.orgs:
    orgs = requests.get(TRELLO_API + 'members/me/organizations' + auth).json()
    for org in orgs:
        boards_url = TRELLO_API + 'organizations/' + org['id'] + '/boards' + auth
        org_boards_data[org['name']] = requests.get(boards_url).json()

for org, boards in org_boards_data.items():
    os.mkdir(org)
    os.chdir(org)
    boards = filter_boards(boards)
    for board in boards:
        backup_board(board)
    os.chdir('..')

print('Trello Full Backup Completed!')
