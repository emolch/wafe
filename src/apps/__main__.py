#!/usr/bin/env python

import sys
import logging
from optparse import OptionParser

from pyrocko import util

from wafe import core, config as wconfig, meta, plot

logger = logging.getLogger('wafe.main')
km = 1e3


def d2u(d):
    if isinstance(d, dict):
        return dict((k.replace('-', '_'), v) for (k, v) in d.items())
    else:
        return d.replace('-', '_')


subcommand_descriptions = {
    'extract': 'extract features from observed waveforms',
    'plot': 'plot results',
}

subcommand_usages = {
    'extract': 'extract <configfile>',
    'plot': 'plot <results-dir>'
}

subcommands = subcommand_descriptions.keys()

program_name = 'wafe'

usage_tdata = d2u(subcommand_descriptions)
usage_tdata['program_name'] = program_name

usage = '''%(program_name)s <subcommand> [options] [--] <arguments> ...

Subcommands:

    extract            %(extract)s
    plot               %(plot)s

To get further help and a list of available options for any subcommand run:

    %(program_name)s <subcommand> --help

''' % usage_tdata


def main(args=None):
    if not args:
        args = sys.argv

    args = list(sys.argv)
    if len(args) < 2:
        sys.exit('Usage: %s' % usage)

    args.pop(0)
    command = args.pop(0)

    if command in subcommands:
        globals()['command_' + d2u(command)](args)

    elif command in ('--help', '-h', 'help'):
        if command == 'help' and args:
            acommand = args[0]
            if acommand in subcommands:
                globals()['command_' + acommand](['--help'])

        sys.exit('Usage: %s' % usage)

    else:
        die('no such subcommand: %s' % command)


def add_common_options(parser):
    parser.add_option(
        '--loglevel',
        action='store',
        dest='loglevel',
        type='choice',
        choices=('critical', 'error', 'warning', 'info', 'debug'),
        default='info',
        help='set logger level to '
             '"critical", "error", "warning", "info", or "debug". '
             'Default is "%default".')


def process_common_options(options):
    util.setup_logging(program_name, options.loglevel)


def cl_parse(command, args, setup=None, details=None):
    usage = subcommand_usages[command]
    descr = subcommand_descriptions[command]

    if isinstance(usage, str):
        usage = [usage]

    susage = '%s %s' % (program_name, usage[0])
    for s in usage[1:]:
        susage += '\n%s%s %s' % (' '*7, program_name, s)

    description = descr[0].upper() + descr[1:] + '.'

    if details:
        description = description + '\n\n%s' % details

    parser = OptionParser(usage=susage, description=description)

    if setup:
        setup(parser)

    add_common_options(parser)
    (options, args) = parser.parse_args(args)
    process_common_options(options)
    return parser, options, args


def die(message, err=''):
    if err:
        sys.exit('%s: error: %s \n %s' % (program_name, message, err))
    else:
        sys.exit('%s: error: %s' % (program_name, message))


def help_and_die(parser, message):
    parser.print_help(sys.stderr)
    sys.stderr.write('\n')
    die(message)


def command_extract(args):

    def setup(parser):
        parser.add_option(
            '--debug',
            action='store_true',
            dest='debug',
            help='show processing window traces for debugging')

    parser, options, args = cl_parse('extract', args, setup)

    if len(args) != 1:
        help_and_die(parser, 'argument required')

    try:
        config_path = args[0]
        config = wconfig.read_config(config_path)
        core.run_extract(config, debug=options.debug)

    except meta.WafeError as e:
        die('command extract failed', e)


def command_plot(args):

    def setup(parser):
        pass

    parser, options, args = cl_parse('plot', args, setup)

    if len(args) != 1:
        help_and_die(parser, 'argument required')

    try:
        results_path = args[0]
        plot.run_plot(results_path)

    except meta.WafeError as e:
        die('command plot failed', e)

if __name__ == '__main__':
    main()
