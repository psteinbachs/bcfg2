'''Admin interface for dynamic reports'''
import Bcfg2.Logger
import Bcfg2.Server.Admin
import datetime
import os
import logging
import pickle
import platform
import sys
import traceback

from Bcfg2.Compat import md5

from Bcfg2 import settings

# Load django and reports stuff _after_ we know we can load settings
from django.core import management
from Bcfg2.Reporting.utils import *

project_directory = os.path.dirname(settings.__file__)
project_name = os.path.basename(project_directory)
sys.path.append(os.path.join(project_directory, '..'))
project_module = __import__(project_name, '', '', [''])
sys.path.pop()

# Set DJANGO_SETTINGS_MODULE appropriately.
os.environ['DJANGO_SETTINGS_MODULE'] = '%s.settings' % project_name
from django.db import connection, transaction

from Bcfg2.Reporting.models import Client, Interaction, \
    Performance, Bundle, Group, FailureEntry, PathEntry, \
    PackageEntry, ServiceEntry, ActionEntry


def printStats(fn):
    """
    Print db stats.

    Decorator for purging.  Prints database statistics after a run.
    """
    def print_stats(self, *data):
        start_client = Client.objects.count()
        start_i = Interaction.objects.count()
        start_ei = Entries_interactions.objects.count()
        start_perf = Performance.objects.count()

        fn(self, *data)

        self.log.info("Clients removed: %s" %
                      (start_client - Client.objects.count()))
        self.log.info("Interactions removed: %s" %
                      (start_i - Interaction.objects.count()))
        self.log.info("Interactions->Entries removed: %s" %
                      (start_ei - 0))
        #              (start_ei - Entries_interactions.objects.count()))
        self.log.info("Metrics removed: %s" %
                      (start_perf - Performance.objects.count()))

    return print_stats


class Reports(Bcfg2.Server.Admin.Mode):
    '''Admin interface for dynamic reports'''
    __shorthelp__ = "Manage dynamic reports"
    __longhelp__ = (__shorthelp__)
    django_commands = ['dbshell', 'shell', 'sqlall', 'validate']
    __usage__ = ("bcfg2-admin reports [command] [options]\n"
                 "\n"
                 "  Commands:\n"
                 "    init                 Initialize the database\n"
                 "    purge                Purge records\n"
                 "      --client [n]       Client to operate on\n"
                 "      --days   [n]       Records older then n days\n"
                 "      --expired          Expired clients only\n"
                 "    scrub                Scrub the database for duplicate reasons and orphaned entries\n"
                 "    update               Apply any updates to the reporting database\n"
                 "\n"
                 "  Django commands:\n    " \
                 + "\n    ".join(django_commands))

    def __init__(self, setup):
        Bcfg2.Server.Admin.Mode.__init__(self, setup)
        try:
            import south
        except ImportError:
            print "Django south is required for Reporting"
            raise SystemExit(-3)

    def __call__(self, args):
        if len(args) == 0 or args[0] == '-h':
            print(self.__usage__)
            raise SystemExit(0)

        # FIXME - dry run

        if args[0] in self.django_commands:
            self.django_command_proxy(args[0])
        elif args[0] == 'scrub':
            self.scrub()
        elif args[0] in ['init', 'update', 'syncdb']:
            if self.setup['debug']:
                vrb = 2
            elif self.setup['verbose']:
                vrb = 1
            else:
                vrb = 0
            try:
                management.call_command("syncdb", verbosity=vrb)
                management.call_command("migrate", verbosity=vrb)
            except:
                print("Update failed: %s" % traceback.format_exc().splitlines()[-1])
                raise SystemExit(-1)
        elif args[0] == 'purge':
            expired = False
            client = None
            maxdate = None
            state = None
            i = 1
            while i < len(args):
                if args[i] == '-c' or args[i] == '--client':
                    if client:
                        self.errExit("Only one client per run")
                    client = args[i + 1]
                    print(client)
                    i = i + 1
                elif args[i] == '--days':
                    if maxdate:
                        self.errExit("Max date specified multiple times")
                    try:
                        maxdate = datetime.datetime.now() - datetime.timedelta(days=int(args[i + 1]))
                    except:
                        self.log.error("Invalid number of days: %s" % args[i + 1])
                        raise SystemExit(-1)
                    i = i + 1
                elif args[i] == '--expired':
                    expired = True
                i = i + 1
            if expired:
                if state:
                    self.log.error("--state is not valid with --expired")
                    raise SystemExit(-1)
                self.purge_expired(maxdate)
            else:
                self.purge(client, maxdate, state)
        else:
            print("Unknown command: %s" % args[0])

    @transaction.commit_on_success
    def scrub(self):
        ''' Perform a thorough scrub and cleanup of the database '''

        # Cleanup unused entries
        for cls in (Group, Bundle, FailureEntry, ActionEntry, PathEntry, 
                PackageEntry, PathEntry):
            try:
                start_count = cls.objects.count()
                cls.prune_orphans()
                self.log.info("Pruned %d %s records" % \
                    (start_count - cls.objects.count(), cls.__class__.__name__))
            except:
                print("Failed to prune %s: %s" % \
                    (cls.__class__.__name__, 
                    traceback.format_exc().splitlines()[-1]))


    def django_command_proxy(self, command):
        '''Call a django command'''
        if command == 'sqlall':
            management.call_command(command, 'Reporting')
        else:
            management.call_command(command)


    @printStats
    def purge(self, client=None, maxdate=None, state=None):
        '''Purge historical data from the database'''

        filtered = False  # indicates whether or not a client should be deleted

        if not client and not maxdate and not state:
            self.errExit("Reports.prune: Refusing to prune all data")

        ipurge = Interaction.objects
        if client:
            try:
                cobj = Client.objects.get(name=client)
                ipurge = ipurge.filter(client=cobj)
            except Client.DoesNotExist:
                self.log.error("Client %s not in database" % client)
                raise SystemExit(-1)
            self.log.debug("Filtering by client: %s" % client)

        if maxdate:
            filtered = True
            if not isinstance(maxdate, datetime.datetime):
                raise TypeError("maxdate is not a DateTime object")
            self.log.debug("Filtering by maxdate: %s" % maxdate)
            ipurge = ipurge.filter(timestamp__lt=maxdate)

        if settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
            grp_limit = 100
        else:
            grp_limit = 1000
        if state:
            filtered = True
            if state not in ('dirty', 'clean', 'modified'):
                raise TypeError("state is not one of the following values " + \
                                "('dirty','clean','modified')")
            self.log.debug("Filtering by state: %s" % state)
            ipurge = ipurge.filter(state=state)

        count = ipurge.count()
        rnum = 0
        try:
            while rnum < count:
                grp = list(ipurge[:grp_limit].values("id"))
                # just in case...
                if not grp:
                    break
                Interaction.objects.filter(id__in=[x['id'] for x in grp]).delete()
                rnum += len(grp)
                self.log.debug("Deleted %s of %s" % (rnum, count))
        except:
            self.log.error("Failed to remove interactions")
            (a, b, c) = sys.exc_info()
            msg = traceback.format_exception(a, b, c, limit=2)[-1][:-1]
            del a, b, c
            self.log.error(msg)

        # bulk operations bypass the Interaction.delete method
        self.log.debug("Pruning orphan Performance objects")
        Performance.prune_orphans()
        self.log.debug("Pruning orphan Reason objects")
        Reason.prune_orphans()

        if client and not filtered:
            '''Delete the client, ping data is automatic'''
            try:
                self.log.debug("Purging client %s" % client)
                cobj.delete()
            except:
                self.log.error("Failed to delete client %s" % client)
                (a, b, c) = sys.exc_info()
                msg = traceback.format_exception(a, b, c, limit=2)[-1][:-1]
                del a, b, c
                self.log.error(msg)

    @printStats
    def purge_expired(self, maxdate=None):
        '''Purge expired clients from the database'''

        if maxdate:
            if not isinstance(maxdate, datetime.datetime):
                raise TypeError("maxdate is not a DateTime object")
            self.log.debug("Filtering by maxdate: %s" % maxdate)
            clients = Client.objects.filter(expiration__lt=maxdate)
        else:
            clients = Client.objects.filter(expiration__isnull=False)

        for client in clients:
            self.log.debug("Purging client %s" % client)
            Interaction.objects.filter(client=client).delete()
            client.delete()
        self.log.debug("Pruning orphan Performance objects")
        Performance.prune_orphans()
